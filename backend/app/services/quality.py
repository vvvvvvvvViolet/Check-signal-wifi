"""Turning raw numbers into the words the UI shows.

Two separate judgements, deliberately not merged:

``grade``   - how good the *radio* is, on the four-step scale the gauge draws.
``verdict`` - whether this measurement should worry anyone, which also weighs
              latency and loss and is what History shows as PASS/WARNING/FAIL.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import AppSettings, SignalBands, Thresholds

EXCELLENT = "EXCELLENT"
GOOD = "GOOD"
FAIR = "FAIR"
POOR = "POOR"
UNKNOWN = "UNKNOWN"

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"

GRADE_ORDER = [EXCELLENT, GOOD, FAIR, POOR, UNKNOWN]
GRADE_COLOR = {
    EXCELLENT: "#16a34a",
    GOOD: "#4ade80",
    FAIR: "#facc15",
    POOR: "#ef4444",
    UNKNOWN: "#94a3b8",
}
VERDICT_ORDER = [PASS, WARNING, FAIL]


def grade_rssi(rssi: int | None, bands: SignalBands | None = None) -> str:
    """Excellent >= -55, Good -56..-65, Fair -66..-72, Poor below that."""
    if rssi is None:
        return UNKNOWN
    bands = bands or SignalBands()
    if rssi >= bands.excellent:
        return EXCELLENT
    if rssi >= bands.good:
        return GOOD
    if rssi >= bands.fair:
        return FAIR
    return POOR


def signal_percent(rssi: int | None, floor: int = -90, ceiling: int = -30) -> int:
    """0-100 for the gauge arc. Clamped, so a -20 dBm reading still means 100."""
    if rssi is None:
        return 0
    span = ceiling - floor
    return max(0, min(100, round((rssi - floor) * 100 / span)))


@dataclass(slots=True)
class MetricStatus:
    """One metric's standing against its thresholds."""

    value: float | int | None
    status: str  # ok | warning | critical | unknown
    label: str


def _status_low_is_good(
    value: float | None, warn: float, crit: float, label: str
) -> MetricStatus:
    """For metrics where bigger is worse (latency, loss, jitter)."""
    if value is None:
        return MetricStatus(None, "unknown", label)
    if value >= crit:
        return MetricStatus(value, "critical", label)
    if value >= warn:
        return MetricStatus(value, "warning", label)
    return MetricStatus(value, "ok", label)


def rssi_status(rssi: int | None, th: Thresholds) -> MetricStatus:
    """For RSSI, bigger (closer to zero) is better, so the comparison flips."""
    if rssi is None:
        return MetricStatus(None, "unknown", "Signal")
    if rssi <= th.rssi_critical:
        return MetricStatus(rssi, "critical", "Signal")
    if rssi <= th.rssi_warning:
        return MetricStatus(rssi, "warning", "Signal")
    return MetricStatus(rssi, "ok", "Signal")


def evaluate(
    settings: AppSettings,
    *,
    rssi: int | None = None,
    ping_ms: float | None = None,
    loss_pct: float | None = None,
    jitter_ms: float | None = None,
) -> dict:
    """Grade a measurement and roll the worst metric up into a verdict."""
    th = settings.thresholds
    metrics = {
        "rssi": rssi_status(rssi, th),
        "ping": _status_low_is_good(ping_ms, th.ping_warning_ms, th.ping_critical_ms, "Latency"),
        "loss": _status_low_is_good(
            loss_pct, th.loss_warning_pct, th.loss_critical_pct, "Packet loss"
        ),
        "jitter": _status_low_is_good(
            jitter_ms, th.jitter_warning_ms, th.jitter_warning_ms * 3, "Jitter"
        ),
    }
    statuses = {m.status for m in metrics.values()}
    # Reachability was never established if neither latency nor loss is known,
    # so PASS would be an unearned claim - a good radio proves nothing about
    # whether traffic actually flows.
    incomplete = metrics["ping"].status == "unknown" and metrics["loss"].status == "unknown"

    if "critical" in statuses:
        verdict = FAIL
    elif "warning" in statuses or incomplete:
        verdict = WARNING
    else:
        verdict = PASS

    grade = grade_rssi(rssi, settings.bands)
    return {
        "grade": grade,
        "grade_color": GRADE_COLOR[grade],
        "signal_percent": signal_percent(rssi),
        "verdict": verdict,
        "incomplete": incomplete,
        "metrics": {
            key: {"value": m.value, "status": m.status, "label": m.label}
            for key, m in metrics.items()
        },
    }


def worst_verdict(verdicts: list[str]) -> str:
    """FAIL beats WARNING beats PASS."""
    for candidate in (FAIL, WARNING):
        if candidate in verdicts:
            return candidate
    return PASS if verdicts else WARNING
