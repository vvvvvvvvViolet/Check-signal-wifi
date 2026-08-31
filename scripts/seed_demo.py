#!/usr/bin/env python3
"""Populate the app with a plausible factory survey so it can be evaluated.

Generates a floor plan, four APs, a grid of survey points measured against the
simulated RF model, and a spread of history records. Run against a running
server:

    python scripts/seed_demo.py [--base-url http://127.0.0.1:8000]

Safe to re-run: it always creates a new floor plan rather than editing one.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import random
import sys
import urllib.error
import urllib.request

WIDTH, HEIGHT = 1000, 520

# Where the APs sit on the plan, in plan pixels.
APS = [
    ("AP-Factory-01", "AA:BB:CC:DD:EE:01", 190, 150),
    ("AP-Factory-02", "AA:BB:CC:DD:EE:02", 780, 150),
    ("AP-Factory-03", "AA:BB:CC:DD:EE:03", 190, 400),
    ("AP-Factory-04", "AA:BB:CC:DD:EE:04", 780, 400),
]

def band_for(channel: int) -> str:
    """Channel 6 is 2.4 GHz however much one wishes otherwise."""
    return "2.4 GHz" if channel <= 14 else "5 GHz"


AREAS = ["Line-A", "Line-B", "Line-C", "Warehouse-1", "Warehouse-2", "QC-Lab"]
DEVICES = ["Scanner-01", "Scanner-02", "Tablet-07", "Forklift-PC-3"]


def build_plan_png() -> bytes:
    """Draw a simple factory floor: outer wall, aisles and labelled zones."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("Pillow is required: pip install -r backend/requirements.txt")

    image = Image.new("RGB", (WIDTH, HEIGHT), (24, 30, 43))
    draw = ImageDraw.Draw(image)
    wall = (100, 116, 139)

    draw.rectangle([8, 8, WIDTH - 8, HEIGHT - 8], outline=wall, width=4)
    for x in (WIDTH // 3, 2 * WIDTH // 3):
        draw.line([(x, 8), (x, HEIGHT - 8)], fill=(51, 65, 85), width=3)
    draw.line([(8, HEIGHT // 2), (WIDTH - 8, HEIGHT // 2)], fill=(51, 65, 85), width=2)

    for index, (label, x0) in enumerate((("PRODUCTION A", 30), ("PRODUCTION B", 360), ("WAREHOUSE", 700))):
        draw.text((x0, 24), label, fill=(148, 163, 184))
        del index

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def upload_plan(base: str, png: bytes, name: str, location: str) -> dict:
    boundary = "----csw-seed-boundary"
    parts: list[bytes] = []

    def field(key: str, value: str) -> None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        )

    field("name", name)
    field("location", location)
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="plan.png"\r\n'
        f"Content-Type: image/png\r\n\r\n".encode()
    )
    parts.append(png)
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        f"{base}/api/heatmap/plans",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


# A block of high steel racking in the middle-right of the floor. Every real
# survey has one of these, and a heatmap that never shows a weak zone is not
# demonstrating anything - so the demo data includes the shadow it casts.
SHADOW = {"x": 620, "y": 300, "radius": 165, "max_loss_db": 22.0}


def _rssi_from(ap: tuple, x: float, y: float) -> float:
    """Path-loss RSSI from one AP, shaped like the simulator's model."""
    _name, _bssid, ax, ay = ap
    # ~14 px per metre on this plan.
    distance_m = max(1.0, math.hypot(ax - x, ay - y) / 14.0)
    rssi = -28 - (40 + 10 * 2.9 * math.log10(distance_m)) + 40

    # Attenuation tapers to zero at the edge of the racking, so the heatmap
    # shows a gradient rather than a hard-edged disc.
    offset = math.hypot(SHADOW["x"] - x, SHADOW["y"] - y)
    if offset < SHADOW["radius"]:
        rssi -= SHADOW["max_loss_db"] * (1 - offset / SHADOW["radius"]) ** 1.5
    return rssi


def synth_neighbors(x: float, y: float, connected_bssid: str, rng: random.Random) -> list[dict]:
    """Every *other* AP audible from this spot.

    Without this the seeded survey cannot demonstrate the redundancy map, and
    every point would read as a blind spot.
    """
    neighbors = []
    for ap in APS:
        if ap[1] == connected_bssid:
            continue
        rssi = int(round(_rssi_from(ap, x, y) + rng.uniform(-2.5, 2.5)))
        if rssi >= -92:
            neighbors.append(
                {
                    "bssid": ap[1],
                    "ssid": "Factory-WiFi",
                    "rssi": rssi,
                    "channel": 44,
                    "band": "5 GHz",
                }
            )
    return neighbors


def strongest_ap(x: float, y: float) -> tuple:
    return max(APS, key=lambda ap: _rssi_from(ap, x, y))


def synth_rssi(x: float, y: float, rng: random.Random) -> int:
    """RSSI from the nearest AP, using the same path-loss shape as the simulator."""
    best = -99.0
    for _name, _bssid, ax, ay in APS:
        # ~14 px per metre on this plan.
        distance_m = max(1.0, math.hypot(ax - x, ay - y) / 14.0)
        rssi = -28 - (40 + 10 * 2.9 * math.log10(distance_m)) + 40
        best = max(best, rssi)

    # Attenuation tapers to zero at the edge of the racking, so the heatmap
    # shows a gradient rather than a hard-edged disc.
    offset = math.hypot(SHADOW["x"] - x, SHADOW["y"] - y)
    if offset < SHADOW["radius"]:
        best -= SHADOW["max_loss_db"] * (1 - offset / SHADOW["radius"]) ** 1.5

    return int(round(best + rng.uniform(-2.5, 2.5)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--spacing", type=int, default=85, help="survey point spacing in pixels")
    parser.add_argument("--history", type=int, default=24, help="history records to create")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    rng = random.Random(args.seed)

    try:
        with urllib.request.urlopen(f"{base}/api/health", timeout=10) as response:
            health = json.load(response)
    except (urllib.error.URLError, OSError) as exc:
        return _fail(f"Cannot reach {base}: {exc}\nStart the server first.")

    print(f"Server {health['version']} · wifi backend: {health['wifi_backend']}")

    plan = upload_plan(base, build_plan_png(), "Production-A", "Building 1")
    print(f"Floor plan #{plan['id']} created ({plan['width_px']}x{plan['height_px']})")

    for name, bssid, x, y in APS:
        post(f"{base}/api/heatmap/plans/{plan['id']}/aps", {"name": name, "bssid": bssid, "x": x, "y": y})
    print(f"{len(APS)} access points placed")

    points = 0
    for y in range(60, HEIGHT - 40, args.spacing):
        for x in range(60, WIDTH - 40, args.spacing):
            jitter_x = x + rng.randint(-12, 12)
            jitter_y = y + rng.randint(-12, 12)
            channel = rng.choice([36, 44, 149, 6])
            connected = strongest_ap(jitter_x, jitter_y)
            post(
                f"{base}/api/heatmap/plans/{plan['id']}/points",
                {
                    "x": jitter_x,
                    "y": jitter_y,
                    "measure": False,
                    "label": None,
                    "ssid": "Factory-WiFi",
                    "bssid": connected[1],
                    "channel": channel,
                    "band": band_for(channel),
                    "rssi": synth_rssi(jitter_x, jitter_y, rng),
                    "ping_ms": round(rng.uniform(1.5, 12.0), 2),
                    "packet_loss_pct": 0.0,
                    "neighbors": synth_neighbors(jitter_x, jitter_y, connected[1], rng),
                },
            )
            points += 1
    print(f"{points} survey points captured")

    for _ in range(args.history):
        channel = rng.choice([36, 44, 149, 6])
        rssi = rng.choice([-48, -52, -58, -61, -66, -68, -71, -76, -79])
        # Latency tracks signal loosely, with the odd upstream spike.
        ping = round(max(1.5, (abs(rssi) - 40) * rng.uniform(0.4, 1.4)), 2)
        if rng.random() < 0.12:
            ping = round(rng.uniform(120, 300), 2)
        loss = 0.0 if rssi > -70 else round(rng.uniform(0, 9), 1)
        post(
            f"{base}/api/history",
            {
                "area": rng.choice(AREAS),
                "device": rng.choice(DEVICES),
                "measure": False,
                "ssid": "Factory-WiFi",
                "bssid": rng.choice(APS)[1],
                "channel": channel,
                "band": band_for(channel),
                "rssi": rssi,
                "ping_ms": ping,
                "packet_loss_pct": loss,
            },
        )
    print(f"{args.history} history records created")
    print(f"\nOpen {base}/ to explore.")
    return 0


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
