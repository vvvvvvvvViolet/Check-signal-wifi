"""Network Test: the WiFi -> Gateway -> LAN -> DNS -> Internet ladder."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_session
from ..services import net_test, probe
from ..services.settings_store import load_settings

router = APIRouter(prefix="/api/nettest", tags=["network-test"])


@router.get("/chain")
async def chain(db: Session = Depends(get_session)) -> dict:
    settings = load_settings(db)
    return await probe.connectivity_chain(settings)


@router.get("/ping")
async def ping(
    target: str = Query(..., min_length=1, max_length=253),
    count: int = Query(default=4, ge=1, le=20),
    timeout: float = Query(default=1.0, ge=0.2, le=10.0),
) -> dict:
    result = await net_test.ping_async(target, count, timeout)
    return result.as_dict()


@router.get("/dns")
async def dns(
    hostname: str = Query(default="www.google.com", min_length=1, max_length=253),
) -> dict:
    return await asyncio.to_thread(net_test.dns_lookup, hostname)


@router.get("/traceroute")
async def trace(
    target: str = Query(..., min_length=1, max_length=253),
    max_hops: int = Query(default=12, ge=1, le=30),
) -> dict:
    hops = await asyncio.to_thread(net_test.traceroute, target, max_hops)
    return {
        "target": target,
        "hops": hops,
        "available": bool(hops),
        "note": None if hops else "traceroute/tracert is not installed on this host",
    }


@router.get("/gateway")
async def gateway(db: Session = Depends(get_session)) -> dict:
    settings = load_settings(db)
    address, auto = await asyncio.to_thread(net_test.resolve_gateway, settings.ping.gateway)
    local = await asyncio.to_thread(net_test.local_ip)
    return {"gateway": address, "auto_detected": auto, "local_ip": local}
