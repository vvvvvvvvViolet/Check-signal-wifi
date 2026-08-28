"""macOS Wi-Fi backend.

Apple removed the scan/-I output from the old ``airport`` binary in Sonoma, so
this tries ``airport`` first (still present and useful on older systems) and
falls back to ``wdutil`` / ``system_profiler`` for the link state.
"""

from __future__ import annotations

import plistlib
import re
import subprocess
import sys

from .base import (
    WifiAdapter,
    WifiLink,
    WifiNetwork,
    band_for_channel,
    channel_to_frequency,
    quality_from_rssi,
    run_cmd,
)

AIRPORT = (
    "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
)


class MacWifiAdapter(WifiAdapter):
    name = "macos"

    @staticmethod
    def is_available() -> bool:
        return sys.platform == "darwin"

    # ---------------------------------------------------------------- link
    def get_link(self) -> WifiLink:
        link = WifiLink(backend=self.name, interface=self._iface())
        out = self._airport(["-I"])
        if out.strip():
            self._parse_airport_info(out, link)
        if not link.connected:
            self._parse_system_profiler(link)
        if link.rssi is not None and link.quality_pct is None:
            link.quality_pct = quality_from_rssi(link.rssi)
        return link

    def _parse_airport_info(self, out: str, link: WifiLink) -> None:
        values = {}
        for line in out.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                values[key.strip()] = value.strip()
        if values.get("AirPort") == "Off":
            link.warnings.append("Wi-Fi radio is off")
            return
        link.ssid = values.get("SSID")
        bssid = values.get("BSSID")
        link.bssid = bssid.upper() if bssid else None
        link.rssi = _int(values.get("agrCtlRSSI"))
        link.noise_dbm = _int(values.get("agrCtlNoise"))
        link.channel = _int((values.get("channel") or "").split(",")[0])
        link.band = band_for_channel(link.channel)
        link.frequency_mhz = channel_to_frequency(link.channel, link.band)
        link.tx_rate_mbps = _float(values.get("lastTxRate"))
        link.security = values.get("link auth")
        link.connected = bool(link.ssid or link.bssid)

    def _parse_system_profiler(self, link: WifiLink) -> None:
        """Sonoma+ fallback. Note: the BSSID is redacted without Location access."""
        try:
            raw = subprocess.run(
                ["system_profiler", "-xml", "SPAirPortDataType"],
                capture_output=True,
                timeout=20.0,
                check=False,
            ).stdout
            data = plistlib.loads(raw) if raw else []
        except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, ValueError):
            return

        for item in _walk(data):
            if not isinstance(item, dict) or "spairport_current_network_information" not in item:
                continue
            current = item["spairport_current_network_information"]
            link.connected = True
            link.ssid = current.get("_name")
            link.bssid = (current.get("spairport_network_bssid") or "").upper() or None
            link.rssi = _int(current.get("spairport_signal_noise"))
            link.channel = _int(current.get("spairport_network_channel"))
            link.band = band_for_channel(link.channel)
            link.frequency_mhz = channel_to_frequency(link.channel, link.band)
            if link.bssid is None:
                link.warnings.append(
                    "macOS hides the BSSID unless the app has Location Services permission"
                )
            return

    # ---------------------------------------------------------------- scan
    def scan(self) -> list[WifiNetwork]:
        out = self._airport(["-s"])
        if not out.strip():
            return []
        return self._parse_airport_scan(out)

    def _parse_airport_scan(self, out: str) -> list[WifiNetwork]:
        networks: list[WifiNetwork] = []
        lines = out.splitlines()
        if not lines:
            return networks
        # Columns: SSID BSSID RSSI CHANNEL HT CC SECURITY. SSIDs may contain
        # spaces, so anchor on the MAC address instead of splitting naively.
        pattern = re.compile(
            r"^\s*(?P<ssid>.*?)\s+(?P<bssid>[0-9a-fA-F:]{17})\s+(?P<rssi>-?\d+)\s+"
            r"(?P<channel>[\d,+-]+)\s+\S+\s+\S+\s+(?P<security>.*)$"
        )
        for line in lines[1:]:
            match = pattern.match(line)
            if not match:
                continue
            channel = _int(match.group("channel").split(",")[0])
            rssi = int(match.group("rssi"))
            networks.append(
                WifiNetwork(
                    ssid=match.group("ssid").strip() or None,
                    bssid=match.group("bssid").upper(),
                    rssi=rssi,
                    quality_pct=quality_from_rssi(rssi),
                    channel=channel,
                    band=band_for_channel(channel),
                    frequency_mhz=channel_to_frequency(channel),
                    security=match.group("security").strip() or None,
                )
            )
        return networks

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _airport(args: list[str]) -> str:
        try:
            proc = subprocess.run(
                [AIRPORT, *args], capture_output=True, text=True, timeout=25.0, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return proc.stdout or ""

    @staticmethod
    def _iface() -> str | None:
        out = run_cmd(["networksetup", "-listallhardwareports"])
        match = re.search(r"Hardware Port: Wi-Fi\s*\nDevice:\s*(\S+)", out)
        return match.group(1) if match else "en0"


def _walk(node):
    """Yield every nested dict/list element of a system_profiler plist."""
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, list | dict):
                yield from _walk(value)


def _int(value) -> int | None:
    try:
        match = re.search(r"-?\d+", str(value))
        return int(match.group()) if match else None
    except (TypeError, ValueError):
        return None


def _float(value) -> float | None:
    try:
        match = re.search(r"-?[\d.]+", str(value))
        return float(match.group()) if match else None
    except (TypeError, ValueError):
        return None
