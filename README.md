# 📶 CHECK SIGNAL WIFI

WiFi monitoring, site survey and coverage heatmap for factory and warehouse
networks. Runs as a local application on the machine doing the surveying — it
reads that machine's own radio and routing table, so there is nothing to deploy
centrally.

```
CHECK SIGNAL WIFI
├── 🏠 Dashboard        Is the WiFi OK right now?
├── 📶 Signal Monitor   Continuous RSSI / latency / loss sampling
├── 🔍 WiFi Scanner     Every BSSID in range, and who shares your channel
├── 🔄 Roaming Test     Every AP hand-off, timestamped
├── 🗺️ Heatmap          Survey points on your floor plan, interpolated
├── 🧪 Network Test     WiFi → Gateway → LAN → DNS → Internet
├── 🚨 Diagnosis        Which layer is actually at fault
├── 📊 History          Saved spot-checks, filterable
├── 📄 Report           Excel / CSV / PDF export
└── ⚙️ Settings         Thresholds, ping targets, grading scale
```

---

## Quick start

```bash
# 1. Backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt

# 2. Frontend (built once, then served by the backend)
cd frontend && npm install && npm run build && cd ..

# 3. Run
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. API docs are at `/docs`.

**Want to see it populated first?** With the server running:

```bash
python scripts/seed_demo.py
```

That creates a floor plan, four APs, a 55-point survey (including a weak zone
behind steel racking) and a spread of history records.

### Development

Run the API and the Vite dev server side by side — the dev server proxies
`/api` and the WebSocket to port 8000, so there is no CORS setup:

```bash
uvicorn backend.app.main:app --reload --port 8000   # terminal 1
cd frontend && npm run dev                          # terminal 2 → :5173
```

```bash
cd backend && pytest          # 90 tests
cd backend && ruff check .
cd frontend && npm run lint   # tsc --noEmit
```

---

## Recommended stack — and why

| Layer | Choice | Why this one |
|---|---|---|
| **Backend** | Python 3.11 + FastAPI | The WiFi/ping/route tooling on every OS is a command-line program. Python shells out to them cleanly, and FastAPI gives async, WebSockets and generated API docs in one dependency. |
| **Database** | SQLite via SQLAlchemy 2.x | A survey tool is single-user and offline. SQLite is a file — no server to install on a factory laptop. WAL mode keeps the sampling writer from blocking the dashboard. Swap `CSW_DATABASE_URL` for PostgreSQL if you later centralise. |
| **Realtime** | WebSocket | Monitoring pushes a sample every 1–2 s. Polling at that rate wastes a scan per request; a socket costs one connection. |
| **Frontend** | React 18 + TypeScript + Vite | Ten screens sharing live state. TypeScript matters here because RSSI, latency and loss are all "just numbers" until the types say otherwise. |
| **Styling** | Tailwind CSS | Dense technical tables and readouts, styled without a parallel CSS file to keep in sync. |
| **Charts** | Recharts | Declarative React charts with the threshold reference lines this app needs. |
| **Heatmap** | Hand-written Canvas 2D | An interpolated grid drawn small and scaled up with smoothing. No mapping library, no WebGL, no dependency. |
| **Export** | openpyxl + ReportLab | Excel with real cell colouring; PDF laid out properly rather than printed from HTML. |

**Deliberately not used:** Electron (a browser is already on the laptop),
Redux/Zustand (screen-local state plus one WebSocket is enough), a charting
service, and any mapping library for the heatmap.

### Deploying it

The backend serves the built frontend from `frontend/dist`, so one process
serves everything on one port. For a fixed survey station, run it under
`systemd` (Linux) or NSSM (Windows). It binds `127.0.0.1` by default and has no
authentication — **do not expose it to a shared network** without putting a
reverse proxy and auth in front.

---

## Reading the numbers

### Signal grading

| Grade | RSSI |
|---|---|
| 🟢 Excellent | ≥ -55 dBm |
| 🟢 Good | -56 to -65 dBm |
| 🟡 Fair | -66 to -72 dBm |
| 🔴 Poor | < -72 dBm |

The **grading scale** decides what a colour means. The **alert thresholds**
(Settings) decide when the app complains. They are separate on purpose: a
signal can be graded Fair without being worth a warning, and the thresholds
also weigh latency and loss, which the grade does not.

### PASS / WARNING / FAIL

The verdict is the worst standing among signal, latency, packet loss and
jitter. Defaults: warn below -67 dBm, above 50 ms, or above 2% loss; fail below
-75 dBm, above 150 ms, or above 5% loss.

### What the app will not claim

Measurement honesty is a design goal, because a survey tool that cries wolf
gets ignored:

- **A missing `ping` binary is reported as unknown, not as 100% packet loss.**
  The two look nothing alike to a technician, so they do not look alike here.
- **A failed server probe is never masked by falling back to the gateway.**
- **PASS is withheld when neither latency nor loss could be measured.** A strong
  radio proves nothing about whether traffic actually flows.
- **In the Network Test chain, a hop that passed is shown as passing** even if
  an earlier one failed. ICMP to the gateway is often filtered while everything
  above it works, and calling a working DNS lookup "blocked" sends people
  hunting a fault that is not there.
- **On the heatmap, floor with no measurement within range stays transparent**
  rather than being coloured green.

---

## Wi-Fi backends

The adapter is chosen automatically. Override with `CSW_WIFI_BACKEND`.

| Platform | Tooling | Notes |
|---|---|---|
| Linux | `nmcli`, falling back to `iw` | `iw` gives true dBm and PHY rates. Best data of the three. |
| Windows | `netsh wlan` | Reports signal as a percentage only; dBm is derived and labelled as such in the UI. |
| macOS | `airport`, falling back to `system_profiler` | Sonoma removed most of `airport`. The BSSID is hidden without Location Services permission. |
| any | `mock` | Simulator — see below. |

**Linux** needs no root for `nmcli`. A full `iw scan` may need
`sudo setcap cap_net_admin+ep $(which iw)` or running as root.
**macOS** needs Location Services permission for the app to see BSSIDs.

### The simulator

`CSW_WIFI_BACKEND=mock` models a client walking a loop past four APs on a
factory floor, with path loss, sticky-client hysteresis and realistic roam
gaps. It exists so the UI, roam detection, diagnosis and exports can be
developed and tested on a machine with no radio — and it is what CI runs
against. The UI labels simulated readings clearly.

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `CSW_WIFI_BACKEND` | `auto` | `auto`, `linux`, `windows`, `macos`, `mock` |
| `CSW_DATABASE_URL` | SQLite in `data/` | Any SQLAlchemy URL |
| `CSW_DATA_DIR` | `./data` | Database and uploaded floor plans |
| `CSW_EXPORT_DIR` | `./exports` | Reserved for generated files |
| `CSW_FRONTEND_DIST` | `frontend/dist` | Built UI to serve |
| `CSW_LOG_LEVEL` | `INFO` | Standard logging levels |
| `CSW_MOCK_SEED` | `1337` | Pins the simulator's noise |

Everything else — thresholds, ping targets, sample interval, the grading scale —
lives in **Settings** and is stored in the database.

---

## Layout

```
backend/app/
├── main.py            FastAPI app; serves the built UI
├── config.py          AppSettings: bands, thresholds, ping targets
├── models.py          SQLAlchemy tables
├── wifi/              One adapter contract, four backends
└── services/
    ├── quality.py     Grading and PASS/WARNING/FAIL
    ├── net_test.py    Ping, gateway discovery, DNS, traceroute
    ├── probe.py       One measurement tick, shared by every screen
    ├── monitor.py     The sampling loop and its WebSocket fan-out
    ├── roaming.py     Roam vs. reconnect vs. network change
    ├── diagnosis.py   The rule engine
    ├── heatmap.py     IDW interpolation
    └── report.py      CSV / Excel / PDF writers
frontend/src/
├── pages/             One file per screen
├── components/        Gauge, heatmap canvas, layout, shared UI
└── api/               Typed client and response shapes
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design decisions and
[`docs/API.md`](docs/API.md) for the endpoint reference.
