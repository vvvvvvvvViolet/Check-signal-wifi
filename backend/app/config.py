"""Runtime configuration and user-tunable thresholds.

Two different things live here and they are deliberately kept apart:

* ``SignalBands``  - the fixed grading scale used by the gauge / heatmap colours
  (Excellent / Good / Fair / Poor).  Tuning these changes what a colour *means*.
* ``Thresholds``   - the alerting limits used by diagnosis and PASS/WARN/FAIL
  verdicts.  Tuning these changes when the app *complains*.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field

APP_DIR_NAME = "CheckSignalWiFi"

# PyInstaller sets ``frozen`` and unpacks the bundle into a temp directory that
# is wiped when the process exits. Read-only assets live there; anything the app
# writes must not, or a survey would vanish the moment the window is closed.
IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BUNDLE_DIR = BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _default_data_dir() -> Path:
    """Where surveys live.

    Running from a checkout, the repo's own ``data/`` is the least surprising
    place. Running as a packaged app, the executable may sit somewhere the user
    cannot write (Program Files, a read-only share, a USB stick), so data goes
    to the per-user application directory the platform reserves for exactly this.
    """
    if not IS_FROZEN:
        return BASE_DIR / "data"
    if sys.platform.startswith("win"):
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / APP_DIR_NAME


DATA_DIR = Path(os.environ.get("CSW_DATA_DIR") or _default_data_dir())
FLOORPLAN_DIR = DATA_DIR / "floorplans"
EXPORT_DIR = Path(os.environ.get("CSW_EXPORT_DIR") or (DATA_DIR / "exports"))
DB_PATH = DATA_DIR / "check_signal_wifi.db"

# The built UI ships inside the bundle when frozen, and sits in the frontend
# workspace when running from a checkout.
FRONTEND_DIST = Path(
    os.environ.get("CSW_FRONTEND_DIST")
    or (BUNDLE_DIR / "frontend_dist" if IS_FROZEN else BASE_DIR / "frontend" / "dist")
)

for _d in (DATA_DIR, FLOORPLAN_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("CSW_DATABASE_URL", f"sqlite:///{DB_PATH}")

# Force a specific Wi-Fi backend: auto | linux | windows | macos | mock
WIFI_BACKEND = os.environ.get("CSW_WIFI_BACKEND", "auto").lower()


class SignalBands(BaseModel):
    """RSSI cut-offs for the four quality grades, in dBm.

    A sample is graded by the first band whose floor it clears:
    ``rssi >= excellent`` -> Excellent, ``>= good`` -> Good, ``>= fair`` -> Fair,
    anything lower -> Poor.
    """

    excellent: int = Field(default=-55, le=0)
    good: int = Field(default=-65, le=0)
    fair: int = Field(default=-72, le=0)


class Thresholds(BaseModel):
    """Alerting limits. Warning is raised first, critical supersedes it."""

    rssi_warning: int = Field(default=-67, le=0)
    rssi_critical: int = Field(default=-75, le=0)
    ping_warning_ms: float = Field(default=50.0, ge=0)
    ping_critical_ms: float = Field(default=150.0, ge=0)
    loss_warning_pct: float = Field(default=2.0, ge=0, le=100)
    loss_critical_pct: float = Field(default=5.0, ge=0, le=100)
    jitter_warning_ms: float = Field(default=30.0, ge=0)
    # A hand-off longer than this drops barcode-scanner and VoIP sessions.
    roam_gap_warning_ms: float = Field(default=500.0, ge=0)


class PingTargets(BaseModel):
    """Where the probes are sent.

    ``gateway`` accepts the literal string ``auto`` to mean "discover the
    default gateway at probe time", which is what a field technician wants
    when they roam between sites.
    """

    gateway: str = "auto"
    server: str = "8.8.8.8"
    dns: str = "1.1.1.1"
    dns_hostname: str = "www.google.com"


class MonitorConfig(BaseModel):
    interval_sec: float = Field(default=2.0, ge=0.5, le=300)
    ping_count: int = Field(default=4, ge=1, le=20)
    ping_timeout_sec: float = Field(default=1.0, ge=0.2, le=10)
    retention_days: int = Field(default=90, ge=1)
    # Capturing a survey point makes someone stand still while it runs, so it
    # uses fewer probes than continuous monitoring, which nobody waits on.
    survey_ping_count: int = Field(default=2, ge=1, le=20)


class ControllerConfig(BaseModel):
    """How to reach the site's WLAN controller over SNMP.

    Optional and off by default: most sites do not have one, and reading it
    means the app reaches out to enterprise infrastructure rather than only
    the machine it runs on - a different trust boundary from everything else
    here, so it stays opt-in.
    """

    enabled: bool = False
    host: str = ""
    port: int = Field(default=161, ge=1, le=65535)
    version: str = Field(default="v2c", pattern="^(v2c|v3)$")
    # SNMPv2c's community string travels in cleartext on the wire - acceptable
    # on a dedicated management VLAN, not across an open WiFi survey network.
    community: str = ""
    v3_user: str = ""
    v3_auth_password: str = ""
    v3_priv_password: str = ""
    timeout_sec: float = Field(default=4.0, ge=0.5, le=30)


class AppSettings(BaseModel):
    """The whole user-editable configuration, persisted as one JSON blob."""

    bands: SignalBands = Field(default_factory=SignalBands)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    ping: PingTargets = Field(default_factory=PingTargets)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    controller: ControllerConfig = Field(default_factory=ControllerConfig)
    site_name: str = "Default Site"


DEFAULT_SETTINGS = AppSettings()
