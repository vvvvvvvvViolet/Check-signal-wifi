"""Request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .config import AppSettings


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------- monitoring
class MonitorStartRequest(BaseModel):
    name: str = "Monitor session"
    area: str | None = None
    device: str | None = None
    note: str | None = None
    interval_sec: float | None = Field(default=None, ge=0.5, le=300)


class SampleOut(ORMModel):
    id: int
    session_id: int | None
    ts: datetime
    ssid: str | None
    bssid: str | None
    channel: int | None
    band: str | None
    rssi: int | None
    quality_pct: int | None
    tx_rate_mbps: float | None
    ping_gateway_ms: float | None
    ping_server_ms: float | None
    ping_dns_ms: float | None
    jitter_ms: float | None
    packet_loss_pct: float | None
    grade: str | None
    verdict: str | None


class MonitorSessionOut(ORMModel):
    id: int
    name: str
    area: str | None
    device: str | None
    note: str | None
    started_at: datetime
    ended_at: datetime | None
    interval_sec: float


class RoamEventOut(ORMModel):
    id: int
    session_id: int | None
    ts: datetime
    ssid: str | None
    from_bssid: str | None
    to_bssid: str | None
    from_rssi: int | None
    to_rssi: int | None
    from_channel: int | None
    to_channel: int | None
    gap_ms: float | None


# --------------------------------------------------------------- heatmap
class FloorPlanCreate(BaseModel):
    name: str
    location: str | None = None
    meters_per_px: float | None = Field(default=None, gt=0)


class FloorPlanUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    meters_per_px: float | None = Field(default=None, gt=0)


class FloorPlanOut(ORMModel):
    id: int
    name: str
    location: str | None
    image_filename: str
    width_px: int
    height_px: int
    meters_per_px: float | None
    created_at: datetime


class SurveyPointCreate(BaseModel):
    """Capture a point.

    Leaving the radio fields unset makes the server measure live at this
    coordinate, which is the normal walk-the-floor workflow. Supplying them
    explicitly is for importing a survey taken elsewhere.
    """

    x: float = Field(ge=0)
    y: float = Field(ge=0)
    label: str | None = None
    note: str | None = None
    measure: bool = True
    ssid: str | None = None
    bssid: str | None = None
    channel: int | None = None
    band: str | None = None
    rssi: int | None = None
    ping_ms: float | None = None
    packet_loss_pct: float | None = None


class SurveyPointOut(ORMModel):
    id: int
    floor_plan_id: int
    ts: datetime
    label: str | None
    x: float
    y: float
    ssid: str | None
    bssid: str | None
    channel: int | None
    band: str | None
    rssi: int | None
    ping_ms: float | None
    packet_loss_pct: float | None
    grade: str | None
    note: str | None


class AccessPointMarkerCreate(BaseModel):
    name: str
    bssid: str | None = None
    x: float = Field(ge=0)
    y: float = Field(ge=0)


class AccessPointMarkerOut(ORMModel):
    id: int
    floor_plan_id: int
    name: str
    bssid: str | None
    x: float
    y: float


# --------------------------------------------------------------- history
class TestRecordCreate(BaseModel):
    area: str | None = None
    device: str | None = None
    note: str | None = None
    measure: bool = True
    ssid: str | None = None
    bssid: str | None = None
    channel: int | None = None
    band: str | None = None
    rssi: int | None = None
    ping_ms: float | None = None
    jitter_ms: float | None = None
    packet_loss_pct: float | None = None


class TestRecordOut(ORMModel):
    id: int
    ts: datetime
    area: str | None
    device: str | None
    ssid: str | None
    bssid: str | None
    channel: int | None
    band: str | None
    rssi: int | None
    ping_ms: float | None
    jitter_ms: float | None
    packet_loss_pct: float | None
    grade: str | None
    result: str | None
    note: str | None


class HistoryPage(BaseModel):
    items: list[TestRecordOut]
    total: int
    limit: int
    offset: int


# -------------------------------------------------------------- settings
class SettingsOut(BaseModel):
    settings: AppSettings
    stored: bool
    wifi_backend: str
