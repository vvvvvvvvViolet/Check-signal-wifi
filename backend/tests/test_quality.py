"""The grading scale is the contract the whole UI is coloured by."""

from __future__ import annotations

import pytest
from backend.app.config import AppSettings
from backend.app.services import quality


@pytest.mark.parametrize(
    ("rssi", "expected"),
    [
        (-30, quality.EXCELLENT),
        (-55, quality.EXCELLENT),  # boundary: -55 is Excellent, not Good
        (-56, quality.GOOD),
        (-65, quality.GOOD),  # boundary: -65 is Good, not Fair
        (-66, quality.FAIR),
        (-72, quality.FAIR),  # boundary: -72 is Fair, not Poor
        (-73, quality.POOR),
        (-95, quality.POOR),
        (None, quality.UNKNOWN),
    ],
)
def test_grade_boundaries_match_the_spec(rssi, expected):
    assert quality.grade_rssi(rssi) == expected


def test_signal_percent_is_clamped():
    assert quality.signal_percent(-90) == 0
    assert quality.signal_percent(-30) == 100
    assert quality.signal_percent(-120) == 0
    assert quality.signal_percent(10) == 100
    assert quality.signal_percent(None) == 0


def test_good_signal_with_bad_latency_fails(settings: AppSettings):
    result = quality.evaluate(settings, rssi=-52, ping_ms=250.0, loss_pct=15.0)
    assert result["grade"] == quality.EXCELLENT  # the radio really is fine
    assert result["verdict"] == quality.FAIL  # but the network is not
    assert result["metrics"]["rssi"]["status"] == "ok"
    assert result["metrics"]["loss"]["status"] == "critical"


def test_weak_signal_warns(settings: AppSettings):
    result = quality.evaluate(settings, rssi=-70, ping_ms=5.0, loss_pct=0.0)
    assert result["verdict"] == quality.WARNING


def test_all_clear_passes(settings: AppSettings):
    result = quality.evaluate(settings, rssi=-50, ping_ms=4.0, loss_pct=0.0, jitter_ms=1.0)
    assert result["verdict"] == quality.PASS
    assert result["incomplete"] is False


def test_unmeasured_reachability_is_not_a_pass(settings: AppSettings):
    """A strong radio proves nothing about whether traffic flows."""
    result = quality.evaluate(settings, rssi=-40, ping_ms=None, loss_pct=None)
    assert result["incomplete"] is True
    assert result["verdict"] == quality.WARNING


def test_worst_verdict_precedence():
    assert quality.worst_verdict(["PASS", "WARNING", "FAIL"]) == "FAIL"
    assert quality.worst_verdict(["PASS", "WARNING"]) == "WARNING"
    assert quality.worst_verdict(["PASS", "PASS"]) == "PASS"
