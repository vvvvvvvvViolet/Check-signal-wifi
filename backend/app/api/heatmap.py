"""Floor plans, survey points and the interpolated coverage grid."""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import FLOORPLAN_DIR
from ..db import get_session
from ..models import AccessPointMarker, FloorPlan, SurveyPoint
from ..schemas import (
    AccessPointMarkerCreate,
    AccessPointMarkerOut,
    FloorPlanOut,
    FloorPlanUpdate,
    SurveyPointCreate,
    SurveyPointOut,
)
from ..services import heatmap as heatmap_service
from ..services import probe
from ..services.quality import GRADE_COLOR, grade_rssi
from ..services.settings_store import load_settings

router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])

ALLOWED_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


# ----------------------------------------------------------- floor plans
@router.post("/plans", response_model=FloorPlanOut, status_code=201)
async def upload_plan(
    file: UploadFile = File(...),
    name: str = Form(...),
    location: str | None = Form(default=None),
    meters_per_px: float | None = Form(default=None),
    db: Session = Depends(get_session),
):
    """Upload a building/factory plan.

    The image is decoded before it is stored so a corrupt or mislabelled file
    fails here rather than when someone is standing on the factory floor trying
    to drop a point on it.
    """
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Floor plan must be 20 MB or smaller")
    if not payload:
        raise HTTPException(status_code=400, detail="Empty upload")

    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
            fmt = (image.format or "").lower()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"Unreadable image: {exc}") from exc

    suffix = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}.get(fmt)
    if suffix is None:
        raise HTTPException(status_code=415, detail="Use PNG, JPEG or WebP")

    filename = f"{uuid.uuid4().hex}{suffix}"
    (FLOORPLAN_DIR / filename).write_bytes(payload)

    plan = FloorPlan(
        name=name,
        location=location,
        image_filename=filename,
        width_px=width,
        height_px=height,
        meters_per_px=meters_per_px if meters_per_px and meters_per_px > 0 else None,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/plans", response_model=list[FloorPlanOut])
async def list_plans(db: Session = Depends(get_session)):
    return db.scalars(select(FloorPlan).order_by(FloorPlan.created_at.desc())).all()


@router.get("/plans/{plan_id}", response_model=FloorPlanOut)
async def get_plan(plan_id: int, db: Session = Depends(get_session)):
    return _require_plan(db, plan_id)


@router.patch("/plans/{plan_id}", response_model=FloorPlanOut)
async def update_plan(plan_id: int, payload: FloorPlanUpdate, db: Session = Depends(get_session)):
    plan = _require_plan(db, plan_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/plans/{plan_id}", status_code=204, response_model=None)
async def delete_plan(plan_id: int, db: Session = Depends(get_session)) -> None:
    plan = _require_plan(db, plan_id)
    image_path = FLOORPLAN_DIR / plan.image_filename
    db.delete(plan)
    db.commit()
    image_path.unlink(missing_ok=True)


@router.get("/plans/{plan_id}/image")
async def plan_image(plan_id: int, db: Session = Depends(get_session)):
    plan = _require_plan(db, plan_id)
    path = FLOORPLAN_DIR / plan.image_filename
    # Resolve and re-check: the filename comes from the DB, but a path that
    # escapes the upload directory must never be served.
    resolved = path.resolve()
    if not resolved.is_relative_to(Path(FLOORPLAN_DIR).resolve()) or not resolved.exists():
        raise HTTPException(status_code=404, detail="Floor plan image is missing")
    return FileResponse(resolved)


# --------------------------------------------------------- survey points
@router.post("/plans/{plan_id}/points", response_model=SurveyPointOut, status_code=201)
async def add_point(
    plan_id: int, payload: SurveyPointCreate, db: Session = Depends(get_session)
):
    plan = _require_plan(db, plan_id)
    if payload.x > plan.width_px or payload.y > plan.height_px:
        raise HTTPException(status_code=400, detail="Point falls outside the floor plan")

    settings = load_settings(db)
    data = payload.model_dump(exclude={"measure"})

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
            packet_loss_pct=summary.get("packet_loss_pct"),
        )

    point = SurveyPoint(
        floor_plan_id=plan_id,
        **data,
        grade=grade_rssi(data.get("rssi"), settings.bands),
    )
    db.add(point)
    db.commit()
    db.refresh(point)
    return point


@router.get("/plans/{plan_id}/points", response_model=list[SurveyPointOut])
async def list_points(
    plan_id: int,
    ssid: str | None = None,
    bssid: str | None = None,
    db: Session = Depends(get_session),
):
    _require_plan(db, plan_id)
    stmt = select(SurveyPoint).where(SurveyPoint.floor_plan_id == plan_id)
    if ssid:
        stmt = stmt.where(SurveyPoint.ssid == ssid)
    if bssid:
        stmt = stmt.where(SurveyPoint.bssid == bssid)
    return db.scalars(stmt.order_by(SurveyPoint.ts)).all()


@router.delete("/points/{point_id}", status_code=204, response_model=None)
async def delete_point(point_id: int, db: Session = Depends(get_session)) -> None:
    point = db.get(SurveyPoint, point_id)
    if point is None:
        raise HTTPException(status_code=404, detail="Survey point not found")
    db.delete(point)
    db.commit()


# ------------------------------------------------------------ AP markers
@router.post("/plans/{plan_id}/aps", response_model=AccessPointMarkerOut, status_code=201)
async def add_ap(
    plan_id: int, payload: AccessPointMarkerCreate, db: Session = Depends(get_session)
):
    _require_plan(db, plan_id)
    marker = AccessPointMarker(floor_plan_id=plan_id, **payload.model_dump())
    db.add(marker)
    db.commit()
    db.refresh(marker)
    return marker


@router.get("/plans/{plan_id}/aps", response_model=list[AccessPointMarkerOut])
async def list_aps(plan_id: int, db: Session = Depends(get_session)):
    _require_plan(db, plan_id)
    return db.scalars(
        select(AccessPointMarker).where(AccessPointMarker.floor_plan_id == plan_id)
    ).all()


@router.delete("/aps/{ap_id}", status_code=204, response_model=None)
async def delete_ap(ap_id: int, db: Session = Depends(get_session)) -> None:
    marker = db.get(AccessPointMarker, ap_id)
    if marker is None:
        raise HTTPException(status_code=404, detail="Access point marker not found")
    db.delete(marker)
    db.commit()


# ---------------------------------------------------------------- render
@router.get("/plans/{plan_id}/grid")
async def coverage_grid(
    plan_id: int,
    ssid: str | None = None,
    grid_size: int = Query(default=48, ge=8, le=160),
    power: float = Query(default=2.0, ge=0.5, le=6.0),
    max_influence_px: float | None = Query(default=None, gt=0),
    db: Session = Depends(get_session),
) -> dict:
    """Interpolated RSSI grid plus the points and APs to draw over it."""
    plan = _require_plan(db, plan_id)
    settings = load_settings(db)

    stmt = select(SurveyPoint).where(
        SurveyPoint.floor_plan_id == plan_id, SurveyPoint.rssi.is_not(None)
    )
    if ssid:
        stmt = stmt.where(SurveyPoint.ssid == ssid)
    points = db.scalars(stmt).all()

    measurements = [heatmap_service.Point(p.x, p.y, float(p.rssi)) for p in points]
    if not measurements:
        return {
            "plan": FloorPlanOut.model_validate(plan).model_dump(mode="json"),
            "grid": None,
            "summary": heatmap_service.summarise([], settings.bands),
            "points": [],
            "access_points": [],
            "colors": GRADE_COLOR,
            "message": "No measurements captured on this plan yet",
        }

    grid = heatmap_service.interpolate_grid(
        measurements,
        plan.width_px,
        plan.height_px,
        grid_size=grid_size,
        power=power,
        max_influence_px=max_influence_px,
    )
    grid["grades"] = heatmap_service.grade_matrix(grid["matrix"], settings.bands)

    return {
        "plan": FloorPlanOut.model_validate(plan).model_dump(mode="json"),
        "grid": grid,
        "summary": heatmap_service.summarise(measurements, settings.bands),
        "points": [SurveyPointOut.model_validate(p).model_dump(mode="json") for p in points],
        "access_points": [
            AccessPointMarkerOut.model_validate(a).model_dump(mode="json")
            for a in db.scalars(
                select(AccessPointMarker).where(AccessPointMarker.floor_plan_id == plan_id)
            ).all()
        ],
        "colors": GRADE_COLOR,
        "bands": settings.bands.model_dump(),
    }


def _require_plan(db: Session, plan_id: int) -> FloorPlan:
    plan = db.get(FloorPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Floor plan not found")
    return plan
