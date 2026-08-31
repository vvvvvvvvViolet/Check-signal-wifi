"""Simulated Wi-Fi environment.

This is not a toy: it is what lets the UI, the roaming detector, the diagnosis
rules and the report writers be exercised on a CI runner, in a container, or on
a laptop with the radio switched off.  It models a small factory floor - a
client walking a loop past four APs - so RSSI decays with distance, the client
sticks to an AP until another is clearly better, and roams take a real gap.
"""

from __future__ import annotations

import math
import os
import random
import time

from .base import (
    WifiAdapter,
    WifiLink,
    WifiNetwork,
    band_for_channel,
    channel_to_frequency,
    quality_from_rssi,
)

# name, bssid, channel, x, y (metres on an imaginary 80 x 40 m floor), tx dBm
_ACCESS_POINTS = [
    ("Factory-WiFi", "AA:BB:CC:DD:EE:01", 36, 15.0, 10.0, -28),
    ("Factory-WiFi", "AA:BB:CC:DD:EE:02", 44, 60.0, 10.0, -28),
    ("Factory-WiFi", "AA:BB:CC:DD:EE:03", 149, 15.0, 32.0, -30),
    ("Factory-WiFi", "AA:BB:CC:DD:EE:04", 6, 60.0, 32.0, -30),
]
# Neighbouring networks that are visible but never joined.
_NEIGHBOURS = [
    ("Office-WiFi", "11:22:33:44:55:01", 6, 40.0, 55.0, -30),
    ("Office-WiFi", "11:22:33:44:55:02", 11, 70.0, 60.0, -30),
    ("Guest-WiFi", "11:22:33:44:55:03", 149, 5.0, 60.0, -32),
    ("Warehouse-IoT", "11:22:33:44:55:04", 1, 90.0, 20.0, -30),
]

# Free-space-ish path loss with an indoor exponent; factories are cluttered.
_PATH_LOSS_EXPONENT = 2.9
_REFERENCE_LOSS_DB = 40.0  # loss at 1 m
_HYSTERESIS_DB = 6.0  # how much better a neighbour must be before roaming
_ROAM_GAP_MS = 120.0


def _rssi_at(tx_dbm: float, distance_m: float) -> int:
    d = max(distance_m, 1.0)
    loss = _REFERENCE_LOSS_DB + 10 * _PATH_LOSS_EXPONENT * math.log10(d)
    return int(round(tx_dbm - loss + 40))  # +40 folds antenna gain into one constant


class MockWifiAdapter(WifiAdapter):
    """Deterministic-by-default simulator; set ``CSW_MOCK_SEED`` to pin the noise."""

    name = "mock"

    def __init__(self, period_sec: float = 90.0) -> None:
        self._period = period_sec
        self._t0 = time.monotonic()
        self._rng = random.Random(int(os.environ.get("CSW_MOCK_SEED", "1337")))
        self._current_bssid: str | None = None
        self._last_roam_at = 0.0

    @staticmethod
    def is_available() -> bool:
        return True

    # ------------------------------------------------------------ geometry
    def _client_position(self) -> tuple[float, float]:
        """Walk an oval loop around the floor so every AP takes a turn."""
        phase = ((time.monotonic() - self._t0) % self._period) / self._period
        angle = phase * 2 * math.pi
        return 37.5 + 28.0 * math.cos(angle), 21.0 + 14.0 * math.sin(angle)

    def _observed(self) -> list[tuple[tuple, int]]:
        x, y = self._client_position()
        seen = []
        for ap in (*_ACCESS_POINTS, *_NEIGHBOURS):
            _ssid, _bssid, _ch, ax, ay, tx = ap
            distance = math.hypot(ax - x, ay - y)
            rssi = _rssi_at(tx, distance) + self._rng.randint(-2, 2)
            if rssi >= -92:
                seen.append((ap, rssi))
        return sorted(seen, key=lambda item: item[1], reverse=True)

    # ---------------------------------------------------------------- link
    def get_link(self) -> WifiLink:
        candidates = [item for item in self._observed() if item[0][0] == "Factory-WiFi"]
        if not candidates:
            return WifiLink(backend=self.name, interface="mock0", connected=False)

        best_ap, best_rssi = candidates[0]
        held = next((c for c in candidates if c[0][1] == self._current_bssid), None)

        # Sticky client: only hand over when the alternative is clearly better.
        if held is None or best_rssi - held[1] > _HYSTERESIS_DB:
            if held is not None:
                self._last_roam_at = time.monotonic()
            chosen_ap, chosen_rssi = best_ap, best_rssi
            self._current_bssid = best_ap[1]
        else:
            chosen_ap, chosen_rssi = held

        ssid, bssid, channel, _ax, _ay, _tx = chosen_ap
        band = band_for_channel(channel)
        roaming_now = (time.monotonic() - self._last_roam_at) * 1000 < _ROAM_GAP_MS
        return WifiLink(
            connected=not roaming_now,
            interface="mock0",
            ssid=ssid,
            bssid=bssid,
            rssi=chosen_rssi,
            quality_pct=quality_from_rssi(chosen_rssi),
            noise_dbm=-95,
            channel=channel,
            band=band,
            frequency_mhz=channel_to_frequency(channel, band),
            tx_rate_mbps=self._phy_rate(chosen_rssi),
            rx_rate_mbps=self._phy_rate(chosen_rssi),
            security="WPA2-Enterprise",
            ip_address="10.20.30.44",
            backend=self.name,
            warnings=["Simulated data - no Wi-Fi hardware in use"],
        )

    @staticmethod
    def _phy_rate(rssi: int) -> float:
        """Rate adaptation: strong signal -> high MCS."""
        for floor, rate in ((-55, 866.7), (-62, 650.0), (-68, 400.0), (-74, 175.5), (-82, 72.2)):
            if rssi >= floor:
                return rate
        return 24.0

    # ---------------------------------------------------------------- scan
    def scan(self) -> list[WifiNetwork]:
        networks = []
        for ap, rssi in self._observed():
            ssid, bssid, channel, _ax, _ay, _tx = ap
            band = band_for_channel(channel)
            networks.append(
                WifiNetwork(
                    ssid=ssid,
                    bssid=bssid,
                    rssi=rssi,
                    quality_pct=quality_from_rssi(rssi),
                    channel=channel,
                    band=band,
                    frequency_mhz=channel_to_frequency(channel, band),
                    security="WPA2" if ssid != "Guest-WiFi" else "Open",
                )
            )
        return networks
