"""Runtime configuration and user-tunable thresholds.

Two different things live here and they are deliberately kept apart:

* ``SignalBands``  - the fixed grading scale used by the gauge / heatmap colours
  (Excellent / Good / Fair / Poor).  Tuning these changes what a colour *means*.
* ``Thresholds``   - the alerting limits used by diagnosis and PASS/WARN/FAIL
  verdicts.  Tuning these changes when the app *complains*.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.environ.get("CSW_DATA_DIR", BASE_DIR / "data"))
FLOORPLAN_DIR = DATA_DIR / "floorplans"
EXPORT_DIR = Path(os.environ.get("CSW_EXPORT_DIR", BASE_DIR / "exports"))
DB_PATH = DATA_DIR / "check_signal_wifi.db"

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


class AppSettings(BaseModel):
    """The whole user-editable configuration, persisted as one JSON blob."""

    bands: SignalBands = Field(default_factory=SignalBands)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    ping: PingTargets = Field(default_factory=PingTargets)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    site_name: str = "Default Site"


DEFAULT_SETTINGS = AppSettings()
