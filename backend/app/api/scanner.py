"""WiFi Scanner: every BSSID in range, plus a channel-utilisation view."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_session
from ..services.quality import GRADE_COLOR, grade_rssi
from ..services.settings_store import load_settings
from ..wifi import get_adapter

router = APIRouter(prefix="/api/scan", tags=["scanner"])


@router.get("")
async def scan(
    ssid: str | None = Query(default=None, description="Case-insensitive SSID filter"),
    band: str | None = Query(default=None, description="e.g. '2.4', '5', '6'"),
    min_rssi: int | None = Query(default=None, le=0),
    db: Session = Depends(get_session),
) -> dict:
    settings = load_settings(db)
    adapter = get_adapter()
    networks = await asyncio.to_thread(adapter.scan)

    rows = []
    for net in networks:
        data = net.as_dict()
        data["grade"] = grade_rssi(net.rssi, settings.bands)
        data["grade_color"] = GRADE_COLOR[data["grade"]]
        rows.append(data)

    if ssid:
        needle = ssid.lower()
        rows = [r for r in rows if needle in (r["ssid"] or "").lower()]
    if band:
        rows = [r for r in rows if (r["band"] or "").startswith(band)]
    if min_rssi is not None:
        rows = [r for r in rows if r["rssi"] is not None and r["rssi"] >= min_rssi]

    # Strongest first - that is the one the client would actually pick.
    rows.sort(key=lambda r: (r["rssi"] is None, -(r["rssi"] or -999)))

    by_ssid: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_ssid[row["ssid"] or "(hidden)"].append(row)

    channels = Counter(r["channel"] for r in rows if r["channel"] is not None)
    bands = Counter(r["band"] for r in rows if r["band"])

    return {
        "backend": adapter.name,
        "count": len(rows),
        "networks": rows,
        "ssid_groups": [
            {
                "ssid": name,
                "bssid_count": len(items),
                "best_rssi": max((i["rssi"] for i in items if i["rssi"] is not None), default=None),
                "channels": sorted({i["channel"] for i in items if i["channel"] is not None}),
                "bands": sorted({i["band"] for i in items if i["band"]}),
            }
            for name, items in sorted(by_ssid.items(), key=lambda kv: kv[0].lower())
        ],
        "channel_usage": [
            {"channel": ch, "count": n, "band": _band_of(ch, rows)}
            for ch, n in sorted(channels.items())
        ],
        "band_usage": [{"band": b, "count": n} for b, n in sorted(bands.items())],
    }


def _band_of(channel: int, rows: list[dict]) -> str | None:
    return next((r["band"] for r in rows if r["channel"] == channel and r["band"]), None)
