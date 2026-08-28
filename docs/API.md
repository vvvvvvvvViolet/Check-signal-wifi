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
| DELETE | `/api/monitor/samples` | Purge samples older than `older_than_days` |
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
| POST | `/api/heatmap/plans/{id}/points` | Capture a survey point |
| GET | `/api/heatmap/plans/{id}/points` | List points |
| DELETE | `/api/heatmap/points/{id}` | Remove a point |
| POST/GET | `/api/heatmap/plans/{id}/aps` | Place / list AP markers |
| DELETE | `/api/heatmap/aps/{id}` | Remove a marker |
| GET | `/api/heatmap/plans/{id}/grid` | Interpolated coverage grid |

`POST …/points` with `measure: true` (the default) takes a live reading at that
coordinate. Supplying the radio fields explicitly is for importing a survey
taken elsewhere.

`GET …/grid` accepts `grid_size` (8–160), `power` (IDW exponent) and
`max_influence_px`. It returns a row-major `matrix` of RSSI values with `null`
for cells no measurement can vouch for, a matching `grades` matrix, the points,
the AP markers and a coverage summary.

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

## Diagnosis

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/diagnosis` | Measure, scan, and run the rules |
| POST | `/api/diagnosis` | Run the rules over numbers you supply |

Findings carry `code`, `severity` (`info`/`warning`/`critical`), `title`,
`summary`, `causes`, `recommendations` and `evidence`, sorted worst-first.

Codes: `NOT_ASSOCIATED`, `WEAK_COVERAGE`, `UPSTREAM_DEGRADED`,
`RETRANSMISSION`, `HIGH_JITTER`, `CO_CHANNEL_CONTENTION`,
`NON_STANDARD_24_CHANNEL`, `EXCESSIVE_ROAMING`, `HEALTHY`.

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
