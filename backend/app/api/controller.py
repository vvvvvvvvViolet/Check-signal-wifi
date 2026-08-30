"""WLAN Controller: cross-check the client's view of the network against
what the WLC itself reports, over SNMP.

Disabled by default and returns ``503`` while it is - this endpoint reaches
out to enterprise infrastructure rather than only the machine the app runs
on, so it must be turned on deliberately in Settings rather than probed by
accident.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import ControllerConfig
from ..db import get_session
from ..services import controller as controller_service
from ..services import snmp as snmp_service
from ..services.settings_store import load_settings
from ..wifi import get_adapter

router = APIRouter(prefix="/api/controller", tags=["controller"])


def _require_enabled(config: ControllerConfig) -> None:
    if not config.enabled or not config.host:
        raise HTTPException(
            status_code=503,
            detail=(
                "Controller monitoring is not configured. "
                "Set the host and enable it in Settings."
            ),
        )


@router.get("/status")
async def status(db: Session = Depends(get_session)) -> dict:
    """Confirm the WLC answers at all, before trusting anything Cisco-specific
    from it. Standard MIB-II - no vendor-specific OID guesswork here."""
    settings = load_settings(db)
    _require_enabled(settings.controller)
    return await controller_service.check_reachable(settings.controller)


@router.get("/aps")
async def access_points(db: Session = Depends(get_session)) -> dict:
    """Every AP the controller manages, with each radio's channel and load."""
    settings = load_settings(db)
    _require_enabled(settings.controller)
    try:
        aps = await controller_service.list_access_points(settings.controller)
    except snmp_service.SnmpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "count": len(aps),
        "access_points": [
            {
                "index": ap.index,
                "name": ap.name,
                "ip_address": ap.ip_address,
                "mac_address": ap.mac_address,
                "model": ap.model,
                "location": ap.location,
                "operation_status": ap.operation_status,
                "radios": [
                    {
                        "radio_index": radio.radio_index,
                        "channel": radio.channel,
                        "operation_status": radio.operation_status,
                        "tx_power_level": radio.tx_power_level,
                        "client_count": radio.client_count,
                        "channel_utilization_pct": radio.channel_utilization_pct,
                    }
                    for radio in ap.radios
                ],
            }
            for ap in aps
        ],
    }


@router.get("/clients")
async def clients(db: Session = Depends(get_session)) -> dict:
    """Every client the controller currently holds, across every AP.

    Cross-referenced against this machine's own MAC below the JSON so the
    caller does not have to do that matching itself.
    """
    settings = load_settings(db)
    _require_enabled(settings.controller)
    try:
        rows = await controller_service.list_clients(settings.controller)
    except snmp_service.SnmpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "count": len(rows),
        "clients": [
            {
                "mac_address": row.mac_address,
                "ap_mac": row.ap_mac,
                "ssid": row.ssid,
                "rssi": row.rssi,
                "snr": row.snr,
                "status": row.status,
            }
            for row in rows
        ],
    }


@router.get("/self-check")
async def self_check(db: Session = Depends(get_session)) -> dict:
    """Does the controller's record of this machine agree with what the
    radio itself reports?

    This is the one check that needs *both* sides: the client-side BSSID this
    survey has been reading all along, and the controller's own client table.
    A mismatch - the client believes it holds AP X, but the WLC has no record
    of this MAC there - is a stale association the AP has already dropped,
    which neither side alone would reveal.
    """
    settings = load_settings(db)
    _require_enabled(settings.controller)

    link = (await asyncio.to_thread(get_adapter().get_link)).as_dict()
    try:
        rows = await controller_service.list_clients(settings.controller)
    except snmp_service.SnmpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return controller_service.compare_client_to_controller(link, rows)


@router.get("/raw")
async def raw(
    oid: str = Query(..., description="OID subtree to walk, e.g. 1.3.6.1.4.1.14179.2.2.1.1"),
    max_rows: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_session),
) -> dict:
    """Verification tool for the OID tables ``services/controller.py`` assumes.

    Dumps a subtree unmapped, exactly as the device returns it - the same
    instrument that resolved the Windows netsh locale bug. Point it at a table
    root and compare the columns against the WLC's own CLI or web UI to
    confirm (or correct) the column-number maps this module relies on.
    """
    settings = load_settings(db)
    _require_enabled(settings.controller)
    try:
        rows = await controller_service.raw_walk(settings.controller, oid, max_rows=max_rows)
    except snmp_service.SnmpError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"oid": oid, "count": len(rows), "rows": rows}
