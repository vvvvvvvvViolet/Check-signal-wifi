"""Reachability probes: ping, default-gateway discovery, DNS, and the
WiFi -> Gateway -> LAN -> DNS -> Internet chain the Network Test screen draws.

Everything here shells out to the platform ``ping`` rather than opening raw
sockets, because raw ICMP needs root/CAP_NET_RAW and a survey tool has to run
as an ordinary user.
"""

from __future__ import annotations

import asyncio
import ipaddress
import itertools
import platform
import re
import shutil
import socket
import statistics
import subprocess
import time
from dataclasses import dataclass, field

from ..wifi.base import run_cmd

IS_WINDOWS = platform.system().lower().startswith("win")


@dataclass(slots=True)
class PingResult:
    """Outcome of one ping run.

    ``available`` separates "the network dropped every packet" (loss = 100)
    from "this host has no ping binary" (loss = ``None``). Conflating the two
    would have the dashboard report a healthy network as failing.
    """

    target: str
    reachable: bool = False
    available: bool = True
    sent: int = 0
    received: int = 0
    packet_loss_pct: float | None = None
    rtt_min_ms: float | None = None
    rtt_avg_ms: float | None = None
    rtt_max_ms: float | None = None
    jitter_ms: float | None = None
    error: str | None = None
    rtts: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = {
            "target": self.target,
            "reachable": self.reachable,
            "available": self.available,
            "sent": self.sent,
            "received": self.received,
            "packet_loss_pct": _r(self.packet_loss_pct),
            "rtt_min_ms": _r(self.rtt_min_ms),
            "rtt_avg_ms": _r(self.rtt_avg_ms),
            "rtt_max_ms": _r(self.rtt_max_ms),
            "jitter_ms": _r(self.jitter_ms),
            "error": self.error,
        }
        return data


def _r(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


# Per-reply RTT, e.g. "time=1.23 ms" (POSIX) or "time<1ms" / "time=3ms" (Windows).
_RTT_RE = re.compile(r"time[=<]\s*([\d.]+)\s*ms", re.IGNORECASE)


def _ping_command(target: str, count: int, timeout_sec: float) -> list[str]:
    if IS_WINDOWS:
        # -w takes milliseconds and applies per reply.
        return ["ping", "-n", str(count), "-w", str(int(timeout_sec * 1000)), target]
    if platform.system() == "Darwin":
        # macOS -W is milliseconds; -t bounds the whole run.
        return ["ping", "-c", str(count), "-W", str(int(timeout_sec * 1000)), target]
    # iputils: -W is seconds (per reply), -i sets the send interval.
    return ["ping", "-c", str(count), "-W", str(max(1, int(timeout_sec))), "-i", "0.25", target]


def ping(target: str, count: int = 4, timeout_sec: float = 1.0) -> PingResult:
    """Send ``count`` echo requests and summarise the replies."""
    result = PingResult(target=target, sent=count)
    if not target:
        result.available = False
        result.sent = 0
        result.error = "no target configured"
        return result

    command = _ping_command(target, count, timeout_sec)
    if shutil.which(command[0]) is None:
        result.available = False
        result.sent = 0
        result.error = f"{command[0]} is not installed on this host"
        return result

    # A generous ceiling: the per-reply timeout times the count, plus slack.
    overall = timeout_sec * count + 5.0
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=overall,
            check=False,
            errors="replace",
        )
        output = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        # It ran and returned nothing in time - that is a real 100% loss.
        result.packet_loss_pct = 100.0
        result.error = "timeout"
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        result.available = False
        result.sent = 0
        result.error = f"ping unavailable: {exc}"
        return result

    rtts = [float(m) for m in _RTT_RE.findall(output)]
    result.rtts = rtts
    result.received = len(rtts)

    # Prefer the OS's own loss figure; it counts duplicates and errors properly.
    loss_match = re.search(r"([\d.]+)%\s*(?:packet\s*)?loss", output, re.IGNORECASE)
    if loss_match:
        result.packet_loss_pct = float(loss_match.group(1))
    elif count:
        result.packet_loss_pct = round(100.0 * (count - len(rtts)) / count, 2)

    if rtts:
        result.reachable = True
        result.rtt_min_ms = min(rtts)
        result.rtt_max_ms = max(rtts)
        result.rtt_avg_ms = sum(rtts) / len(rtts)
        # Jitter as mean absolute successive difference (RFC 3550 in spirit).
        if len(rtts) > 1:
            diffs = [abs(b - a) for a, b in itertools.pairwise(rtts)]
            result.jitter_ms = statistics.fmean(diffs)
        else:
            result.jitter_ms = 0.0
    elif not result.error:
        result.error = "no reply"
    return result


async def ping_async(target: str, count: int = 4, timeout_sec: float = 1.0) -> PingResult:
    """Run :func:`ping` off the event loop so probes can overlap."""
    return await asyncio.to_thread(ping, target, count, timeout_sec)


# --------------------------------------------------------------- discovery
def default_gateway() -> str | None:
    """Find the default gateway without assuming a specific tool exists."""
    if IS_WINDOWS:
        out = run_cmd(["route", "print", "-4"], 10.0)
        match = re.search(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", out, re.MULTILINE)
        if match:
            return match.group(1)
        out = run_cmd(["ipconfig"], 10.0)
        match = re.search(r"Default Gateway[^\n:]*:\s*(\d+\.\d+\.\d+\.\d+)", out)
        return match.group(1) if match else None

    out = run_cmd(["ip", "route", "show", "default"], 6.0)
    if (match := re.search(r"default\s+via\s+(\d+\.\d+\.\d+\.\d+)", out)):
        return match.group(1)

    out = run_cmd(["netstat", "-rn"], 8.0)
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] in ("default", "0.0.0.0") and len(parts) > 1:
            try:
                ipaddress.IPv4Address(parts[1])
                return parts[1]
            except ipaddress.AddressValueError:
                continue
    return None


def resolve_gateway(configured: str | None) -> tuple[str | None, bool]:
    """Return ``(address, was_auto_detected)``."""
    if configured and configured.strip().lower() != "auto":
        return configured.strip(), False
    return default_gateway(), True


def local_ip() -> str | None:
    """The address this host would use to reach the outside world."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # no packets are sent for UDP connect
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def dns_lookup(hostname: str, timeout_sec: float = 3.0) -> dict:
    """Time a real resolution, which is what users actually feel."""
    original = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_sec)
    started = time.perf_counter()
    try:
        infos = socket.getaddrinfo(hostname, None, family=socket.AF_UNSPEC)
        elapsed = (time.perf_counter() - started) * 1000
        addresses = sorted({info[4][0] for info in infos})
        return {
            "hostname": hostname,
            "ok": True,
            "elapsed_ms": round(elapsed, 2),
            "addresses": addresses[:5],
            "error": None,
        }
    except (socket.gaierror, OSError) as exc:
        return {
            "hostname": hostname,
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "addresses": [],
            "error": str(exc),
        }
    finally:
        socket.setdefaulttimeout(original)


def tcp_check(host: str, port: int = 443, timeout_sec: float = 3.0) -> dict:
    """TCP connect test - proves the path works where ICMP may be filtered."""
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return {
                "host": host,
                "port": port,
                "ok": True,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "error": None,
            }
    except OSError as exc:
        return {
            "host": host,
            "port": port,
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": str(exc),
        }


def traceroute(target: str, max_hops: int = 12, timeout_sec: float = 25.0) -> list[dict]:
    """Best-effort path trace; returns ``[]`` when no tracer is installed."""
    cmd = (
        ["tracert", "-d", "-h", str(max_hops), target]
        if IS_WINDOWS
        else ["traceroute", "-n", "-m", str(max_hops), "-w", "2", target]
    )
    out = run_cmd(cmd, timeout_sec)
    hops: list[dict] = []
    for line in out.splitlines():
        match = re.match(r"\s*(\d+)\s+(.*)", line)
        if not match:
            continue
        rest = match.group(2)
        ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", rest)
        rtt_values = [float(v) for v in re.findall(r"([\d.]+)\s*ms", rest)]
        hops.append(
            {
                "hop": int(match.group(1)),
                "address": ip_match.group(1) if ip_match else None,
                "rtt_ms": round(statistics.fmean(rtt_values), 2) if rtt_values else None,
                "timeout": "*" in rest and not rtt_values,
            }
        )
    return hops
