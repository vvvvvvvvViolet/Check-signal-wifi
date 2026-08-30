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
├── 🗺️ Heatmap          Coverage and roaming-redundancy maps on your plan
├── 🧪 Network Test     WiFi → Gateway → LAN → DNS → Internet
├── 🏢 WLAN Controller  Cross-check the client against a Cisco WLC over SNMP
├── 🚨 Diagnosis        Which layer is actually at fault
├── 📊 History          Saved spot-checks, filterable
├── 📄 Report           Excel / CSV / PDF export
└── ⚙️ Settings         Thresholds, ping targets, grading scale
```

---

## Just want to run it?

Download a ready-made build — no Python, no Node.js, nothing to install:

**[Latest builds →](../../actions/workflows/build-desktop.yml)** — open the most
recent run and download the artifact for your platform (Windows, macOS or Linux).
Unzip, double-click, and the app opens in your browser.

`packaging/README-desktop.txt` ships alongside it and covers the first-run
security prompts, where survey data is stored, and what to do when the window
closes too fast to read.

Everything below is for running from source or developing.

---

## Quick start

Needs Python 3.11+ and Node.js 20+ ([nodejs.org](https://nodejs.org) - if
`npm` is not recognized, Node isn't installed yet, or you need to reopen your
terminal after installing it).

**macOS / Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cd frontend && npm install && npm run build && cd ..

uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

**Windows (Command Prompt):**

```bat
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r backend\requirements.txt

cd frontend
npm install
npm run build
cd ..

uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

(PowerShell: use `.venv\Scripts\Activate.ps1` instead of the `activate.bat`
line.) `source` is a bash/macOS command and has no Windows equivalent - copying
the macOS/Linux block into Command Prompt is the most common first error.

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
cd backend && pytest          # 175 tests
cd backend && ruff check .
cd frontend && npm run lint   # tsc --noEmit
```

CI runs all of the above on every push, plus an end-to-end smoke test that
starts the server, seeds a survey and checks every export format
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

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

## WLAN Controller (optional)

Off by default — this is the one screen that reaches out to enterprise
infrastructure over the network rather than reading only the machine the app
runs on, so it needs a deliberate opt-in.

Point it at a Cisco AireOS WLC (tested against WLC 3504) over SNMP and it will:

* confirm the controller answers at all (standard MIB-II — no vendor guesswork)
* list every AP it manages, with each radio's channel, client count and
  utilisation
* list every client the controller currently holds, across every AP
* **cross-check this machine**: does the controller's client table agree that
  this laptop is on the AP its own radio reports? A mismatch means the client
  is holding a stale association the AP has already dropped — invisible to
  either side alone, and folded into Diagnosis as `CONTROLLER_CLIENT_MISMATCH`
  when it happens.

Configure the WLC's host and SNMP community string (v2c) or v3 credentials
under **WLAN Controller** in the app, and enable monitoring.

**A candid limit:** the AP/client table layout (Cisco's
`AIRESPACE-WIRELESS-MIB`) was implemented from public documentation, not
verified against a live WLC 3504 — this project has never had one to test
against. If the AP or client list comes back empty on a WLC that genuinely has
either, use the **raw OID walk** on the same screen: point it at
`1.3.6.1.4.1.14179.2.2.1.1` (APs) or `1.3.6.1.4.1.14179.2.1.4.1` (clients) and
compare the column numbers against the WLC's own CLI (`show ap summary`) or
web UI. That is exactly the tool that resolved the Windows locale bug earlier
in this project, aimed at a new kind of "translated labels."

**Security note:** SNMPv2c's community string travels in cleartext on the
wire. Safe on a dedicated management VLAN; not safe across an open WiFi survey
network. Use SNMPv3 if your network team can provide it.

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

### Surveying a floor

**Point mode** takes a reading where you click. **Walk mode** is the fast way:
click where you start, walk an aisle at a steady pace, click where you finish.
Readings are taken continuously and placed along the line by *when* they were
taken — so keep the route straight and the pace even, because that assumption is
what positions them.

Point mode also scans for other access points (this is skippable, since it costs
a few seconds per point). That scan is what makes the **Redundancy** map
possible.

### Two maps, two questions

| Map | Answers |
|---|---|
| **Coverage** | Is there signal here? |
| **Redundancy** | Is there anywhere to *roam* to here? |

They are not the same question, and the difference is where surveys usually go
wrong. A spot can read a comfortable -50 dBm and still be where a forklift
scanner drops its session, because the only AP it can hear is the one it is
walking away from. Red on the redundancy map means no alternative AP is usable —
a client that moves through it disconnects rather than hands over.

Filter either map by **access point** (to see where one AP actually reaches,
which is what you need to set its transmit power) or by **band** (2.4 and 5 GHz
cover very differently; averaging them hides the problem you are surveying for).

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
- **A survey point captured without a scan is drawn grey on the redundancy map,
  not red.** "Not measured" and "no fallback AP" are different findings.
- **Retention deletes only telemetry.** Saved spot-checks and survey points are
  a person's deliberate work and are never pruned.

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

Adding a column to the schema is handled on startup for SQLite, so an existing
database keeps working after an upgrade. Anything more than adding columns will
need a real migration tool.

Everything else — thresholds, ping targets, sample interval, the grading scale —
lives in **Settings** and is stored in the database.

---

## Layout

```
launcher.py            Desktop entry point (port choice, browser, banner)
packaging/             PyInstaller spec and the end-user readme
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
    ├── heatmap.py     IDW interpolation and redundancy counting
    ├── retention.py   Pruning telemetry (and nothing else)
    ├── snmp.py        Generic, timeout-safe SNMP GET/WALK
    ├── controller.py  Cisco WLC AP/client tables over SNMP
    └── report.py      CSV / Excel / PDF writers
frontend/src/
├── pages/             One file per screen
├── components/        Gauge, heatmap canvas, layout, shared UI
└── api/               Typed client and response shapes
```

### Building the desktop app yourself

```bash
pip install -r backend/requirements-dev.txt   # includes PyInstaller
npm --prefix frontend ci
npm --prefix frontend run build               # the spec refuses to build without this
pyinstaller packaging/check-signal-wifi.spec --noconfirm
```

The executable lands in `dist/`. Build on the platform you are targeting —
PyInstaller does not cross-compile, which is why CI builds all three.

When packaged, survey data moves out of the repo to the per-user application
directory (`%LOCALAPPDATA%\CheckSignalWiFi` on Windows, `~/Library/Application
Support/CheckSignalWiFi` on macOS, `~/.local/share/CheckSignalWiFi` on Linux),
because the executable may sit somewhere the user cannot write.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design decisions and
[`docs/API.md`](docs/API.md) for the endpoint reference.
