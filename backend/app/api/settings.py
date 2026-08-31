"""Settings: thresholds, ping targets and monitor cadence."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import WIFI_BACKEND, AppSettings
from ..db import get_session
from ..schemas import SettingsOut
from ..services import settings_store
from ..wifi import get_adapter

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
async def read_settings(db: Session = Depends(get_session)) -> SettingsOut:
    return SettingsOut(
        settings=settings_store.load_settings(db),
        stored=settings_store.has_stored_settings(db),
        wifi_backend=get_adapter().name,
    )


@router.put("", response_model=SettingsOut)
async def write_settings(payload: AppSettings, db: Session = Depends(get_session)) -> SettingsOut:
    saved = settings_store.save_settings(db, payload)
    return SettingsOut(settings=saved, stored=True, wifi_backend=get_adapter().name)


@router.post("/reset", response_model=SettingsOut)
async def reset(db: Session = Depends(get_session)) -> SettingsOut:
    saved = settings_store.reset_settings(db)
    return SettingsOut(settings=saved, stored=True, wifi_backend=get_adapter().name)


@router.get("/backend")
async def backend_info() -> dict:
    adapter = get_adapter()
    return {
        "backend": adapter.name,
        "configured": WIFI_BACKEND,
        "simulated": adapter.name == "mock",
        "note": (
            "Running against simulated data. Set CSW_WIFI_BACKEND or install nmcli/iw "
            "(Linux), use netsh (Windows) or airport (macOS) for live readings."
            if adapter.name == "mock"
            else None
        ),
    }
