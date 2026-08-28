"""Windows Wi-Fi backend built on ``netsh wlan``.

``netsh`` reports signal as a 0-100 percentage only, so dBm is reconstructed
with the standard linear mapping.  It is an approximation, and the UI labels it
as such rather than pretending to millidecibel accuracy.
"""

from __future__ import annotations

import re
import sys

from .base import (
    WifiAdapter,
    WifiLink,
    WifiNetwork,
    band_for_channel,
    channel_to_frequency,
    rssi_from_quality,
    run_cmd,
)

# netsh localises its labels; match on the value shape where we can.
_MAC_RE = re.compile(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})")


def _field(block: str, *names: str) -> str | None:
    """Pull ``Name : value`` out of a netsh block, trying several label spellings."""
    for name in names:
        match = re.search(rf"^\s*{re.escape(name)}\s*:\s*(.+?)\s*$", block, re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


def _int_field(block: str, *names: str) -> int | None:
    raw = _field(block, *names)
    if raw is None:
        return None
    match = re.search(r"-?\d+", raw)
    return int(match.group()) if match else None


class WindowsWifiAdapter(WifiAdapter):
    name = "windows"

    @staticmethod
    def is_available() -> bool:
        return sys.platform.startswith("win")

    # ---------------------------------------------------------------- link
    def get_link(self) -> WifiLink:
        out = run_cmd(["netsh", "wlan", "show", "interfaces"], 12.0)
        link = WifiLink(backend=self.name)
        if not out.strip():
            link.warnings.append("netsh returned no output; is the WLAN service running?")
            return link

        state = (_field(out, "State") or "").lower()
        link.interface = _field(out, "Name")
        link.connected = "connected" in state and "disconnected" not in state
        if not link.connected:
            return link

        link.ssid = _field(out, "SSID")
        bssid = _field(out, "BSSID", "AP BSSID")
        link.bssid = bssid.upper() if bssid else None
        link.security = _field(out, "Authentication")
        link.channel = _int_field(out, "Channel")

        quality = _int_field(out, "Signal")
        link.quality_pct = quality
        link.rssi = rssi_from_quality(quality)
        link.warnings.append("RSSI is derived from the Windows signal percentage")

        band = _field(out, "Band", "Radio type")
        link.band = self._normalise_band(band) or band_for_channel(link.channel)
        link.frequency_mhz = channel_to_frequency(link.channel, link.band)

        if (rate := _field(out, "Transmit rate (Mbps)", "Transmit rate")):
            link.tx_rate_mbps = _safe_float(rate)
        if (rate := _field(out, "Receive rate (Mbps)", "Receive rate")):
            link.rx_rate_mbps = _safe_float(rate)
        return link

    @staticmethod
    def _normalise_band(raw: str | None) -> str | None:
        if not raw:
            return None
        text = raw.replace(" ", "").lower()
        if text.startswith("2.4"):
            return "2.4 GHz"
        if text.startswith("5"):
            return "5 GHz"
        if text.startswith("6"):
            return "6 GHz"
        return None

    # ---------------------------------------------------------------- scan
    def scan(self) -> list[WifiNetwork]:
        out = run_cmd(["netsh", "wlan", "show", "networks", "mode=bssid"], 25.0)
        return self._parse_scan(out)

    def _parse_scan(self, out: str) -> list[WifiNetwork]:
        networks: list[WifiNetwork] = []
        # Each SSID block starts with "SSID N : name" and contains 1..n BSSID blocks.
        ssid_blocks = re.split(r"^SSID\s+\d+\s*:\s*", out, flags=re.MULTILINE)[1:]
        for block in ssid_blocks:
            lines = block.splitlines()
            ssid = lines[0].strip() if lines else None
            body = "\n".join(lines[1:])
            security = _field(body, "Authentication")

            bssid_chunks = re.split(r"^\s*BSSID\s+\d+\s*:\s*", body, flags=re.MULTILINE)[1:]
            if not bssid_chunks:
                networks.append(WifiNetwork(ssid=ssid or None, bssid=None, security=security))
                continue
            for chunk in bssid_chunks:
                mac_match = _MAC_RE.search(chunk)
                quality = _int_field(chunk, "Signal")
                channel = _int_field(chunk, "Channel")
                band = self._normalise_band(_field(chunk, "Band"))
                networks.append(
                    WifiNetwork(
                        ssid=ssid or None,
                        bssid=mac_match.group(1).upper() if mac_match else None,
                        rssi=rssi_from_quality(quality),
                        quality_pct=quality,
                        channel=channel,
                        band=band or band_for_channel(channel),
                        frequency_mhz=channel_to_frequency(channel, band),
                        security=security,
                    )
                )
        return networks


def _safe_float(raw: str) -> float | None:
    match = re.search(r"[\d.]+", raw)
    try:
        return float(match.group()) if match else None
    except ValueError:
        return None
