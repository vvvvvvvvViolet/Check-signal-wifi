"""Test History: saved spot-checks with the filters the field team needs."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, distinct, select
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import TestRecord
from ..schemas import HistoryPage, TestRecordCreate, TestRecordOut
from ..services import diagnosis as diagnosis_service
from ..services import probe
from ..services.quality import grade_rssi
from ..services.settings_store import load_settings

router = APIRouter(prefix="/api/history", tags=["history"])


def apply_filters(
    stmt: Select,
    *,
    date_from: date | None,
    date_to: date | None,
    area: str | None,
    ssid: str | None,
    bssid: str | None,
    result: str | None,
    device: str | None,
) -> Select:
    """Shared by the list endpoint and the exporter so both filter identically."""
    if date_from:
        stmt = stmt.where(TestRecord.ts >= datetime.combine(date_from, time.min, UTC))
    if date_to:
        # Inclusive of the whole end day - a technician filtering "today" expects today.
        stmt = stmt.where(TestRecord.ts <= datetime.combine(date_to, time.max, UTC))
    if area:
        stmt = stmt.where(TestRecord.area == area)
    if ssid:
        stmt = stmt.where(TestRecord.ssid == ssid)
    if bssid:
        stmt = stmt.where(TestRecord.bssid == bssid)
    if result:
        stmt = stmt.where(TestRecord.result == result.upper())
    if device:
        stmt = stmt.where(TestRecord.device == device)
    return stmt


@router.post("", response_model=TestRecordOut, status_code=201)
async def create_record(payload: TestRecordCreate, db: Session = Depends(get_session)):
    """Record a spot-check, measuring live unless values were supplied."""
    settings = load_settings(db)
    data = payload.model_dump(exclude={"measure"})
    findings: list[dict] = []

    if payload.measure:
        snapshot = await probe.take_snapshot(settings)
        link = snapshot["link"]
        summary = snapshot["summary"]
        data.update(
            ssid=link.get("ssid"),
            bssid=link.get("bssid"),
            channel=link.get("channel"),
            band=link.get("band"),
            rssi=link.get("rssi"),
            ping_ms=summary.get("ping_ms"),
            jitter_ms=summary.get("jitter_ms"),
            packet_loss_pct=summary.get("packet_loss_pct"),
        )
        verdict = summary["verdict"]
        connected = bool(link.get("connected"))
    else:
        from ..services import quality

        assessment = quality.evaluate(
            settings,
            rssi=data.get("rssi"),
            ping_ms=data.get("ping_ms"),
            loss_pct=data.get("packet_loss_pct"),
            jitter_ms=data.get("jitter_ms"),
        )
        verdict = assessment["verdict"]
        connected = data.get("rssi") is not None

    report = diagnosis_service.diagnose(
        settings,
        rssi=data.get("rssi"),
        ping_ms=data.get("ping_ms"),
        loss_pct=data.get("packet_loss_pct"),
        jitter_ms=data.get("jitter_ms"),
        channel=data.get("channel"),
        band=data.get("band"),
        connected=connected,
    )
    findings = report["findings"]

    record = TestRecord(
        **data,
        grade=grade_rssi(data.get("rssi"), settings.bands),
        result=verdict,
        findings=findings,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("", response_model=HistoryPage)
async def list_records(
    date_from: date | None = None,
    date_to: date | None = None,
    area: str | None = None,
    ssid: str | None = None,
    bssid: str | None = None,
    result: str | None = Query(default=None, pattern="^(?i)(PASS|WARNING|FAIL)$"),
    device: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
):
    filters = {
        "date_from": date_from,
        "date_to": date_to,
        "area": area,
        "ssid": ssid,
        "bssid": bssid,
        "result": result,
        "device": device,
    }
    total = db.scalar(apply_filters(select(sa_func.count(TestRecord.id)), **filters)) or 0
    rows = db.scalars(
        apply_filters(select(TestRecord), **filters)
        .order_by(TestRecord.ts.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return HistoryPage(
        items=[TestRecordOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/facets")
async def facets(db: Session = Depends(get_session)) -> dict:
    """Distinct values so the UI can offer real filter options, not free text."""

    def values(column) -> list[str]:
        return [v for v in db.scalars(select(distinct(column)).order_by(column)).all() if v]

    return {
        "areas": values(TestRecord.area),
        "ssids": values(TestRecord.ssid),
        "bssids": values(TestRecord.bssid),
        "devices": values(TestRecord.device),
        "results": ["PASS", "WARNING", "FAIL"],
    }


@router.get("/stats")
async def stats(db: Session = Depends(get_session)) -> dict:
    counts = dict(
        db.execute(
            select(TestRecord.result, sa_func.count(TestRecord.id)).group_by(TestRecord.result)
        ).all()
    )
    by_area = [
        {
            "area": area or "(unassigned)",
            "count": count,
            "avg_rssi": round(avg_rssi, 1) if avg_rssi is not None else None,
            "avg_ping_ms": round(avg_ping, 2) if avg_ping is not None else None,
        }
        for area, count, avg_rssi, avg_ping in db.execute(
            select(
                TestRecord.area,
                sa_func.count(TestRecord.id),
                sa_func.avg(TestRecord.rssi),
                sa_func.avg(TestRecord.ping_ms),
            ).group_by(TestRecord.area)
        ).all()
    ]
    return {
        "total": sum(counts.values()),
        "by_result": {k or "UNKNOWN": v for k, v in counts.items()},
        "by_area": sorted(by_area, key=lambda row: row["count"], reverse=True),
    }


@router.get("/{record_id}", response_model=TestRecordOut)
async def get_record(record_id: int, db: Session = Depends(get_session)):
    record = db.get(TestRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Test record not found")
    return record


@router.delete("/{record_id}", status_code=204, response_model=None)
async def delete_record(record_id: int, db: Session = Depends(get_session)) -> None:
    record = db.get(TestRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Test record not found")
    db.delete(record)
    db.commit()
