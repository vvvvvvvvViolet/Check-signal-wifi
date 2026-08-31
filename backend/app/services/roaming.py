"""Detect AP transitions from a stream of link readings.

A "roam" is a BSSID change while the SSID stays the same. A change of SSID is a
different network, not a roam, and a drop to nothing and back is a
disconnect/reconnect - the two are reported distinctly because they mean very
different things to whoever is holding the scanner.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(slots=True)
class RoamObservation:
    ssid: str | None
    from_bssid: str | None
    to_bssid: str | None
    from_rssi: int | None
    to_rssi: int | None
    from_channel: int | None
    to_channel: int | None
    gap_ms: float | None
    kind: str  # roam | reconnect | network_change

    def as_dict(self) -> dict:
        return {
            "ssid": self.ssid,
            "from_bssid": self.from_bssid,
            "to_bssid": self.to_bssid,
            "from_rssi": self.from_rssi,
            "to_rssi": self.to_rssi,
            "from_channel": self.from_channel,
            "to_channel": self.to_channel,
            "gap_ms": round(self.gap_ms, 1) if self.gap_ms is not None else None,
            "kind": self.kind,
            "rssi_delta": (
                self.to_rssi - self.from_rssi
                if self.to_rssi is not None and self.from_rssi is not None
                else None
            ),
        }


class RoamDetector:
    """Feed it every link reading; it emits an observation only on a transition."""

    def __init__(self) -> None:
        self._bssid: str | None = None
        self._ssid: str | None = None
        self._rssi: int | None = None
        self._channel: int | None = None
        self._last_seen: float | None = None
        self._disconnected_since: float | None = None

    @property
    def current_bssid(self) -> str | None:
        return self._bssid

    def observe(self, link: dict) -> RoamObservation | None:
        now = time.monotonic()
        bssid = link.get("bssid")
        ssid = link.get("ssid")
        connected = bool(link.get("connected")) and bssid is not None

        if not connected:
            # Remember when the link dropped so the next association can report
            # a real outage duration instead of the poll interval.
            if self._disconnected_since is None:
                self._disconnected_since = now
            return None

        if self._bssid is None:
            self._adopt(bssid, ssid, link, now)
            self._disconnected_since = None
            return None

        if bssid == self._bssid:
            self._rssi = link.get("rssi")
            self._channel = link.get("channel")
            self._last_seen = now
            self._disconnected_since = None
            return None

        if self._disconnected_since is not None:
            gap_ms = (now - self._disconnected_since) * 1000
            kind = "reconnect"
        else:
            gap_ms = (now - self._last_seen) * 1000 if self._last_seen else None
            kind = "roam" if ssid == self._ssid else "network_change"

        observation = RoamObservation(
            ssid=ssid,
            from_bssid=self._bssid,
            to_bssid=bssid,
            from_rssi=self._rssi,
            to_rssi=link.get("rssi"),
            from_channel=self._channel,
            to_channel=link.get("channel"),
            gap_ms=gap_ms,
            kind=kind,
        )
        self._adopt(bssid, ssid, link, now)
        self._disconnected_since = None
        return observation

    def _adopt(self, bssid: str | None, ssid: str | None, link: dict, now: float) -> None:
        self._bssid = bssid
        self._ssid = ssid
        self._rssi = link.get("rssi")
        self._channel = link.get("channel")
        self._last_seen = now

    def reset(self) -> None:
        self.__init__()
