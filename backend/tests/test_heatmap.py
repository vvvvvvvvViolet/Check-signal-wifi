"""IDW must be exact at measurements and honest about gaps."""

from __future__ import annotations

import pytest
from backend.app.services.heatmap import (
    Point,
    default_influence_px,
    grade_matrix,
    interpolate_grid,
    redundancy_at,
    summarise,
    summarise_redundancy,
)


def test_interpolation_is_exact_at_a_measured_point():
    points = [Point(0, 0, -40.0), Point(100, 100, -80.0)]
    grid = interpolate_grid(points, 100, 100, grid_size=2)
    # With a 2x2 grid, cell centres sit at 25 and 75; the corner values dominate.
    assert grid["min"] is not None and grid["max"] is not None
    assert grid["max"] <= -40.0
    assert grid["min"] >= -80.0


def test_single_point_fills_only_its_neighbourhood():
    grid = interpolate_grid([Point(10, 10, -55.0)], 1000, 1000, grid_size=20)
    flat = [v for row in grid["matrix"] for v in row]
    assert any(v is None for v in flat), "far cells must stay unknown, not be invented"
    assert all(v == -55.0 for v in flat if v is not None)
    assert grid["covered_pct"] < 100


def test_interpolated_values_stay_within_the_measured_range():
    """IDW is an average of the inputs, so it must never extrapolate past them."""
    points = [Point(10, 10, -45.0), Point(90, 10, -75.0), Point(50, 90, -60.0)]
    grid = interpolate_grid(points, 100, 100, grid_size=16)
    values = [v for row in grid["matrix"] for v in row if v is not None]
    assert values
    assert min(values) >= -75.0 - 1e-6
    assert max(values) <= -45.0 + 1e-6


def test_grid_cells_stay_square_on_a_wide_plan():
    grid = interpolate_grid([Point(5, 5, -50.0)], 800, 400, grid_size=40)
    assert grid["cols"] == 40
    assert grid["rows"] == 20
    assert grid["cell_width_px"] == pytest.approx(grid["cell_height_px"])


def test_zero_dimensions_are_rejected():
    with pytest.raises(ValueError):
        interpolate_grid([Point(0, 0, -50.0)], 0, 100)


def test_influence_does_not_grow_with_the_plans_resolution():
    """The same survey scanned at a higher resolution must not claim more floor.

    The reach of a reading used to be a fraction of the plan diagonal, so
    re-exporting the same drawing at twice the size doubled how far every
    reading spoke for - and a lone point on a large CAD export painted a third
    of the building at its own value.
    """
    # The same four readings, laid out on plans that differ only in scale.
    small = [Point(100, 100, -55.0), Point(300, 100, -60.0), Point(100, 300, -58.0)]
    large = [Point(p.x * 4, p.y * 4, p.value) for p in small]

    small_reach = default_influence_px(small, 1000, 1000)
    large_reach = default_influence_px(large, 4000, 4000)

    # Reach scales with the survey, so as a share of the plan it is unchanged.
    assert large_reach / 4000 == pytest.approx(small_reach / 1000, rel=1e-6)


def test_a_lone_reading_claims_only_a_small_neighbourhood():
    """One point is evidence about where the meter stood, not about the site."""
    width = height = 4000
    reach = default_influence_px([Point(200, 2000, -38.0)], width, height)
    assert reach < 0.10 * width, "a single reading must not span the building"

    grid = interpolate_grid([Point(200, 2000, -38.0)], width, height, grid_size=48)
    # Most of an unsurveyed building has to stay unknown rather than read green.
    assert grid["covered_pct"] < 10


def test_reach_follows_how_far_apart_the_readings_actually_are():
    tight = [Point(500 + i * 20, 500, -55.0) for i in range(6)]
    spread = [Point(500 + i * 200, 500, -55.0) for i in range(6)]
    assert default_influence_px(tight, 2000, 2000) < default_influence_px(spread, 2000, 2000)


def test_a_proper_survey_leaves_no_holes_between_its_readings():
    """Tightening the default must not punch holes in a normally spaced survey.

    Floor beyond the surveyed rectangle is a different matter: that genuinely
    was not measured, and is asserted to stay unknown here rather than being
    filled in from the nearest reading several rooms away.
    """
    points = [Point(80 + i * 120, 80 + j * 120, -55.0) for i in range(8) for j in range(4)]
    grid = interpolate_grid(points, 1100, 600, grid_size=48)
    cell_w, cell_h = grid["cell_width_px"], grid["cell_height_px"]

    def cell_at(x: float, y: float):
        return grid["matrix"][int(y / cell_h)][int(x / cell_w)]

    # Dead centre of four adjacent readings - the worst case for a gap.
    assert cell_at(140, 140) == pytest.approx(-55.0)
    # Well outside the surveyed rectangle, which stopped at x=920, y=440.
    assert cell_at(1080, 580) is None


def test_readings_stacked_on_one_spot_do_not_collapse_the_reach():
    """Identical coordinates carry no spacing information, so they get no vote."""
    stacked = [Point(500, 500, -55.0), Point(500, 500, -57.0)]
    assert default_influence_px(stacked, 2000, 2000) > 0


def test_summary_counts_by_grade():
    points = [Point(0, 0, -50.0), Point(1, 1, -60.0), Point(2, 2, -70.0), Point(3, 3, -80.0)]
    stats = summarise(points)
    assert stats["total_points"] == 4
    assert stats["counts"] == {
        "EXCELLENT": 1,
        "GOOD": 1,
        "FAIR": 1,
        "POOR": 1,
        "UNKNOWN": 0,
    }
    assert stats["rssi_avg"] == -65.0


def test_grade_matrix_preserves_gaps():
    matrix = [[-50.0, None], [-80.0, -66.0]]
    assert grade_matrix(matrix) == [["EXCELLENT", None], ["POOR", "FAIR"]]


# ----------------------------------------------------------- redundancy
def test_redundancy_counts_only_usable_alternatives():
    neighbors = [
        {"bssid": "AA:00", "ssid": "Factory-WiFi", "rssi": -60},
        {"bssid": "AA:01", "ssid": "Factory-WiFi", "rssi": -68},
        {"bssid": "AA:02", "ssid": "Factory-WiFi", "rssi": -85},  # too weak to roam to
    ]
    assert redundancy_at(neighbors, -70, "Factory-WiFi") == 2


def test_redundancy_ignores_other_networks():
    """A guest SSID is not somewhere a factory scanner can fall back to."""
    neighbors = [
        {"bssid": "AA:00", "ssid": "Factory-WiFi", "rssi": -60},
        {"bssid": "BB:00", "ssid": "Guest-WiFi", "rssi": -55},
    ]
    assert redundancy_at(neighbors, -70, "Factory-WiFi") == 1
    # With no SSID given, every audible AP counts.
    assert redundancy_at(neighbors, -70, None) == 2


def test_redundancy_deduplicates_repeated_bssids():
    neighbors = [
        {"bssid": "AA:00", "ssid": "X", "rssi": -60},
        {"bssid": "AA:00", "ssid": "X", "rssi": -62},
    ]
    assert redundancy_at(neighbors, -70, "X") == 1


def test_redundancy_of_nothing_is_zero_not_an_error():
    assert redundancy_at(None, -70) == 0
    assert redundancy_at([], -70) == 0
    assert redundancy_at([{"rssi": -50}, "junk", {"bssid": "AA:00"}], -70) == 0


def test_redundancy_summary_flags_blind_spots():
    points = [Point(0, 0, 0.0), Point(1, 1, 1.0), Point(2, 2, 3.0), Point(3, 3, 2.0)]
    stats = summarise_redundancy(points)
    assert stats["total_points"] == 4
    assert stats["blind_spots"] == 1
    assert stats["counts"]["No alternative AP"] == 1
    assert stats["counts"]["3 or more"] == 1
    assert stats["min"] == 0
    assert stats["max"] == 3
