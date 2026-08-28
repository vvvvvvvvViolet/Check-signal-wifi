"""The rules exist to stop a technician fixing the wrong layer."""

from __future__ import annotations

from backend.app.config import AppSettings
from backend.app.services import diagnosis


def codes(report: dict) -> set[str]:
    return {f["code"] for f in report["findings"]}


def test_weak_signal_is_diagnosed_as_coverage(settings: AppSettings):
    report = diagnosis.diagnose(settings, rssi=-76, ping_ms=85.0, loss_pct=6.0)
    assert "WEAK_COVERAGE" in codes(report)
    assert report["severity"] == "critical"

    finding = next(f for f in report["findings"] if f["code"] == "WEAK_COVERAGE")
    assert any("far from" in cause.lower() for cause in finding["causes"])
    assert any("nearest ap" in rec.lower() for rec in finding["recommendations"])


def test_strong_signal_with_bad_latency_points_upstream(settings: AppSettings):
    """The spec's second example: -52 dBm, 250 ms, 15% loss."""
    report = diagnosis.diagnose(settings, rssi=-52, ping_ms=250.0, loss_pct=15.0)

    assert "UPSTREAM_DEGRADED" in codes(report)
    assert "WEAK_COVERAGE" not in codes(report), "must not blame coverage on a strong signal"

    finding = next(f for f in report["findings"] if f["code"] == "UPSTREAM_DEGRADED")
    assert "not a coverage problem" in finding["summary"].lower()
    assert any("congestion" in c.lower() for c in finding["causes"])


def test_healthy_network_reports_nothing_to_fix(settings: AppSettings):
    report = diagnosis.diagnose(settings, rssi=-52, ping_ms=3.0, loss_pct=0.0)
    assert codes(report) == {"HEALTHY"}
    assert report["severity"] == "info"


def test_disconnected_short_circuits(settings: AppSettings):
    report = diagnosis.diagnose(
        settings, rssi=None, ping_ms=None, loss_pct=None, connected=False
    )
    assert codes(report) == {"NOT_ASSOCIATED"}
    assert report["severity"] == "critical"


def test_weak_signal_and_loss_also_flags_retransmission(settings: AppSettings):
    report = diagnosis.diagnose(settings, rssi=-78, ping_ms=90.0, loss_pct=7.0)
    assert {"WEAK_COVERAGE", "RETRANSMISSION"} <= codes(report)


def test_co_channel_contention_is_detected(settings: AppSettings):
    scan = [
        {"bssid": f"AA:BB:CC:00:00:0{i}", "channel": 6, "rssi": -70} for i in range(1, 5)
    ]
    report = diagnosis.diagnose(
        settings, rssi=-58, ping_ms=5.0, loss_pct=0.0, channel=6, band="2.4 GHz", scan=scan
    )
    assert "CO_CHANNEL_CONTENTION" in codes(report)


def test_weak_neighbours_do_not_count_as_contention(settings: AppSettings):
    scan = [
        {"bssid": f"AA:BB:CC:00:00:0{i}", "channel": 6, "rssi": -90} for i in range(1, 6)
    ]
    report = diagnosis.diagnose(
        settings, rssi=-58, ping_ms=5.0, loss_pct=0.0, channel=6, band="2.4 GHz", scan=scan
    )
    assert "CO_CHANNEL_CONTENTION" not in codes(report)


def test_overlapping_24ghz_channel_is_flagged(settings: AppSettings):
    report = diagnosis.diagnose(
        settings, rssi=-58, ping_ms=4.0, loss_pct=0.0, channel=3, band="2.4 GHz", scan=[{}]
    )
    assert "NON_STANDARD_24_CHANNEL" in codes(report)


def test_standard_24ghz_channel_is_not_flagged(settings: AppSettings):
    for channel in (1, 6, 11):
        report = diagnosis.diagnose(
            settings,
            rssi=-58,
            ping_ms=4.0,
            loss_pct=0.0,
            channel=channel,
            band="2.4 GHz",
            scan=[{}],
        )
        assert "NON_STANDARD_24_CHANNEL" not in codes(report)


def test_excessive_roaming_is_flagged(settings: AppSettings):
    report = diagnosis.diagnose(
        settings, rssi=-58, ping_ms=4.0, loss_pct=0.0, roam_count=9, window_minutes=15
    )
    assert "EXCESSIVE_ROAMING" in codes(report)


def test_findings_are_ordered_worst_first(settings: AppSettings):
    report = diagnosis.diagnose(
        settings, rssi=-80, ping_ms=200.0, loss_pct=9.0, jitter_ms=60.0
    )
    severities = [f["severity"] for f in report["findings"]]
    rank = {"critical": 0, "warning": 1, "info": 2}
    assert severities == sorted(severities, key=lambda s: rank[s])
