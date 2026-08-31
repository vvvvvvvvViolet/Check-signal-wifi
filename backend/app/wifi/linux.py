"""Linux Wi-Fi backend.

Prefers NetworkManager (``nmcli``) because it reports signal, channel, security
and the active flag in one machine-readable line.  Falls back to ``iw`` for the
link state on systems that do not run NetworkManager.
"""

from __future__ import annotations

import re
import shutil

from .base import (
    WifiAdapter,
    WifiLink,
    WifiNetwork,
    band_for_channel,
    channel_to_frequency,
    quality_from_rssi,
    rssi_from_quality,
    run_cmd,
)

# nmcli escapes the field separator inside values as "\:" - split on unescaped ones.
_UNESCAPED_COLON = re.compile(r"(?<!\\):")


def _split_nmcli(line: str) -> list[str]:
    return [part.replace("\\:", ":").replace("\\\\", "\\") for part in _UNESCAPED_COLON.split(line)]


def _to_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


class LinuxWifiAdapter(WifiAdapter):
    name = "linux"

    _SCAN_FIELDS = "ACTIVE,SSID,BSSID,SIGNAL,CHAN,FREQ,SECURITY,RATE"

    @staticmethod
    def is_available() -> bool:
        return shutil.which("nmcli") is not None or shutil.which("iw") is not None

    # ---------------------------------------------------------------- scan
    def scan(self) -> list[WifiNetwork]:
        out = run_cmd(
            ["nmcli", "-t", "-f", self._SCAN_FIELDS, "device", "wifi", "list", "--rescan", "auto"],
            timeout=20.0,
        )
        if out.strip():
            return self._parse_nmcli_scan(out)
        return self._parse_iw_scan(run_cmd(["iw", "dev", self._iface() or "wlan0", "scan"], 25.0))

    def _parse_nmcli_scan(self, out: str) -> list[WifiNetwork]:
        networks: list[WifiNetwork] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = _split_nmcli(line)
            if len(parts) < 6:
                continue
            _active, ssid, bssid, signal, chan, freq = parts[:6]
            security = parts[6] if len(parts) > 6 else None
            # nmcli's SIGNAL is a 0-100 quality percentage, not dBm.
            quality = _to_int(signal)
            channel = _to_int(chan)
            freq_mhz = _to_int(freq.replace("MHz", "").strip()) if freq else None
            networks.append(
                WifiNetwork(
                    ssid=ssid or None,
                    bssid=(bssid or "").upper() or None,
                    rssi=rssi_from_quality(quality),
                    quality_pct=quality,
                    channel=channel,
                    frequency_mhz=freq_mhz or channel_to_frequency(channel),
                    band=band_for_channel(channel, freq_mhz),
                    security=security or None,
                )
            )
        return networks

    def _parse_iw_scan(self, out: str) -> list[WifiNetwork]:
        networks: list[WifiNetwork] = []
        current: dict = {}

        def flush() -> None:
            if not current.get("bssid"):
                return
            freq = current.get("freq")
            channel = current.get("channel")
            networks.append(
                WifiNetwork(
                    ssid=current.get("ssid"),
                    bssid=current["bssid"],
                    rssi=current.get("rssi"),
                    quality_pct=quality_from_rssi(current.get("rssi")),
                    channel=channel,
                    frequency_mhz=freq,
                    band=band_for_channel(channel, freq),
                    security=current.get("security"),
                )
            )

        for raw in out.splitlines():
            line = raw.strip()
            if line.startswith("BSS "):
                flush()
                current = {"bssid": line[4:].split("(")[0].strip().upper()}
            elif line.startswith("SSID:"):
                current["ssid"] = line[5:].strip() or None
            elif line.startswith("signal:"):
                current["rssi"] = int(round(float(line.split()[1])))
            elif line.startswith("freq:"):
                current["freq"] = _to_int(line.split(":", 1)[1])
            elif line.startswith("DS Parameter set: channel"):
                current["channel"] = _to_int(line.rsplit(" ", 1)[1])
            elif "RSN:" in line or "WPA:" in line:
                current["security"] = "WPA2" if "RSN" in line else "WPA"
        flush()
        for net in networks:
            if net.channel is None and net.frequency_mhz:
                net.channel = self._freq_to_channel(net.frequency_mhz)
        return networks

    @staticmethod
    def _freq_to_channel(freq: int) -> int | None:
        if freq == 2484:
            return 14
        if 2412 <= freq <= 2472:
            return (freq - 2407) // 5
        if 5160 <= freq <= 5885:
            return (freq - 5000) // 5
        if 5955 <= freq <= 7115:
            return (freq - 5955) // 5 + 1
        return None

    # ---------------------------------------------------------------- link
    def _iface(self) -> str | None:
        out = run_cmd(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"])
        for line in out.splitlines():
            parts = _split_nmcli(line)
            if len(parts) >= 3 and parts[1] == "wifi" and parts[2] == "connected":
                return parts[0]
        out = run_cmd(["iw", "dev"])
        match = re.search(r"Interface\s+(\S+)", out)
        return match.group(1) if match else None

    def get_link(self) -> WifiLink:
        link = WifiLink(backend=self.name, interface=self._iface())

        active = self._active_nmcli_row()
        if active is not None:
            link.connected = True
            link.ssid = active.ssid
            link.bssid = active.bssid
            link.rssi = active.rssi
            link.quality_pct = active.quality_pct
            link.channel = active.channel
            link.frequency_mhz = active.frequency_mhz
            link.band = active.band
            link.security = active.security

        self._enrich_from_iw(link)
        if link.rssi is not None and link.quality_pct is None:
            link.quality_pct = quality_from_rssi(link.rssi)
        link.ip_address = self._ip_address(link.interface)
        if not link.connected and link.bssid:
            link.connected = True
        return link

    def _active_nmcli_row(self) -> WifiNetwork | None:
        out = run_cmd(["nmcli", "-t", "-f", self._SCAN_FIELDS, "device", "wifi", "list"], 12.0)
        for line in out.splitlines():
            parts = _split_nmcli(line)
            if parts and parts[0] == "yes":
                parsed = self._parse_nmcli_scan(line)
                if parsed:
                    return parsed[0]
        return None

    def _enrich_from_iw(self, link: WifiLink) -> None:
        """`iw link` gives a true dBm reading and the negotiated PHY rates."""
        if not link.interface:
            return
        out = run_cmd(["iw", "dev", link.interface, "link"])
        if "Not connected" in out or not out.strip():
            return
        link.connected = True
        if (m := re.search(r"Connected to ([0-9a-fA-F:]{17})", out)):
            link.bssid = m.group(1).upper()
        if (m := re.search(r"SSID:\s*(.+)", out)):
            link.ssid = m.group(1).strip()
        if (m := re.search(r"signal:\s*(-?\d+)", out)):
            link.rssi = int(m.group(1))
            link.quality_pct = quality_from_rssi(link.rssi)
        if (m := re.search(r"freq:\s*(\d+)", out)):
            link.frequency_mhz = int(m.group(1))
            link.channel = self._freq_to_channel(link.frequency_mhz) or link.channel
            link.band = band_for_channel(link.channel, link.frequency_mhz)
        if (m := re.search(r"tx bitrate:\s*([\d.]+)", out)):
            link.tx_rate_mbps = float(m.group(1))
        if (m := re.search(r"rx bitrate:\s*([\d.]+)", out)):
            link.rx_rate_mbps = float(m.group(1))

    @staticmethod
    def _ip_address(iface: str | None) -> str | None:
        if not iface:
            return None
        out = run_cmd(["ip", "-4", "-o", "addr", "show", "dev", iface])
        match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", out)
        return match.group(1) if match else None
