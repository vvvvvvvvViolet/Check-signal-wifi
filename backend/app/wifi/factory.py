"""Pick the right Wi-Fi backend for this machine (once, and cache it)."""

from __future__ import annotations

import logging
import sys
from functools import lru_cache

from ..config import WIFI_BACKEND
from .base import WifiAdapter
from .linux import LinuxWifiAdapter
from .macos import MacWifiAdapter
from .mock import MockWifiAdapter
from .windows import WindowsWifiAdapter

log = logging.getLogger(__name__)

_BY_NAME: dict[str, type[WifiAdapter]] = {
    "linux": LinuxWifiAdapter,
    "windows": WindowsWifiAdapter,
    "macos": MacWifiAdapter,
    "mock": MockWifiAdapter,
}


def _auto_select() -> WifiAdapter:
    if sys.platform.startswith("win") and WindowsWifiAdapter.is_available():
        return WindowsWifiAdapter()
    if sys.platform == "darwin" and MacWifiAdapter.is_available():
        return MacWifiAdapter()
    if sys.platform.startswith("linux") and LinuxWifiAdapter.is_available():
        return LinuxWifiAdapter()
    log.warning(
        "No native Wi-Fi tooling found (nmcli/iw/netsh/airport); "
        "falling back to the simulator. Set CSW_WIFI_BACKEND to override."
    )
    return MockWifiAdapter()


@lru_cache(maxsize=1)
def get_adapter() -> WifiAdapter:
    if WIFI_BACKEND != "auto":
        cls = _BY_NAME.get(WIFI_BACKEND)
        if cls is None:
            raise ValueError(
                f"Unknown CSW_WIFI_BACKEND={WIFI_BACKEND!r}; "
                f"expected one of auto, {', '.join(sorted(_BY_NAME))}"
            )
        return cls()
    return _auto_select()


def reset_adapter_cache() -> None:
    get_adapter.cache_clear()
