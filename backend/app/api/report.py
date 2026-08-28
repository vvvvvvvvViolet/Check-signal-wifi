"""Export: history, monitor sessions and heatmaps as CSV / Excel / PDF."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import FloorPlan, MonitorSession, Sample, SurveyPoint, TestRecord
from ..services import report as report_service
from ..services.heatmap import Point, summarise
from ..services.settings_store import load_settings
from .history import apply_filters

router = APIRouter(prefix="/api/report", tags=["report"])

MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}

HISTORY_HEADERS = [
    "Date",
    "Time",
    "Area",
    "Device",
    "SSID",
    "BSSID",
    "Channel",
    "Band",
    "RSSI (dBm)",
    "Ping (ms)",
    "Jitter (ms)",
    "Loss (%)",
    "Grade",
    "Result",
    "Note",
]

SAMPLE_HEADERS = [
    "Timestamp",
    "SSID",
    "BSSID",
    "Channel",
    "Band",
    "RSSI (dBm)",
    "Ping Gateway (ms)",
    "Ping Server (ms)",
    "Loss (%)",
    "Grade",
    "Result",
]

POINT_HEADERS = [
    "Timestamp",
    "Label",
    "X",
    "Y",
    "SSID",
    "BSSID",
    "Channel",
    "Band",
    "RSSI (dBm)",
    "Ping (ms)",
    "Loss (%)",
    "Grade",
]


def _local(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _render(
    fmt: str,
    headers: list[str],
    rows: list[list],
    *,
    title: str,
    subtitle: str | None = None,
    summary: dict | None = None,
    findings: list[dict] | None = None,
) -> Response:
    fmt = fmt.lower()
    if fmt not in MEDIA:
        raise HTTPException(status_code=400, detail="format must be csv, xlsx or pdf")

    if fmt == "csv":
        body = report_service.to_csv(headers, rows)
    elif fmt == "xlsx":
        body = report_service.to_xlsx(headers, rows, title=title, summary=summary)
    else:
        body = report_service.to_pdf(
            headers, rows, title=title, subtitle=subtitle, summary=summary, findings=findings
        )

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in title.lower())[:48].strip("-")
    filename = f"{slug or 'report'}-{stamp}.{fmt}"
    return Response(
        content=body,
        media_type=MEDIA[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/history")
async def export_history(
    format: str = Query(default="xlsx", pattern="^(?i)(csv|xlsx|pdf)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    area: str | None = None,
    ssid: str | None = None,
    bssid: str | None = None,
    result: str | None = Query(default=None, pattern="^(?i)(PASS|WARNING|FAIL)$"),
    device: str | None = None,
    limit: int = Query(default=5000, ge=1, le=50000),
    db: Session = Depends(get_session),
) -> Response:
    """Export the History table under exactly the filters the UI is showing."""
    stmt = apply_filters(
        select(TestRecord),
        date_from=date_from,
        date_to=date_to,
        area=area,
        ssid=ssid,
        bssid=bssid,
        result=result,
        device=device,
    )
    records = db.scalars(stmt.order_by(TestRecord.ts.desc()).limit(limit)).all()

    rows = [
        [
            _local(r.ts).strftime("%Y-%m-%d"),
            _local(r.ts).strftime("%H:%M:%S"),
            r.area,
            r.device,
            r.ssid,
            r.bssid,
            r.channel,
            r.band,
            r.rssi,
            r.ping_ms,
            r.jitter_ms,
            r.packet_loss_pct,
            r.grade,
            r.result,
            r.note,
        ]
        for r in records
    ]

    verdicts = [r.result for r in records if r.result]
    rssis = [r.rssi for r in records if r.rssi is not None]
    settings = load_settings(db)
    summary = {
        "Site": settings.site_name,
        "Records": len(records),
        "PASS": verdicts.count("PASS"),
        "WARNING": verdicts.count("WARNING"),
        "FAIL": verdicts.count("FAIL"),
        "Average RSSI (dBm)": round(sum(rssis) / len(rssis), 1) if rssis else None,
        "Date range": f"{date_from or 'all'} .. {date_to or 'all'}",
        "Area filter": area or "all",
        "SSID filter": ssid or "all",
    }

    # Roll the distinct findings up so the PDF carries the "why", not just rows.
    findings: list[dict] = []
    seen: set[str] = set()
    for record in records:
        for finding in record.findings or []:
            code = finding.get("code")
            if code and code not in seen and code != "HEALTHY":
                seen.add(code)
                findings.append(finding)

    return _render(
        format,
        HISTORY_HEADERS,
        rows,
        title="WiFi Test History",
        subtitle=f"{settings.site_name} - {len(records)} records",
        summary=summary,
        findings=findings[:12],
    )


@router.get("/session/{session_id}")
async def export_session(
    session_id: int,
    format: str = Query(default="xlsx", pattern="^(?i)(csv|xlsx|pdf)$"),
    limit: int = Query(default=20000, ge=1, le=100000),
    db: Session = Depends(get_session),
) -> Response:
    """Export every sample from one continuous-monitoring run."""
    session = db.get(MonitorSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Monitor session not found")

    samples = db.scalars(
        select(Sample).where(Sample.session_id == session_id).order_by(Sample.ts).limit(limit)
    ).all()

    rows = [
        [
            _local(s.ts).strftime("%Y-%m-%d %H:%M:%S"),
            s.ssid,
            s.bssid,
            s.channel,
            s.band,
            s.rssi,
            s.ping_gateway_ms,
            s.ping_server_ms,
            s.packet_loss_pct,
            s.grade,
            s.verdict,
        ]
        for s in samples
    ]

    rssis = [s.rssi for s in samples if s.rssi is not None]
    summary = {
        "Session": session.name,
        "Area": session.area or "-",
        "Device": session.device or "-",
        "Started": _local(session.started_at).strftime("%Y-%m-%d %H:%M:%S"),
        "Ended": (
            _local(session.ended_at).strftime("%Y-%m-%d %H:%M:%S")
            if session.ended_at
            else "running"
        ),
        "Samples": len(samples),
        "Average RSSI (dBm)": round(sum(rssis) / len(rssis), 1) if rssis else None,
        "Min RSSI (dBm)": min(rssis) if rssis else None,
        "Max RSSI (dBm)": max(rssis) if rssis else None,
    }
    return _render(
        format,
        SAMPLE_HEADERS,
        rows,
        title=f"Monitor Session {session.name}",
        subtitle=session.area,
        summary=summary,
    )


@router.get("/heatmap/{plan_id}")
async def export_heatmap(
    plan_id: int,
    format: str = Query(default="xlsx", pattern="^(?i)(csv|xlsx|pdf)$"),
    db: Session = Depends(get_session),
) -> Response:
    """Export the survey points behind a heatmap, with a coverage breakdown."""
    plan = db.get(FloorPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Floor plan not found")

    points = db.scalars(
        select(SurveyPoint)
        .where(SurveyPoint.floor_plan_id == plan_id)
        .order_by(SurveyPoint.ts)
    ).all()

    rows = [
        [
            _local(p.ts).strftime("%Y-%m-%d %H:%M:%S"),
            p.label,
            round(p.x, 1),
            round(p.y, 1),
            p.ssid,
            p.bssid,
            p.channel,
            p.band,
            p.rssi,
            p.ping_ms,
            p.packet_loss_pct,
            p.grade,
        ]
        for p in points
    ]

    settings = load_settings(db)
    stats = summarise(
        [Point(p.x, p.y, float(p.rssi)) for p in points if p.rssi is not None], settings.bands
    )
    summary = {
        "Floor plan": plan.name,
        "Location": plan.location or "-",
        "Survey points": stats["total_points"],
        "Excellent": f'{stats["counts"]["EXCELLENT"]} ({stats["percent"]["EXCELLENT"]}%)',
        "Good": f'{stats["counts"]["GOOD"]} ({stats["percent"]["GOOD"]}%)',
        "Fair": f'{stats["counts"]["FAIR"]} ({stats["percent"]["FAIR"]}%)',
        "Poor": f'{stats["counts"]["POOR"]} ({stats["percent"]["POOR"]}%)',
        "Average RSSI (dBm)": stats["rssi_avg"],
        "Weakest point (dBm)": stats["rssi_min"],
    }
    return _render(
        format,
        POINT_HEADERS,
        rows,
        title=f"Heatmap Survey {plan.name}",
        subtitle=plan.location,
        summary=summary,
    )
