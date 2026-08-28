"""Auto Diagnosis: run the rule engine over a live or supplied measurement."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import RoamEvent
from ..services import diagnosis as diagnosis_service
from ..services import probe
from ..services.settings_store import load_settings
from ..wifi import get_adapter

router = APIRouter(prefix="/api/diagnosis", tags=["diagnosis"])


class ManualDiagnosisRequest(BaseModel):
    """Diagnose numbers captured elsewhere, e.g. from a report or a phone."""

    rssi: int | None = Field(default=None, le=0)
    ping_ms: float | None = Field(default=None, ge=0)
    packet_loss_pct: float | None = Field(default=None, ge=0, le=100)
    jitter_ms: float | None = Field(default=None, ge=0)
    channel: int | None = None
    band: str | None = None
    connected: bool = True


@router.get("")
async def run_diagnosis(
    include_scan: bool = Query(default=True, description="Also check for channel contention"),
    window_minutes: int = Query(default=15, ge=1, le=1440),
    db: Session = Depends(get_session),
) -> dict:
    settings = load_settings(db)
    snapshot = await probe.take_snapshot(settings)
    link = snapshot["link"]
    summary = snapshot["summary"]

    scan: list[dict] = []
    if include_scan:
        networks = await asyncio.to_thread(get_adapter().scan)
        scan = [n.as_dict() for n in networks]

    since = datetime.now(UTC) - timedelta(minutes=window_minutes)
    # The events themselves, not just the count: how *late* each hand-off was is
    # what reveals a sticky client, and a count cannot show that.
    recent_roams = db.scalars(
        select(RoamEvent).where(RoamEvent.ts >= since).order_by(RoamEvent.ts)
    ).all()
    roams = [
        {
            "from_bssid": r.from_bssid,
            "to_bssid": r.to_bssid,
            "from_rssi": r.from_rssi,
            "to_rssi": r.to_rssi,
            "gap_ms": r.gap_ms,
            "kind": "roam",
        }
        for r in recent_roams
    ]

    report = diagnosis_service.diagnose(
        settings,
        rssi=link.get("rssi"),
        ping_ms=summary.get("ping_ms"),
        loss_pct=summary.get("packet_loss_pct"),
        jitter_ms=summary.get("jitter_ms"),
        channel=link.get("channel"),
        band=link.get("band"),
        connected=bool(link.get("connected")),
        scan=scan,
        roam_count=len(roams),
        window_minutes=window_minutes,
        roams=roams,
    )
    return {"ts": snapshot["ts"], "link": link, "summary": summary, **report}


@router.post("")
async def diagnose_manual(
    payload: ManualDiagnosisRequest, db: Session = Depends(get_session)
) -> dict:
    settings = load_settings(db)
    return diagnosis_service.diagnose(
        settings,
        rssi=payload.rssi,
        ping_ms=payload.ping_ms,
        loss_pct=payload.packet_loss_pct,
        jitter_ms=payload.jitter_ms,
        channel=payload.channel,
        band=payload.band,
        connected=payload.connected,
    )
