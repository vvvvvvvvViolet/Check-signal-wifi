"""Persisted entities.

The schema is intentionally flat: a site survey tool is written far more often
than it is queried, and every screen in the UI is a filter over one of these
tables.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class SettingRecord(Base):
    """Single-row key/value store for :class:`app.config.AppSettings`."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class MonitorSession(Base, TimestampMixin):
    """One continuous-monitoring run (Signal Monitor / Roaming Test)."""

    __tablename__ = "monitor_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    area: Mapped[str | None] = mapped_column(String(128))
    device: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interval_sec: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)

    samples: Mapped[list[Sample]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )
    roam_events: Mapped[list[RoamEvent]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_running(self) -> bool:
        return self.ended_at is None


class Sample(Base):
    """One measurement tick: radio state plus the reachability probes."""

    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("monitor_sessions.id", ondelete="CASCADE"), index=True
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    ssid: Mapped[str | None] = mapped_column(String(64), index=True)
    bssid: Mapped[str | None] = mapped_column(String(32), index=True)
    channel: Mapped[int | None] = mapped_column(Integer)
    band: Mapped[str | None] = mapped_column(String(8))
    frequency_mhz: Mapped[int | None] = mapped_column(Integer)
    rssi: Mapped[int | None] = mapped_column(Integer, index=True)
    quality_pct: Mapped[int | None] = mapped_column(Integer)
    noise_dbm: Mapped[int | None] = mapped_column(Integer)
    tx_rate_mbps: Mapped[float | None] = mapped_column(Float)
    rx_rate_mbps: Mapped[float | None] = mapped_column(Float)

    ping_gateway_ms: Mapped[float | None] = mapped_column(Float)
    ping_server_ms: Mapped[float | None] = mapped_column(Float)
    ping_dns_ms: Mapped[float | None] = mapped_column(Float)
    jitter_ms: Mapped[float | None] = mapped_column(Float)
    packet_loss_pct: Mapped[float | None] = mapped_column(Float)

    grade: Mapped[str | None] = mapped_column(String(16))
    verdict: Mapped[str | None] = mapped_column(String(16), index=True)

    session: Mapped[MonitorSession | None] = relationship(back_populates="samples")


class RoamEvent(Base):
    """A BSSID transition observed while monitoring."""

    __tablename__ = "roam_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("monitor_sessions.id", ondelete="CASCADE"), index=True
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    ssid: Mapped[str | None] = mapped_column(String(64))
    from_bssid: Mapped[str | None] = mapped_column(String(32))
    to_bssid: Mapped[str | None] = mapped_column(String(32))
    from_rssi: Mapped[int | None] = mapped_column(Integer)
    to_rssi: Mapped[int | None] = mapped_column(Integer)
    from_channel: Mapped[int | None] = mapped_column(Integer)
    to_channel: Mapped[int | None] = mapped_column(Integer)
    gap_ms: Mapped[float | None] = mapped_column(Float)

    session: Mapped[MonitorSession | None] = relationship(back_populates="roam_events")


class FloorPlan(Base, TimestampMixin):
    """An uploaded building/factory plan that survey points are pinned onto."""

    __tablename__ = "floor_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    location: Mapped[str | None] = mapped_column(String(128), index=True)
    image_filename: Mapped[str] = mapped_column(String(256), nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    # Optional real-world scale so distances can be reported in metres.
    meters_per_px: Mapped[float | None] = mapped_column(Float)

    points: Mapped[list[SurveyPoint]] = relationship(
        back_populates="floor_plan", cascade="all, delete-orphan", passive_deletes=True
    )
    access_points: Mapped[list[AccessPointMarker]] = relationship(
        back_populates="floor_plan", cascade="all, delete-orphan", passive_deletes=True
    )


class SurveyPoint(Base):
    """A measurement captured at a pixel coordinate on a floor plan."""

    __tablename__ = "survey_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    floor_plan_id: Mapped[int] = mapped_column(
        ForeignKey("floor_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    label: Mapped[str | None] = mapped_column(String(128))
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)

    ssid: Mapped[str | None] = mapped_column(String(64), index=True)
    bssid: Mapped[str | None] = mapped_column(String(32), index=True)
    channel: Mapped[int | None] = mapped_column(Integer)
    band: Mapped[str | None] = mapped_column(String(8))
    rssi: Mapped[int | None] = mapped_column(Integer)
    ping_ms: Mapped[float | None] = mapped_column(Float)
    packet_loss_pct: Mapped[float | None] = mapped_column(Float)
    grade: Mapped[str | None] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)

    # Every other BSSID audible here, as [{bssid, ssid, rssi, channel, band}].
    # This is what makes a redundancy map possible: coverage answers "is there
    # signal", redundancy answers "is there anywhere to roam to", and a client
    # that can hear only one AP is a client that will drop when it moves.
    neighbors: Mapped[list | None] = mapped_column(JSON)

    floor_plan: Mapped[FloorPlan] = relationship(back_populates="points")


class AccessPointMarker(Base):
    """Where an AP physically sits on the plan - drawn on the heatmap."""

    __tablename__ = "ap_markers"
    __table_args__ = (UniqueConstraint("floor_plan_id", "name", name="uq_ap_plan_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    floor_plan_id: Mapped[int] = mapped_column(
        ForeignKey("floor_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    bssid: Mapped[str | None] = mapped_column(String(32))
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)

    floor_plan: Mapped[FloorPlan] = relationship(back_populates="access_points")


class TestRecord(Base):
    """A saved spot-check for the History screen."""

    __tablename__ = "test_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    area: Mapped[str | None] = mapped_column(String(128), index=True)
    device: Mapped[str | None] = mapped_column(String(128), index=True)
    ssid: Mapped[str | None] = mapped_column(String(64), index=True)
    bssid: Mapped[str | None] = mapped_column(String(32), index=True)
    channel: Mapped[int | None] = mapped_column(Integer)
    band: Mapped[str | None] = mapped_column(String(8))
    rssi: Mapped[int | None] = mapped_column(Integer)
    ping_ms: Mapped[float | None] = mapped_column(Float)
    jitter_ms: Mapped[float | None] = mapped_column(Float)
    packet_loss_pct: Mapped[float | None] = mapped_column(Float)
    grade: Mapped[str | None] = mapped_column(String(16))
    result: Mapped[str | None] = mapped_column(String(16), index=True)
    findings: Mapped[list | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
