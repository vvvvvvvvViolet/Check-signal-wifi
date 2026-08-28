"""Ping output parsing, and the missing-tool case that must not read as loss."""

from __future__ import annotations

from unittest import mock

from backend.app.services import net_test

LINUX_OUTPUT = """PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.
64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.10 ms
64 bytes from 10.0.0.1: icmp_seq=2 ttl=64 time=3.10 ms
64 bytes from 10.0.0.1: icmp_seq=3 ttl=64 time=2.10 ms
64 bytes from 10.0.0.1: icmp_seq=4 ttl=64 time=4.10 ms

--- 10.0.0.1 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 3005ms
rtt min/avg/max/mdev = 1.100/2.600/4.100/1.118 ms
"""

WINDOWS_OUTPUT = """
Pinging 10.0.0.1 with 32 bytes of data:
Reply from 10.0.0.1: bytes=32 time=2ms TTL=64
Reply from 10.0.0.1: bytes=32 time=4ms TTL=64

Ping statistics for 10.0.0.1:
    Packets: Sent = 4, Received = 2, Lost = 2 (50% loss),
"""

UNREACHABLE_OUTPUT = """PING 10.0.0.9 (10.0.0.9) 56(84) bytes of data.

--- 10.0.0.9 ping statistics ---
4 packets transmitted, 0 received, 100% packet loss, time 3070ms
"""


def _run_ping(output: str, **kwargs):
    completed = mock.Mock(stdout=output, stderr="")
    with mock.patch.object(net_test.shutil, "which", return_value="/bin/ping"), mock.patch.object(
        net_test.subprocess, "run", return_value=completed
    ):
        return net_test.ping("10.0.0.1", **kwargs)


def test_parses_posix_ping():
    result = _run_ping(LINUX_OUTPUT)
    assert result.reachable is True
    assert result.available is True
    assert result.received == 4
    assert result.packet_loss_pct == 0.0
    assert result.rtt_min_ms == 1.10
    assert result.rtt_max_ms == 4.10
    assert result.rtt_avg_ms == 2.60
    # Mean absolute successive difference of 1.1, 3.1, 2.1, 4.1 -> (2+1+2)/3
    assert round(result.jitter_ms, 3) == round(5 / 3, 3)


def test_prefers_the_os_reported_loss_figure():
    result = _run_ping(WINDOWS_OUTPUT)
    assert result.packet_loss_pct == 50.0
    assert result.received == 2
    assert result.reachable is True


def test_total_loss_is_reported_as_a_failure():
    result = _run_ping(UNREACHABLE_OUTPUT)
    assert result.reachable is False
    assert result.available is True
    assert result.packet_loss_pct == 100.0
    assert result.error == "no reply"


def test_missing_ping_binary_is_unknown_not_total_loss():
    """The distinction the dashboard depends on to avoid crying wolf."""
    with mock.patch.object(net_test.shutil, "which", return_value=None):
        result = net_test.ping("10.0.0.1")
    assert result.available is False
    assert result.packet_loss_pct is None
    assert result.sent == 0
    assert "not installed" in result.error


def test_empty_target_is_rejected_without_running_anything():
    result = net_test.ping("")
    assert result.available is False
    assert result.packet_loss_pct is None
    assert result.error == "no target configured"


def test_subprocess_timeout_counts_as_total_loss():
    with mock.patch.object(net_test.shutil, "which", return_value="/bin/ping"), mock.patch.object(
        net_test.subprocess,
        "run",
        side_effect=net_test.subprocess.TimeoutExpired(cmd="ping", timeout=1),
    ):
        result = net_test.ping("10.0.0.1")
    assert result.available is True
    assert result.packet_loss_pct == 100.0
    assert result.error == "timeout"


def test_resolve_gateway_passes_through_an_explicit_address():
    assert net_test.resolve_gateway("192.168.1.1") == ("192.168.1.1", False)


def test_resolve_gateway_auto_detects():
    with mock.patch.object(net_test, "default_gateway", return_value="10.0.0.1"):
        assert net_test.resolve_gateway("auto") == ("10.0.0.1", True)
        assert net_test.resolve_gateway(None) == ("10.0.0.1", True)
