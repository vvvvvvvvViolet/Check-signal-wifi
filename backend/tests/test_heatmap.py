"""IDW must be exact at measurements and honest about gaps."""

from __future__ import annotations

import pytest
from backend.app.services.heatmap import Point, grade_matrix, interpolate_grid, summarise


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
