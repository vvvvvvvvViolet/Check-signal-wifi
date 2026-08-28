"""Rule-based auto diagnosis.

The point of this screen is to stop a technician mis-attributing a problem.
The two cases that matter most are the ones in the spec:

* weak signal + bad latency  -> a *coverage* problem, fix the RF
* strong signal + bad latency -> **not** an RF problem, look upstream

So the rules are written to key off the *combination*, and the strong-signal
case explicitly says the radio is fine so nobody goes and moves an AP for
nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import AppSettings
from . import quality

INFO = "info"
WARNING = "warning"
CRITICAL = "critical"

_SEVERITY_RANK = {CRITICAL: 0, WARNING: 1, INFO: 2}


@dataclass(slots=True)
class Finding:
    code: str
    severity: str
    title: str
    summary: str
    causes: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "summary": self.summary,
            "causes": self.causes,
            "recommendations": self.recommendations,
            "evidence": self.evidence,
        }


def diagnose(
    settings: AppSettings,
    *,
    rssi: int | None,
    ping_ms: float | None,
    loss_pct: float | None,
    jitter_ms: float | None = None,
    channel: int | None = None,
    band: str | None = None,
    connected: bool = True,
    scan: list[dict] | None = None,
    roam_count: int | None = None,
    window_minutes: int | None = None,
    roams: list[dict] | None = None,
) -> dict:
    """Return findings ordered worst-first, plus a one-line headline."""
    th = settings.thresholds
    findings: list[Finding] = []

    if not connected:
        findings.append(
            Finding(
                code="NOT_ASSOCIATED",
                severity=CRITICAL,
                title="Not connected to any WiFi network",
                summary="The client is not associated with an access point.",
                causes=[
                    "WiFi radio disabled or in airplane mode",
                    "Out of range of every configured SSID",
                    "Authentication or RADIUS failure",
                ],
                recommendations=[
                    "Confirm the WiFi adapter is enabled",
                    "Move within coverage of a known AP and retry",
                    "Check the supplicant / 802.1X credentials",
                ],
            )
        )
        return _wrap(findings, rssi, ping_ms, loss_pct)

    signal_weak = rssi is not None and rssi <= th.rssi_warning
    signal_critical = rssi is not None and rssi <= th.rssi_critical
    latency_bad = ping_ms is not None and ping_ms >= th.ping_warning_ms
    loss_bad = loss_pct is not None and loss_pct >= th.loss_warning_pct

    evidence = {
        "rssi_dbm": rssi,
        "ping_ms": ping_ms,
        "packet_loss_pct": loss_pct,
        "jitter_ms": jitter_ms,
        "channel": channel,
        "band": band,
    }

    # --- coverage --------------------------------------------------------
    if signal_weak:
        findings.append(
            Finding(
                code="WEAK_COVERAGE",
                severity=CRITICAL if signal_critical else WARNING,
                title="WiFi quality issue detected",
                summary=(
                    f"Signal is {rssi} dBm, at or below the "
                    f"{'critical' if signal_critical else 'warning'} threshold "
                    f"({th.rssi_critical if signal_critical else th.rssi_warning} dBm)."
                ),
                causes=[
                    "Weak WiFi coverage at this location",
                    "Client is far from the nearest access point",
                    "Obstruction between client and AP (racks, machinery, metal walls)",
                ],
                recommendations=[
                    "Check the nearest AP and its distance from this point",
                    "Check AP transmit power and antenna orientation",
                    "Perform a measurement sweep around this location",
                    "Consider an additional AP if the weak area is large",
                ],
                evidence=evidence,
            )
        )

    # --- upstream, with a healthy radio ----------------------------------
    if not signal_weak and (latency_bad or loss_bad):
        findings.append(
            Finding(
                code="UPSTREAM_DEGRADED",
                severity=CRITICAL
                if (ping_ms or 0) >= th.ping_critical_ms or (loss_pct or 0) >= th.loss_critical_pct
                else WARNING,
                title="Signal is good but the network is slow",
                summary=(
                    f"Signal strength is {quality.grade_rssi(rssi, settings.bands).title()} "
                    f"({rssi} dBm), so this is not a coverage problem."
                ),
                causes=[
                    "Network congestion or channel contention",
                    "Upstream / WAN issue beyond the access point",
                    "Overloaded AP (too many clients on one radio)",
                    "QoS or rate limiting on the wired side",
                ],
                recommendations=[
                    "Compare gateway latency with server latency to locate the hop",
                    "Check client count and airtime utilisation on this AP",
                    "Run the Network Test to isolate LAN / DNS / Internet",
                    "Escalate to the network team if the gateway itself is slow",
                ],
                evidence=evidence,
            )
        )

    # --- both bad --------------------------------------------------------
    if signal_weak and (latency_bad or loss_bad):
        findings.append(
            Finding(
                code="RETRANSMISSION",
                severity=WARNING,
                title="Latency and loss consistent with retransmissions",
                summary=(
                    "Weak signal together with latency/loss usually means frames are "
                    "being retried at the radio layer rather than dropped upstream."
                ),
                causes=[
                    "Low SNR forcing a low MCS and frequent retries",
                    "Sticky client holding a distant AP",
                ],
                recommendations=[
                    "Fix coverage first, then re-measure before investigating the LAN",
                    "Check whether the client should have roamed to a closer AP",
                ],
                evidence=evidence,
            )
        )

    # --- jitter ----------------------------------------------------------
    if jitter_ms is not None and jitter_ms >= th.jitter_warning_ms:
        findings.append(
            Finding(
                code="HIGH_JITTER",
                severity=WARNING,
                title="Unstable latency (high jitter)",
                summary=f"Latency varies by {jitter_ms:.1f} ms between probes.",
                causes=[
                    "Airtime contention with other clients",
                    "Power-save mode on the client adapter",
                    "Interference from non-WiFi sources",
                ],
                recommendations=[
                    "Disable adapter power saving for latency-sensitive devices",
                    "Check for interference sources near this location",
                ],
                evidence=evidence,
            )
        )

    findings.extend(_rf_environment_findings(scan or [], channel, band, rssi))

    findings.extend(_roaming_findings(settings, roams or []))

    if roam_count is not None and window_minutes and roam_count >= 4:
        findings.append(
            Finding(
                code="EXCESSIVE_ROAMING",
                severity=WARNING,
                title="Excessive roaming",
                summary=f"{roam_count} roams in {window_minutes} minutes.",
                causes=[
                    "Overlapping AP coverage with similar signal levels",
                    "AP transmit power set too high, blurring cell edges",
                ],
                recommendations=[
                    "Reduce AP transmit power to sharpen cell boundaries",
                    "Review the roaming thresholds on the client or controller",
                ],
                evidence={"roam_count": roam_count, "window_minutes": window_minutes},
            )
        )

    if not findings:
        findings.append(
            Finding(
                code="HEALTHY",
                severity=INFO,
                title="Network healthy",
                summary="Signal, latency and packet loss are all within thresholds.",
                evidence=evidence,
            )
        )

    return _wrap(findings, rssi, ping_ms, loss_pct)


def _roaming_findings(settings: AppSettings, roams: list[dict]) -> list[Finding]:
    """The two failure modes of roaming that are not "roams too often".

    A sticky client is the classic warehouse fault: a barcode scanner on a
    forklift holds its original AP well past the point of usefulness, then drops
    the session mid-scan. It shows up in a survey as a *late* hand-off - the
    signal on the AP being left was already at critical level - and it is
    invisible to any check that only looks at the current RSSI, because by the
    time you look the client has already moved on.

    A slow hand-off is the other half: the roam happened, but the gap was long
    enough for the session on top of it to time out.
    """
    th = settings.thresholds
    findings: list[Finding] = []

    # Only true roams count. A reconnect already had an outage, and a network
    # change is the user switching SSID - neither is a sticky client.
    true_roams = [r for r in roams if r.get("kind", "roam") == "roam"]

    late = [
        r
        for r in true_roams
        if r.get("from_rssi") is not None and r["from_rssi"] <= th.rssi_critical
    ]
    if late:
        worst = min(late, key=lambda r: r["from_rssi"])
        findings.append(
            Finding(
                code="STICKY_CLIENT",
                severity=WARNING,
                title="Client roams too late (sticky client)",
                summary=(
                    f"{len(late)} of {len(true_roams)} hand-offs happened only after the "
                    f"signal had fallen to {worst['from_rssi']} dBm, at or below the "
                    f"critical threshold ({th.rssi_critical} dBm). The client held a "
                    f"distant access point instead of moving to a closer one."
                ),
                causes=[
                    "Client roaming threshold set too low (common on handheld scanners)",
                    "No better AP was available at the point the signal degraded",
                    "AP transmit power too high, so a distant cell still looks acceptable",
                    "802.11r/k/v assistance not enabled on the controller",
                ],
                recommendations=[
                    "Raise the roaming aggressiveness on the client adapter or MDM profile",
                    "Check the Heatmap for coverage gaps along this route",
                    "Reduce AP transmit power to sharpen cell edges",
                    "Enable 802.11k/v so the AP can steer the client earlier",
                ],
                evidence={
                    "late_roams": len(late),
                    "total_roams": len(true_roams),
                    "worst_handoff_rssi_dbm": worst["from_rssi"],
                    "from_bssid": worst.get("from_bssid"),
                    "to_bssid": worst.get("to_bssid"),
                },
            )
        )

    slow = [
        r
        for r in true_roams
        if r.get("gap_ms") is not None and r["gap_ms"] >= th.roam_gap_warning_ms
    ]
    if slow:
        worst_gap = max(slow, key=lambda r: r["gap_ms"])
        findings.append(
            Finding(
                code="SLOW_ROAM",
                severity=WARNING,
                title="Hand-off takes long enough to break sessions",
                summary=(
                    f"{len(slow)} hand-off(s) took at least "
                    f"{th.roam_gap_warning_ms:.0f} ms, the longest "
                    f"{worst_gap['gap_ms']:.0f} ms. Scanner and voice sessions time out "
                    f"across a gap this long."
                ),
                causes=[
                    "Full re-authentication on every roam (no PMK caching)",
                    "802.11r fast transition not enabled",
                    "Slow RADIUS response during re-authentication",
                    "Client scanning all channels before selecting a target",
                ],
                recommendations=[
                    "Enable 802.11r fast transition or OKC on the WLAN",
                    "Check RADIUS response time for this SSID",
                    "Restrict the client's scan list to the channels actually in use",
                ],
                evidence={
                    "slow_roams": len(slow),
                    "total_roams": len(true_roams),
                    "worst_gap_ms": round(worst_gap["gap_ms"], 1),
                },
            )
        )

    return findings


def _rf_environment_findings(
    scan: list[dict], channel: int | None, band: str | None, rssi: int | None
) -> list[Finding]:
    """Co-channel contention and 2.4 GHz channel-plan checks."""
    findings: list[Finding] = []
    if not scan or channel is None:
        return findings

    # Only count neighbours strong enough to actually steal airtime.
    co_channel = [
        net
        for net in scan
        if net.get("channel") == channel
        and net.get("rssi") is not None
        and net["rssi"] >= -82
        and (rssi is None or net.get("bssid"))
    ]
    if len(co_channel) >= 3:
        findings.append(
            Finding(
                code="CO_CHANNEL_CONTENTION",
                severity=WARNING,
                title=f"{len(co_channel)} radios sharing channel {channel}",
                summary=(
                    "Neighbouring radios on the same channel share airtime with this link, "
                    "which shows up as latency rather than weak signal."
                ),
                causes=["Too many APs on one channel", "Channel reuse distance too small"],
                recommendations=[
                    "Review the channel plan for this area",
                    "Enable or re-run automatic channel selection on the controller",
                ],
                evidence={
                    "channel": channel,
                    "count": len(co_channel),
                    "bssids": [n.get("bssid") for n in co_channel[:8]],
                },
            )
        )

    if band and band.startswith("2.4") and channel not in (1, 6, 11):
        findings.append(
            Finding(
                code="NON_STANDARD_24_CHANNEL",
                severity=INFO,
                title=f"2.4 GHz channel {channel} overlaps its neighbours",
                summary="Only channels 1, 6 and 11 are non-overlapping at 2.4 GHz.",
                causes=["Manual channel assignment", "Automatic selection without a constraint"],
                recommendations=["Move this radio to channel 1, 6 or 11"],
                evidence={"channel": channel, "band": band},
            )
        )
    return findings


def _wrap(findings: list[Finding], rssi, ping_ms, loss_pct) -> dict:
    findings.sort(key=lambda f: _SEVERITY_RANK.get(f.severity, 9))
    severity = findings[0].severity if findings else INFO
    return {
        "severity": severity,
        "headline": findings[0].title if findings else "Network healthy",
        "measurements": {"rssi_dbm": rssi, "ping_ms": ping_ms, "packet_loss_pct": loss_pct},
        "findings": [f.as_dict() for f in findings],
    }
