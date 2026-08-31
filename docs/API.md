# API reference

Base URL `http://127.0.0.1:8000`. Interactive docs at `/docs`; the OpenAPI
schema at `/openapi.json`.

All timestamps are ISO 8601 UTC. RSSI is dBm (negative), latency milliseconds,
loss a percentage 0–100.

## Meta

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Version, active Wi-Fi backend, whether it is simulated |

## Dashboard

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/dashboard` | Link state, probes, verdict, short trend, monitor status |

## Signal Monitor

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/monitor/status` | Is it running, and since when |
| POST | `/api/monitor/start` | Begin a session. `409` if one is already running |
| POST | `/api/monitor/stop` | End it. `409` if not running |
| GET | `/api/monitor/live` | Buffered samples, so a new chart is not blank |
| GET | `/api/monitor/samples` | Stored samples, chronological. `session_id`, `minutes`, `limit` |
| GET | `/api/monitor/summary` | Aggregates over a session or time window |
| GET | `/api/monitor/roams` | Recorded roam events |
| GET | `/api/monitor/sessions` | List sessions |
| DELETE | `/api/monitor/sessions/{id}` | Delete a session and its samples |
| DELETE | `/api/monitor/samples` | Prune telemetry now; defaults to the configured retention period |
| WS | `/api/monitor/ws` | Live stream |

The socket sends `hello` (status + backfill) on connect, then `sample` and
`roam` messages as they happen, plus a `ping` keepalive every 20 s of silence.

## WiFi Scanner

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/scan` | All visible BSSIDs. Filters: `ssid`, `band`, `min_rssi` |

Returns networks strongest-first, grouped by SSID, plus channel and band usage
counts.

## Heatmap

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/heatmap/plans` | Upload a plan (multipart: `file`, `name`, `location`, `meters_per_px`) |
| GET | `/api/heatmap/plans` | List plans |
| GET/PATCH/DELETE | `/api/heatmap/plans/{id}` | Read, rename, delete |
| GET | `/api/heatmap/plans/{id}/image` | The plan image |
| GET | `/api/heatmap/measure` | One live reading, saved nowhere |
| POST | `/api/heatmap/plans/{id}/points` | Capture a survey point |
| POST | `/api/heatmap/plans/{id}/walk` | Turn a walked line into a row of points |
| GET | `/api/heatmap/plans/{id}/points` | List points |
| DELETE | `/api/heatmap/points/{id}` | Remove a point |
| POST/GET | `/api/heatmap/plans/{id}/aps` | Place / list AP markers |
| DELETE | `/api/heatmap/aps/{id}` | Remove a marker |
| GET | `/api/heatmap/plans/{id}/grid` | Interpolated coverage grid |

`POST …/points` with `measure: true` (the default) takes a live reading at that
coordinate, and with `scan: true` also records every other audible AP into
`neighbors` — which is what the redundancy map is built from. Supplying the
radio fields (and `neighbors`) explicitly is for importing a survey taken
elsewhere.

`POST …/walk` takes `start_x/start_y`, `end_x/end_y` and a list of `samples`,
each with `elapsed_ms` and its measurement. Each sample is positioned along the
line by its elapsed time as a fraction of the whole walk, which assumes a steady
pace — see the note in ARCHITECTURE.md. `GET /api/heatmap/measure` is the cheap
per-reading call a walk loops on: no scan, and the survey ping count.

`GET …/grid` accepts:

| Parameter | Meaning |
|---|---|
| `metric` | `rssi` (default) or `redundancy` |
| `ssid`, `bssid`, `band` | Filter the points the surface is built from |
| `redundancy_min_rssi` | How strong a neighbour must be to count (default -70) |
| `grid_size` | 8–160 cells across |
| `power` | IDW exponent |
| `max_influence_px` | Beyond this, cells stay unknown |

It returns a row-major `matrix` with `null` for cells no measurement can vouch
for, a `grades` matrix (coverage only), the points, the AP markers, a summary,
`available_filters` for populating dropdowns, and `scanned_points`. For
`metric=redundancy` only points that recorded a scan contribute, and the summary
carries `blind_spots` — locations with no usable alternative AP.

## Network Test

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/nettest/chain` | WiFi → Gateway → LAN → DNS → Internet |
| GET | `/api/nettest/ping` | Ping `target`, `count`, `timeout` |
| GET | `/api/nettest/dns` | Time a real resolution of `hostname` |
| GET | `/api/nettest/traceroute` | Path trace; empty if no tracer installed |
| GET | `/api/nettest/gateway` | Detected gateway and local IP |

Each chain step carries `state`: `ok`, `failed`, or `blocked` (it failed and
something upstream failed first). A step that passed is always `ok`.

## WLAN Controller

Off by default (returns `503` until configured and enabled in Settings). Talks
to a Cisco AireOS WLC over SNMP - see the README section on this feature and
the `ACCURACY NOTE` in `services/controller.py` before trusting the AP/client
tables against hardware this project has not verified.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/controller/status` | Standard MIB-II reachability check (sysDescr, sysName, uptime) |
| GET | `/api/controller/aps` | Every AP the controller manages, with each radio's channel/load |
| GET | `/api/controller/clients` | Every client currently associated, across every AP |
| GET | `/api/controller/self-check` | Does the controller agree this machine is on the AP its own radio reports? |
| GET | `/api/controller/raw` | Verification tool: raw-walk any OID subtree (`?oid=...`), unmapped |

`/self-check` returns `agrees: true/false/null` - `null` means the check could
not run (not connected, or the WLC was unreachable), which is folded into
Diagnosis as silence rather than a manufactured finding; `false` becomes the
`CONTROLLER_CLIENT_MISMATCH` finding on `GET /api/diagnosis`.

## Diagnosis

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/diagnosis` | Measure, scan, and run the rules |
| POST | `/api/diagnosis` | Run the rules over numbers you supply |

Findings carry `code`, `severity` (`info`/`warning`/`critical`), `title`,
`summary`, `causes`, `recommendations` and `evidence`, sorted worst-first.

Codes: `NOT_ASSOCIATED`, `WEAK_COVERAGE`, `UPSTREAM_DEGRADED`,
`RETRANSMISSION`, `HIGH_JITTER`, `CO_CHANNEL_CONTENTION`,
`NON_STANDARD_24_CHANNEL`, `EXCESSIVE_ROAMING`, `STICKY_CLIENT`, `SLOW_ROAM`,
`CONTROLLER_CLIENT_MISMATCH`, `HEALTHY`.

`GET /api/diagnosis` also runs the WLC self-check when the controller is
enabled, folding a mismatch in as a finding; an unreachable controller is
swallowed rather than failing the whole request.

`GET /api/diagnosis` reads the recent roam events, not just their count:
`STICKY_CLIENT` needs to know how *late* each hand-off was, which only
`from_rssi` can tell it.

## History

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/history` | Save a spot-check (`measure: true` reads live) |
| GET | `/api/history` | Paged, filtered list |
| GET | `/api/history/facets` | Distinct areas / SSIDs / BSSIDs / devices |
| GET | `/api/history/stats` | Counts by result and by area |
| GET/DELETE | `/api/history/{id}` | Read / delete one record |

Filters: `date_from`, `date_to` (both inclusive), `area`, `ssid`, `bssid`,
`device`, `result`, plus `limit` and `offset`.

## Report

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/report/history` | Export history under the same filters as the list |
| GET | `/api/report/session/{id}` | Export one monitor session |
| GET | `/api/report/heatmap/{id}` | Export a plan's survey points |

`format` is `csv`, `xlsx` or `pdf`. CSV carries a UTF-8 BOM so Excel opens Thai
area names correctly. XLSX colours the verdict column and adds a summary sheet.
PDF adds the rolled-up diagnosis findings.

## Settings

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/settings` | Current settings, whether stored, active backend |
| PUT | `/api/settings` | Replace them (validated; `422` on impossible values) |
| POST | `/api/settings/reset` | Restore defaults |
| GET | `/api/settings/backend` | Which Wi-Fi backend is active and why |

## Errors

Standard HTTP codes with a JSON `detail`. `409` means a conflicting state
(monitor already running, or stopping one that is not). `422` is validation.
