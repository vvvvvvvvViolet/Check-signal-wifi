"""Dashboard: the one screen that must answer "is the WiFi OK right now?"."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Sample
from ..services import diagnosis, probe
from ..services.monitor import engine
from ..services.settings_store import load_settings

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
async def get_dashboard(db: Session = Depends(get_session)) -> dict:
    settings = load_settings(db)
    snapshot = await probe.take_snapshot(settings)

    link = snapshot["link"]
    summary = snapshot["summary"]
    report = diagnosis.diagnose(
        settings,
        rssi=link.get("rssi"),
        ping_ms=summary.get("ping_ms"),
        loss_pct=summary.get("packet_loss_pct"),
        jitter_ms=summary.get("jitter_ms"),
        channel=link.get("channel"),
        band=link.get("band"),
        connected=bool(link.get("connected")),
    )

    # A short trend line so the dashboard shows movement, not just a number.
    recent = db.scalars(
        select(Sample).order_by(Sample.ts.desc()).limit(60)
    ).all()
    trend = [
        {"ts": s.ts.isoformat(), "rssi": s.rssi, "ping_ms": s.ping_server_ms or s.ping_gateway_ms}
        for s in reversed(recent)
    ]

    gateway = snapshot["ping"].get("gateway", {})
    server = snapshot["ping"].get("server", {})
    return {
        **snapshot,
        "status_text": _status_text(
            summary["verdict"], report["headline"], summary.get("incomplete", False)
        ),
        "diagnosis": {"severity": report["severity"], "headline": report["headline"]},
        "internet_ok": bool(server.get("reachable")),
        "gateway_ok": bool(gateway.get("reachable")),
        "trend": trend,
        "monitor": engine.status(),
        "thresholds": settings.thresholds.model_dump(),
        "bands": settings.bands.model_dump(),
    }


def _status_text(verdict: str, headline: str, incomplete: bool = False) -> str:
    if incomplete:
        return "? Reachability not measured"
    if verdict == "PASS":
        return "✓ Network Healthy"
    return f"⚠ {headline}"
