"""Turn scattered survey points into a coverage grid.

Interpolation is inverse-distance weighting (IDW). It is the right choice here
over something fancier: it is exact at the measured points, needs no fitting,
and degrades honestly - far from any measurement the estimate flattens toward
the local mean instead of inventing structure.

Two guards keep it from lying:

* ``max_influence_px`` - cells with no measurement within this radius are left
  empty rather than extrapolated, so unsurveyed floor reads as "unknown", not
  as "green".
* ``power`` - higher values make each point more local. 2.0 is the usual
  default and matches how RSSI actually falls off over short distances.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import SignalBands
from .quality import GRADE_COLOR, grade_rssi

DEFAULT_GRID = 48
DEFAULT_POWER = 2.0


@dataclass(slots=True)
class Point:
    x: float
    y: float
    value: float


def interpolate_grid(
    points: list[Point],
    width_px: int,
    height_px: int,
    *,
    grid_size: int = DEFAULT_GRID,
    power: float = DEFAULT_POWER,
    max_influence_px: float | None = None,
) -> dict:
    """IDW-interpolate ``points`` onto a ``grid_size`` x N cell grid.

    Returns a row-major matrix of RSSI values with ``None`` for cells no
    measurement can vouch for.
    """
    if width_px <= 0 or height_px <= 0:
        raise ValueError("floor plan dimensions must be positive")

    cols = max(2, min(grid_size, 256))
    # Keep cells square so the heatmap is not stretched on non-square plans.
    rows = max(2, min(256, round(cols * height_px / width_px)))
    cell_w = width_px / cols
    cell_h = height_px / rows

    if max_influence_px is None:
        # Default: a quarter of the plan's diagonal - wide enough to bridge a
        # normal survey spacing, tight enough to leave real gaps visible.
        max_influence_px = 0.25 * math.hypot(width_px, height_px)

    matrix: list[list[float | None]] = []
    for row in range(rows):
        cy = (row + 0.5) * cell_h
        line: list[float | None] = []
        for col in range(cols):
            cx = (col + 0.5) * cell_w
            line.append(_idw_at(points, cx, cy, power, max_influence_px))
        matrix.append(line)

    values = [v for line in matrix for v in line if v is not None]
    return {
        "cols": cols,
        "rows": rows,
        "cell_width_px": round(cell_w, 3),
        "cell_height_px": round(cell_h, 3),
        "matrix": [[round(v, 1) if v is not None else None for v in line] for line in matrix],
        "min": round(min(values), 1) if values else None,
        "max": round(max(values), 1) if values else None,
        "covered_pct": round(100 * len(values) / (rows * cols), 1) if rows and cols else 0.0,
        "max_influence_px": round(max_influence_px, 1),
        "power": power,
    }


def _idw_at(
    points: list[Point], x: float, y: float, power: float, max_influence: float
) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for point in points:
        distance = math.hypot(point.x - x, point.y - y)
        if distance > max_influence:
            continue
        if distance < 1e-6:
            # Exactly on a measurement: return it rather than dividing by zero.
            return point.value
        weight = 1.0 / (distance**power)
        numerator += weight * point.value
        denominator += weight
    if denominator == 0.0:
        return None
    return numerator / denominator


REDUNDANCY_COLORS = {
    0: "#ef4444",  # nowhere to roam - the client drops when it moves
    1: "#facc15",  # one fallback, no margin
    2: "#4ade80",
    3: "#16a34a",
}
REDUNDANCY_LABELS = {
    0: "No alternative AP",
    1: "1 alternative",
    2: "2 alternatives",
    3: "3 or more",
}


def redundancy_at(neighbors: list | None, min_rssi: int, ssid: str | None = None) -> int:
    """How many *other* access points are usable from this spot.

    Coverage and redundancy are different questions. A point can sit at -45 dBm
    and still be the place a forklift drops its session, because the only AP it
    can hear is the one it is about to walk away from. Counting usable
    alternatives is what makes that visible on a plan.
    """
    if not neighbors:
        return 0
    seen: set[str] = set()
    for neighbor in neighbors:
        if not isinstance(neighbor, dict):
            continue
        rssi = neighbor.get("rssi")
        bssid = neighbor.get("bssid")
        if bssid is None or rssi is None or rssi < min_rssi:
            continue
        # Only the surveyed network counts; a guest SSID is not a fallback.
        if ssid is not None and neighbor.get("ssid") != ssid:
            continue
        seen.add(bssid)
    return len(seen)


def summarise_redundancy(points: list[Point]) -> dict:
    """Breakdown of how many points have how many fallbacks."""
    counts: dict[str, int] = {label: 0 for label in REDUNDANCY_LABELS.values()}
    for point in points:
        bucket = min(3, int(round(point.value)))
        counts[REDUNDANCY_LABELS[max(0, bucket)]] += 1
    total = sum(counts.values())
    values = [p.value for p in points]
    return {
        "total_points": total,
        "counts": counts,
        "percent": {k: round(100 * v / total, 1) if total else 0.0 for k, v in counts.items()},
        "colors": {REDUNDANCY_LABELS[k]: v for k, v in REDUNDANCY_COLORS.items()},
        "min": int(min(values)) if values else None,
        "max": int(max(values)) if values else None,
        "avg": round(sum(values) / len(values), 2) if values else None,
        "blind_spots": sum(1 for v in values if v < 1),
    }


def summarise(points: list[Point], bands: SignalBands | None = None) -> dict:
    """Coverage breakdown by grade, for the legend and the report."""
    bands = bands or SignalBands()
    counts = {"EXCELLENT": 0, "GOOD": 0, "FAIR": 0, "POOR": 0, "UNKNOWN": 0}
    for point in points:
        counts[grade_rssi(int(round(point.value)), bands)] += 1
    total = sum(counts.values())
    values = [p.value for p in points]
    return {
        "total_points": total,
        "counts": counts,
        "percent": {
            key: round(100 * value / total, 1) if total else 0.0 for key, value in counts.items()
        },
        "colors": GRADE_COLOR,
        "rssi_min": round(min(values), 1) if values else None,
        "rssi_max": round(max(values), 1) if values else None,
        "rssi_avg": round(sum(values) / len(values), 1) if values else None,
    }


def grade_matrix(
    matrix: list[list[float | None]], bands: SignalBands | None = None
) -> list[list[str | None]]:
    """Map an interpolated grid to grade names for client-side colouring."""
    bands = bands or SignalBands()
    return [
        [grade_rssi(int(round(v)), bands) if v is not None else None for v in row] for row in matrix
    ]
