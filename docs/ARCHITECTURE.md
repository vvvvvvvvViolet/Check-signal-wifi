# Architecture

## Shape of the thing

One process. FastAPI serves the JSON API, a WebSocket for live samples, and the
built React bundle. State lives in a SQLite file next to it.

```
        ┌──────────────── browser ────────────────┐
        │  React SPA  ─── fetch ──▶ /api/…        │
        │             ◀── WebSocket ─ /api/monitor/ws
        └─────────────────────────────────────────┘
                              │
        ┌─────────────────── FastAPI ─────────────────────┐
        │  api/       routers, one per screen             │
        │  services/  the actual logic                    │
        │  wifi/      one contract, four OS backends      │
        └─────────────────────────────────────────────────┘
                    │                        │
            SQLite (WAL)          nmcli / iw / netsh / airport
                                  ping / ip route / getaddrinfo
```

It is deliberately not a client-server product. The application needs the
surveying machine's own radio, its own routing table and its own ICMP path;
none of that can be read from somewhere else. Centralising would mean shipping
an agent — a different product.

## Decisions worth explaining

### The Wi-Fi adapter is an interface with four implementations

Every OS exposes Wi-Fi through a different command-line tool with a different
output format and a different idea of what "signal" means. `wifi/base.py`
defines two dataclasses (`WifiLink`, `WifiNetwork`) and two methods
(`get_link`, `scan`); each backend's only job is to fill those in.

The parsers are pure functions over captured tool output, which is why they can
be unit-tested without a radio — `test_wifi_backends.py` feeds them real
`nmcli`, `iw` and `netsh` transcripts.

Windows deserves a note: `netsh` reports signal as a 0–100 percentage and
nothing else. The dBm figure is reconstructed with the standard linear mapping
of −90…−30, and the adapter attaches a warning that the UI surfaces, rather than
presenting a derived number as a measurement.

### The simulator is a first-class backend

`wifi/mock.py` models a client walking an oval loop past four APs: log-distance
path loss with an indoor exponent, additive noise, rate adaptation, and a sticky
client that only hands over when another AP is ~6 dB better — with a real gap
during the transition.

This is not padding. Without it there is no way to test roam detection, the
diagnosis rules, the heatmap or the exporters on a CI runner or in a container.
It is what the 90-test suite runs against.

### One measurement path, shared by every screen

Dashboard, the monitor loop, heatmap capture and history spot-checks all need
the same thing: read the radio, probe the network, grade the result. That is
`services/probe.py::take_snapshot`, and it exists once so those four screens
cannot drift into disagreeing about what "good" means.

### Grading and alerting are separate

`SignalBands` decides what a colour means (Excellent ≥ −55, Good ≥ −65,
Fair ≥ −72, Poor below). `Thresholds` decides when the app complains, and also
weighs latency, loss and jitter. Merging them would mean you could not retune
"when to warn" without silently redefining what green means on every heatmap
ever exported.

### Measurement honesty

Four specific decisions, each of which was a bug first:

1. **`ping` binary missing ≠ 100% packet loss.** `PingResult.available`
   separates "the network dropped every packet" from "this host has no ping
   binary". Without it, a container with no `iputils` reports a healthy network
   as totally failed.
2. **A failed server probe is not masked by the gateway.** The fallback keys off
   whether the server probe was *attempted*, not whether it *succeeded* —
   falling back on failure would hide the very failure worth reporting.
3. **PASS requires evidence.** If neither latency nor loss is known, the verdict
   is capped at WARNING, because a strong radio proves nothing about whether
   traffic flows.
4. **Downstream hops are not blamed for an upstream failure.** In the
   connectivity chain a hop that passed is reported as passing even if an
   earlier one failed. ICMP to the gateway is frequently filtered while
   everything above it works.

### Diagnosis keys off combinations, not single metrics

The rule that matters most is the pair:

- weak signal + bad latency → **coverage**, fix the RF
- strong signal + bad latency → **not** coverage, look upstream

The second rule states explicitly that the radio is fine, so nobody moves an
access point to fix a congested uplink. Findings carry a code, a severity,
causes and recommendations, and are sorted worst-first.

### Heatmap: IDW, bounded

Inverse-distance weighting is right for this: exact at the measured points, no
fitting, and it degrades honestly — far from any measurement the estimate
flattens toward the local mean rather than inventing structure.

Two guards keep it from lying. `max_influence_px` leaves cells with no
measurement in range empty, so unsurveyed floor renders transparent instead of
green. And because IDW is a weighted average of its inputs, it can never
extrapolate past the measured range — there is a test for exactly that.

Rendering draws the grid into an offscreen canvas at one pixel per cell and
scales it up with smoothing. The cost is proportional to the grid, not to the
size of the plan image.

### The monitor engine is a singleton

There is one radio. Two sampling loops would halve the effective interval and
interleave confusing readings, so `MonitorEngine` refuses to start twice (409).
Subscriber queues are bounded; when a stalled browser tab fills its queue the
*oldest* message is dropped, because for live monitoring the newest sample is
the one that matters.

The loop subtracts the time the work took from the sleep, so a 2-second interval
stays a 2-second interval rather than becoming 2 seconds plus however long the
pings took.

## Data model

| Table | Holds |
|---|---|
| `settings` | One row: the whole `AppSettings` blob, validated on read |
| `monitor_sessions` | One continuous-monitoring run |
| `samples` | One measurement tick, optionally tied to a session |
| `roam_events` | AP transitions observed while monitoring |
| `floor_plans` | Uploaded plan image plus its pixel dimensions |
| `survey_points` | A measurement pinned to plan coordinates |
| `ap_markers` | Where an AP physically sits on the plan |
| `test_records` | Saved spot-checks, with the findings that produced the verdict |

Settings are validated rather than trusted on read: a blob written by an older
version is missing keys, and a half-configured app is worse than a defaulted
one.

## Testing

90 tests, all against the simulated backend so they need no hardware.

| File | Covers |
|---|---|
| `test_quality.py` | Grade boundaries (including every edge), verdict precedence, the unearned-PASS rule |
| `test_wifi_backends.py` | Band/channel maths and the `nmcli`/`iw`/`netsh` parsers |
| `test_net_test.py` | Ping parsing on POSIX and Windows, and tool-missing vs. total-loss |
| `test_roaming.py` | Roam vs. network change vs. reconnect |
| `test_diagnosis.py` | Both spec scenarios, contention, channel plan, ordering |
| `test_heatmap.py` | IDW exactness, gap preservation, no extrapolation, square cells |
| `test_report.py` | CSV/Excel/PDF validity and PDF column layout |
| `test_api.py` | The HTTP surface end to end, including the monitor lifecycle |

## Known limits

- **No authentication.** It binds to localhost and is meant to run on the
  surveying machine. Putting it on a shared network needs a reverse proxy.
- **One monitor session at a time**, by design (one radio).
- **macOS BSSIDs** are hidden by the OS without Location Services permission.
- **Windows RSSI is derived** from a percentage, not measured.
- **Survey points are placed by hand.** There is no positioning system in the
  loop; the technician clicks where they are standing.
- **The heatmap interpolates in 2D** and knows nothing about walls. A high
  `max_influence_px` will happily smooth coverage straight through a firewall,
  so survey both sides of one.
