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


# --------------------------------------------------------------- roaming
def roam(from_rssi=-58, to_rssi=-55, gap_ms=80.0, kind="roam"):
    return {
        "from_bssid": "AA:BB:CC:00:00:01",
        "to_bssid": "AA:BB:CC:00:00:02",
        "from_rssi": from_rssi,
        "to_rssi": to_rssi,
        "gap_ms": gap_ms,
        "kind": kind,
    }


def test_sticky_client_is_detected_from_a_late_handoff(settings: AppSettings):
    """The forklift-scanner fault: held the old AP down to -82 before moving."""
    report = diagnosis.diagnose(
        settings,
        rssi=-55,  # healthy *now* - the fault is only visible in the roam history
        ping_ms=4.0,
        loss_pct=0.0,
        roams=[roam(from_rssi=-82, to_rssi=-54)],
    )
    assert "STICKY_CLIENT" in codes(report)

    finding = next(f for f in report["findings"] if f["code"] == "STICKY_CLIENT")
    assert finding["evidence"]["worst_handoff_rssi_dbm"] == -82
    assert any("roaming" in rec.lower() for rec in finding["recommendations"])


def test_a_healthy_handoff_is_not_flagged(settings: AppSettings):
    report = diagnosis.diagnose(
        settings, rssi=-55, ping_ms=4.0, loss_pct=0.0, roams=[roam(from_rssi=-68)]
    )
    assert "STICKY_CLIENT" not in codes(report)
    assert "SLOW_ROAM" not in codes(report)


def test_a_reconnect_is_not_counted_as_a_sticky_roam(settings: AppSettings):
    """A reconnect already involved an outage; it is a different fault."""
    report = diagnosis.diagnose(
        settings,
        rssi=-55,
        ping_ms=4.0,
        loss_pct=0.0,
        roams=[roam(from_rssi=-85, gap_ms=4000.0, kind="reconnect")],
    )
    assert "STICKY_CLIENT" not in codes(report)
    assert "SLOW_ROAM" not in codes(report)


def test_slow_handoff_is_flagged(settings: AppSettings):
    report = diagnosis.diagnose(
        settings, rssi=-55, ping_ms=4.0, loss_pct=0.0, roams=[roam(gap_ms=1800.0)]
    )
    assert "SLOW_ROAM" in codes(report)
    finding = next(f for f in report["findings"] if f["code"] == "SLOW_ROAM")
    assert finding["evidence"]["worst_gap_ms"] == 1800.0


def test_fast_handoff_is_not_flagged(settings: AppSettings):
    report = diagnosis.diagnose(
        settings, rssi=-55, ping_ms=4.0, loss_pct=0.0, roams=[roam(gap_ms=60.0)]
    )
    assert "SLOW_ROAM" not in codes(report)


def test_sticky_and_slow_are_independent(settings: AppSettings):
    report = diagnosis.diagnose(
        settings,
        rssi=-55,
        ping_ms=4.0,
        loss_pct=0.0,
        roams=[roam(from_rssi=-80, gap_ms=2000.0)],
    )
    assert {"STICKY_CLIENT", "SLOW_ROAM"} <= codes(report)


def test_roams_with_missing_data_are_skipped_not_crashed(settings: AppSettings):
    report = diagnosis.diagnose(
        settings,
        rssi=-55,
        ping_ms=4.0,
        loss_pct=0.0,
        roams=[{"kind": "roam"}, {"from_rssi": None, "gap_ms": None, "kind": "roam"}],
    )
    assert "STICKY_CLIENT" not in codes(report)
    assert "SLOW_ROAM" not in codes(report)


# --------------------------------------------------------- controller check
def test_controller_mismatch_is_flagged(settings: AppSettings):
    report = diagnosis.diagnose(
        settings,
        rssi=-55,
        ping_ms=4.0,
        loss_pct=0.0,
        controller_check={
            "agrees": False,
            "reason": "The controller has no client record on this AP.",
            "client_bssid": "AA:BB:CC:DD:EE:01",
            "controller_ap_mac": None,
        },
    )
    assert "CONTROLLER_CLIENT_MISMATCH" in codes(report)


def test_controller_agreement_is_not_a_finding(settings: AppSettings):
    """Agreement is the healthy case - it should stay silent, not add noise."""
    report = diagnosis.diagnose(
        settings,
        rssi=-55,
        ping_ms=4.0,
        loss_pct=0.0,
        controller_check={
            "agrees": True,
            "reason": "ok",
            "client_bssid": "x",
            "controller_ap_mac": "x",
        },
    )
    assert "CONTROLLER_CLIENT_MISMATCH" not in codes(report)


def test_controller_check_unavailable_is_not_a_finding(settings: AppSettings):
    """agrees=None means the check could not run (not connected, WLC
    unreachable) - silence, not a manufactured finding, is correct here."""
    report = diagnosis.diagnose(
        settings,
        rssi=-55,
        ping_ms=4.0,
        loss_pct=0.0,
        controller_check={"agrees": None, "reason": "not connected"},
    )
    assert "CONTROLLER_CLIENT_MISMATCH" not in codes(report)


def test_no_controller_check_at_all_is_not_a_finding(settings: AppSettings):
    """The common case: no WLC configured. Must not appear as if it failed."""
    report = diagnosis.diagnose(settings, rssi=-55, ping_ms=4.0, loss_pct=0.0)
    assert "CONTROLLER_CLIENT_MISMATCH" not in codes(report)
