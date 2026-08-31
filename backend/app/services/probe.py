"""One measurement tick.

The dashboard, the monitor loop, the heatmap capture and the history spot-check
all need the same thing: read the radio, probe the network, grade the result.
That lives here once so the four screens can never disagree with each other.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from ..config import AppSettings
from ..wifi import get_adapter
from . import net_test, quality


async def take_snapshot(
    settings: AppSettings,
    *,
    ping_count: int | None = None,
    include_dns: bool = True,
) -> dict:
    """Read the link and probe gateway / server / DNS concurrently."""
    count = ping_count or settings.monitor.ping_count
    timeout = settings.monitor.ping_timeout_sec

    link = await asyncio.to_thread(get_adapter().get_link)

    gateway_addr, gateway_auto = await asyncio.to_thread(
        net_test.resolve_gateway, settings.ping.gateway
    )

    targets: list[tuple[str, str | None]] = [
        ("gateway", gateway_addr),
        ("server", settings.ping.server),
    ]
    if include_dns:
        targets.append(("dns", settings.ping.dns))

    results = await asyncio.gather(
        *(
            net_test.ping_async(addr, count, timeout)
            if addr
            else _absent(name)
            for name, addr in targets
        )
    )
    pings = {name: result for (name, _addr), result in zip(targets, results, strict=False)}

    gw = pings.get("gateway")
    srv = pings.get("server")

    # The server probe is what a user experiences as "the network". Fall back to
    # the gateway only when the server probe was never *attempted* - falling back
    # because it failed would quietly hide the very failure worth reporting.
    primary = srv if (srv and srv.sent) else gw
    ping_ms = primary.rtt_avg_ms if primary else None
    loss_pct = primary.packet_loss_pct if primary else None
    jitter_ms = primary.jitter_ms if primary else None

    assessment = quality.evaluate(
        settings, rssi=link.rssi, ping_ms=ping_ms, loss_pct=loss_pct, jitter_ms=jitter_ms
    )

    return {
        "ts": datetime.now(UTC).isoformat(),
        "link": link.as_dict(),
        "gateway": {"address": gateway_addr, "auto_detected": gateway_auto},
        "ping": {name: result.as_dict() for name, result in pings.items()},
        "summary": {
            "ping_ms": ping_ms,
            "packet_loss_pct": loss_pct,
            "jitter_ms": jitter_ms,
            **assessment,
        },
    }


async def _absent(name: str) -> net_test.PingResult:
    """A probe that was never attempted - reported as unknown, not as failed."""
    result = net_test.PingResult(target="", sent=0, available=False)
    result.error = f"no {name} address available"
    return result


def snapshot_to_sample_kwargs(snapshot: dict) -> dict:
    """Flatten a snapshot into ``Sample`` column values."""
    link = snapshot["link"]
    summary = snapshot["summary"]
    pings = snapshot.get("ping", {})
    return {
        "ssid": link.get("ssid"),
        "bssid": link.get("bssid"),
        "channel": link.get("channel"),
        "band": link.get("band"),
        "frequency_mhz": link.get("frequency_mhz"),
        "rssi": link.get("rssi"),
        "quality_pct": link.get("quality_pct"),
        "noise_dbm": link.get("noise_dbm"),
        "tx_rate_mbps": link.get("tx_rate_mbps"),
        "rx_rate_mbps": link.get("rx_rate_mbps"),
        "ping_gateway_ms": (pings.get("gateway") or {}).get("rtt_avg_ms"),
        "ping_server_ms": (pings.get("server") or {}).get("rtt_avg_ms"),
        "ping_dns_ms": (pings.get("dns") or {}).get("rtt_avg_ms"),
        "jitter_ms": summary.get("jitter_ms"),
        "packet_loss_pct": summary.get("packet_loss_pct"),
        "grade": summary.get("grade"),
        "verdict": summary.get("verdict"),
    }


async def connectivity_chain(settings: AppSettings) -> dict:
    """The WiFi -> Gateway -> LAN -> DNS -> Internet ladder.

    Each rung is probed independently so a break can be located rather than
    just reported as "no internet". The first failing rung is the culprit;
    everything past it is reported as blocked, not as a second fault.
    """
    adapter = get_adapter()
    link = await asyncio.to_thread(adapter.get_link)
    gateway_addr, gateway_auto = await asyncio.to_thread(
        net_test.resolve_gateway, settings.ping.gateway
    )
    count = settings.monitor.ping_count
    timeout = settings.monitor.ping_timeout_sec

    gw_task = (
        net_test.ping_async(gateway_addr, count, timeout) if gateway_addr else _absent("gateway")
    )
    srv_task = net_test.ping_async(settings.ping.server, count, timeout)
    dns_ping_task = net_test.ping_async(settings.ping.dns, count, timeout)
    dns_task = asyncio.to_thread(net_test.dns_lookup, settings.ping.dns_hostname)
    inet_task = asyncio.to_thread(net_test.tcp_check, settings.ping.dns_hostname, 443)
    lan_ip_task = asyncio.to_thread(net_test.local_ip)

    gw, srv, dns_ping, dns, inet, lan_ip = await asyncio.gather(
        gw_task, srv_task, dns_ping_task, dns_task, inet_task, lan_ip_task
    )

    steps = [
        {
            "key": "wifi",
            "label": "WiFi",
            "ok": bool(link.connected and link.rssi is not None),
            "detail": f"{link.ssid or 'not associated'}"
            + (f" @ {link.rssi} dBm" if link.rssi is not None else ""),
            "latency_ms": None,
        },
        {
            "key": "gateway",
            "label": "Gateway",
            "ok": gw.reachable,
            "detail": gateway_addr or "not found",
            "latency_ms": gw.rtt_avg_ms,
        },
        {
            "key": "lan",
            "label": "LAN",
            "ok": bool(lan_ip),
            "detail": lan_ip or "no local IPv4 address",
            "latency_ms": None,
        },
        {
            "key": "dns",
            "label": "DNS",
            "ok": bool(dns["ok"]),
            "detail": (
                f"{settings.ping.dns_hostname} -> {', '.join(dns['addresses'][:2])}"
                if dns["ok"]
                else dns.get("error") or "resolution failed"
            ),
            "latency_ms": dns["elapsed_ms"],
        },
        {
            "key": "internet",
            "label": "Internet / Server",
            "ok": bool(inet["ok"] or srv.reachable),
            "detail": inet["error"] if not inet["ok"] else f"TCP 443 to {inet['host']}",
            "latency_ms": inet["elapsed_ms"] if inet["ok"] else srv.rtt_avg_ms,
        },
    ]

    # A rung that passed is reported as passing even if an earlier one failed -
    # ICMP to the gateway is often filtered while everything above it works, and
    # calling a working DNS lookup "blocked" would send the technician hunting a
    # fault that is not there. Only *failures* downstream of a failure are
    # attributed to it.
    first_failure = next((s["key"] for s in steps if not s["ok"]), None)
    seen_failure = False
    for step in steps:
        if step["ok"]:
            step["state"] = "ok"
        else:
            step["state"] = "blocked" if seen_failure else "failed"
            seen_failure = True

    return {
        "steps": steps,
        "broken_at": first_failure,
        "healthy": first_failure is None,
        "ping": {
            "gateway": gw.as_dict(),
            "server": srv.as_dict(),
            "dns": dns_ping.as_dict(),
        },
        "dns": dns,
        "internet": inet,
        "gateway_auto_detected": gateway_auto,
    }
