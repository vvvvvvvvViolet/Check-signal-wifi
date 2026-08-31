"""Adapter contract shared by every OS-specific Wi-Fi backend."""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class WifiNetwork:
    """One BSSID seen during a scan."""

    ssid: str | None
    bssid: str | None
    rssi: int | None = None
    channel: int | None = None
    band: str | None = None
    frequency_mhz: int | None = None
    security: str | None = None
    quality_pct: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class WifiLink:
    """The association the client currently holds (if any)."""

    connected: bool = False
    interface: str | None = None
    ssid: str | None = None
    bssid: str | None = None
    rssi: int | None = None
    quality_pct: int | None = None
    noise_dbm: int | None = None
    channel: int | None = None
    band: str | None = None
    frequency_mhz: int | None = None
    tx_rate_mbps: float | None = None
    rx_rate_mbps: float | None = None
    security: str | None = None
    ip_address: str | None = None
    backend: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def band_for_frequency(freq_mhz: int | None) -> str | None:
    """Map a centre frequency to the marketing band name."""
    if not freq_mhz:
        return None
    if 2400 <= freq_mhz <= 2500:
        return "2.4 GHz"
    if 4900 <= freq_mhz <= 5900:
        return "5 GHz"
    if 5925 <= freq_mhz <= 7125:
        return "6 GHz"
    if 57000 <= freq_mhz <= 71000:
        return "60 GHz"
    return None


def channel_to_frequency(channel: int | None, band_hint: str | None = None) -> int | None:
    """Best-effort channel -> frequency.

    Channel numbers repeat across bands (channel 1 exists at 2.4 GHz and at
    6 GHz), so ``band_hint`` decides when the number alone is ambiguous.
    """
    if channel is None:
        return None
    if band_hint and band_hint.startswith("6"):
        return 5955 + (channel - 1) * 5
    if 1 <= channel <= 13:
        return 2407 + channel * 5
    if channel == 14:
        return 2484
    if 32 <= channel <= 68:
        return 5000 + channel * 5
    if 96 <= channel <= 177:
        return 5000 + channel * 5
    return None


def band_for_channel(channel: int | None, freq_mhz: int | None = None) -> str | None:
    """Derive the band, preferring frequency because it is unambiguous."""
    from_freq = band_for_frequency(freq_mhz)
    if from_freq:
        return from_freq
    if channel is None:
        return None
    if 1 <= channel <= 14:
        return "2.4 GHz"
    if 32 <= channel <= 177:
        return "5 GHz"
    return None


def quality_from_rssi(rssi: int | None) -> int | None:
    """Linear 0-100 mapping of -90..-30 dBm, the convention `netsh` uses."""
    if rssi is None:
        return None
    pct = round((rssi + 90) * 100 / 60)
    return max(0, min(100, pct))


def rssi_from_quality(quality_pct: int | None) -> int | None:
    """Inverse of :func:`quality_from_rssi`, for backends that only report %."""
    if quality_pct is None:
        return None
    return round(quality_pct * 60 / 100) - 90


def run_cmd(args: list[str], timeout: float = 8.0) -> str:
    """Run a helper binary and return stdout, or ``""`` when unavailable.

    Every Wi-Fi backend shells out to a vendor tool, and every one of those
    tools is missing on some machine.  Failing soft here keeps the adapter
    reporting "not connected" instead of crashing the API.
    """
    if not args:
        return ""
    if shutil.which(args[0]) is None:
        return ""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            errors="replace",
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    return proc.stdout or ""


class WifiAdapter(ABC):
    """What every backend must be able to answer."""

    name: str = "base"

    @abstractmethod
    def get_link(self) -> WifiLink:
        """State of the current association."""

    @abstractmethod
    def scan(self) -> list[WifiNetwork]:
        """All BSSIDs currently visible."""

    @staticmethod
    def is_available() -> bool:
        return False
