"""Signal Monitor: start/stop the sampling loop and read back its series."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import MonitorSession, RoamEvent, Sample
from ..schemas import MonitorSessionOut, MonitorStartRequest, RoamEventOut, SampleOut
from ..services import retention
from ..services.monitor import engine
from ..services.settings_store import load_settings

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/status")
async def status() -> dict:
    return engine.status()


@router.post("/start")
async def start(payload: MonitorStartRequest) -> dict:
    if engine.is_running:
        raise HTTPException(status_code=409, detail="Monitor is already running")
    return await engine.start(**payload.model_dump())


@router.post("/stop")
async def stop() -> dict:
    if not engine.is_running:
        raise HTTPException(status_code=409, detail="Monitor is not running")
    return await engine.stop()


@router.get("/live")
async def live(limit: int = Query(default=300, ge=1, le=600)) -> dict:
    """Buffered samples so a newly opened chart is not blank."""
    return {"samples": engine.recent(limit), "roams": engine.recent_roams(), **engine.status()}


@router.get("/sessions", response_model=list[MonitorSessionOut])
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_session)
):
    return db.scalars(
        select(MonitorSession).order_by(MonitorSession.started_at.desc()).limit(limit)
    ).all()


@router.get("/sessions/{session_id}", response_model=MonitorSessionOut)
async def get_monitor_session(session_id: int, db: Session = Depends(get_session)):
    session = db.get(MonitorSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Monitor session not found")
    return session


@router.delete("/sessions/{session_id}", status_code=204, response_model=None)
async def delete_monitor_session(session_id: int, db: Session = Depends(get_session)) -> None:
    session = db.get(MonitorSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Monitor session not found")
    if engine.status()["session_id"] == session_id:
        raise HTTPException(status_code=409, detail="Stop the monitor before deleting its session")
    db.delete(session)
    db.commit()


@router.get("/samples", response_model=list[SampleOut])
async def list_samples(
    session_id: int | None = None,
    minutes: int | None = Query(default=None, ge=1, le=60 * 24 * 30),
    limit: int = Query(default=1000, ge=1, le=20000),
    db: Session = Depends(get_session),
):
    stmt = select(Sample).order_by(Sample.ts.desc()).limit(limit)
    if session_id is not None:
        stmt = stmt.where(Sample.session_id == session_id)
    if minutes is not None:
        since = datetime.now(UTC) - timedelta(minutes=minutes)
        stmt = stmt.where(Sample.ts >= since)
    rows = db.scalars(stmt).all()
    return list(reversed(rows))  # chronological, which is what a chart wants


@router.get("/summary")
async def summary(
    session_id: int | None = None,
    minutes: int | None = Query(default=60, ge=1, le=60 * 24 * 30),
    db: Session = Depends(get_session),
) -> dict:
    stmt = select(
        func.count(Sample.id),
        func.avg(Sample.rssi),
        func.min(Sample.rssi),
        func.max(Sample.rssi),
        func.avg(func.coalesce(Sample.ping_server_ms, Sample.ping_gateway_ms)),
        func.max(func.coalesce(Sample.ping_server_ms, Sample.ping_gateway_ms)),
        func.avg(Sample.packet_loss_pct),
    )
    if session_id is not None:
        stmt = stmt.where(Sample.session_id == session_id)
    if minutes is not None:
        stmt = stmt.where(Sample.ts >= datetime.now(UTC) - timedelta(minutes=minutes))

    count, rssi_avg, rssi_min, rssi_max, ping_avg, ping_max, loss_avg = db.execute(stmt).one()

    verdict_stmt = select(Sample.verdict, func.count(Sample.id)).group_by(Sample.verdict)
    if session_id is not None:
        verdict_stmt = verdict_stmt.where(Sample.session_id == session_id)
    if minutes is not None:
        verdict_stmt = verdict_stmt.where(
            Sample.ts >= datetime.now(UTC) - timedelta(minutes=minutes)
        )
    verdicts = {v or "UNKNOWN": n for v, n in db.execute(verdict_stmt).all()}

    return {
        "samples": count or 0,
        "rssi": {
            "avg": round(rssi_avg, 1) if rssi_avg is not None else None,
            "min": rssi_min,
            "max": rssi_max,
        },
        "ping_ms": {
            "avg": round(ping_avg, 2) if ping_avg is not None else None,
            "max": round(ping_max, 2) if ping_max is not None else None,
        },
        "packet_loss_pct": round(loss_avg, 2) if loss_avg is not None else None,
        "verdicts": verdicts,
    }


@router.get("/roams", response_model=list[RoamEventOut])
async def list_roams(
    session_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_session),
):
    stmt = select(RoamEvent).order_by(RoamEvent.ts.desc()).limit(limit)
    if session_id is not None:
        stmt = stmt.where(RoamEvent.session_id == session_id)
    return list(reversed(db.scalars(stmt).all()))


@router.delete("/samples")
async def purge_samples(
    older_than_days: int | None = Query(
        default=None, ge=1, le=3650, description="Defaults to the configured retention period"
    ),
    db: Session = Depends(get_session),
) -> dict:
    """Prune telemetry now instead of waiting for the next session to start.

    Saved spot-checks and survey points are never touched - see
    ``services/retention.py`` for why.
    """
    settings = load_settings(db)
    days = older_than_days or settings.monitor.retention_days
    return {"older_than_days": days, "removed": retention.prune(db, days)}


@router.websocket("/ws")
async def monitor_ws(websocket: WebSocket) -> None:
    """Live sample stream.

    Backfills the buffer on connect so a late subscriber sees the same chart as
    everyone else, then forwards each tick as it happens.
    """
    await websocket.accept()
    queue = engine.subscribe()
    try:
        await websocket.send_json(
            {"type": "hello", "status": engine.status(), "backfill": engine.recent(120)}
        )
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=20.0)
            except TimeoutError:
                # Keeps intermediaries from reaping an idle socket.
                await websocket.send_json({"type": "ping"})
                continue
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    except (RuntimeError, ConnectionError):
        pass
    finally:
        engine.unsubscribe(queue)
        with contextlib.suppress(RuntimeError):
            await websocket.close()
