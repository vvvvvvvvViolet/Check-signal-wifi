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

        link.interface = _field(out, "Name")

        # `netsh` prints every field label in the OS display language. "State"
        # is a plain English word, so on a non-English Windows install it is
        # translated and never reads as "connected" - the client then looks
        # disconnected even while genuinely associated. "SSID" and "BSSID" are
        # protocol terms that Windows generally leaves untranslated, so try
        # them regardless of what the state check finds, and derive
        # `connected` from whether a BSSID was actually found rather than
        # trusting a status word whose language is not guaranteed.
        ssid = _field(out, "SSID")
        bssid_field = _field(out, "BSSID", "AP BSSID")
        bssid = bssid_field.upper() if bssid_field else None

        if bssid is None:
            # Labels can be translated too. "Physical address" (the client's
            # own NIC) has the same MAC shape as BSSID and is always present,
            # connected or not, so a lone match there must not be mistaken for
            # an association - BSSID is only printed when connected, and
            # always appears after Physical address. Two matches is what
            # proves a real BSSID was found; one is just the adapter's own MAC.
            mac_matches = list(_MAC_RE.finditer(out))
            if len(mac_matches) >= 2:
                bssid = mac_matches[-1].group(1).upper()
                if not ssid:
                    ssid = self._ssid_before_bssid(out, mac_matches[-1].group(1))

        state = (_field(out, "State") or "").lower()
        state_says_connected = "connected" in state and "disconnected" not in state
        link.connected = state_says_connected or bssid is not None
        if not link.connected:
            return link

        if not state_says_connected:
            link.warnings.append(
                "The 'State' field did not read as English 'connected' - this "
                "Windows install may use a non-English display language, so "
                "channel, band and rate may be missing"
            )

        link.ssid = ssid
        link.bssid = bssid
        link.security = _field(out, "Authentication")
        link.channel = _int_field(out, "Channel")

        quality = _int_field(out, "Signal")
        if quality is None:
            # "Signal" may be translated too; a bare percentage is the one
            # part of that line whose shape survives any language.
            percent_match = re.search(r"(\d{1,3})\s*%", out)
            quality = int(percent_match.group(1)) if percent_match else None
        link.quality_pct = quality
        link.rssi = rssi_from_quality(quality)
        if quality is not None:
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
    def _ssid_before_bssid(out: str, bssid_value: str) -> str | None:
        """Recover SSID by position on the rare install where its label is
        also translated. SSID's line is always the one immediately before
        BSSID's in every localisation of this output, so position stands in
        for a label match that has nothing else to go on.
        """
        lines = out.splitlines()
        idx = next((i for i, line in enumerate(lines) if bssid_value in line), None)
        if idx is None or idx == 0 or ":" not in lines[idx - 1]:
            return None
        candidate = lines[idx - 1].split(":", 1)[1].strip()
        return candidate or None

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
