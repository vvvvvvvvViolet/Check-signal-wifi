"""A roam, a network change and a reconnect must not be confused."""

from __future__ import annotations

from backend.app.services.roaming import RoamDetector


def link(bssid, ssid="Factory-WiFi", rssi=-60, channel=44, connected=True):
    return {
        "bssid": bssid,
        "ssid": ssid,
        "rssi": rssi,
        "channel": channel,
        "connected": connected,
    }


def test_first_observation_is_not_a_roam():
    detector = RoamDetector()
    assert detector.observe(link("AA:BB:CC:00:00:01")) is None
    assert detector.current_bssid == "AA:BB:CC:00:00:01"


def test_staying_on_the_same_ap_emits_nothing():
    detector = RoamDetector()
    detector.observe(link("AA:BB:CC:00:00:01", rssi=-58))
    for rssi in (-60, -65, -71):
        assert detector.observe(link("AA:BB:CC:00:00:01", rssi=rssi)) is None


def test_bssid_change_on_the_same_ssid_is_a_roam():
    detector = RoamDetector()
    detector.observe(link("AA:BB:CC:00:00:01", rssi=-71, channel=36))
    event = detector.observe(link("AA:BB:CC:00:00:02", rssi=-55, channel=44))

    assert event is not None
    data = event.as_dict()
    assert data["kind"] == "roam"
    assert data["from_bssid"] == "AA:BB:CC:00:00:01"
    assert data["to_bssid"] == "AA:BB:CC:00:00:02"
    assert data["from_rssi"] == -71
    assert data["to_rssi"] == -55
    assert data["rssi_delta"] == 16
    assert data["from_channel"] == 36
    assert data["to_channel"] == 44


def test_ssid_change_is_not_reported_as_a_roam():
    detector = RoamDetector()
    detector.observe(link("AA:BB:CC:00:00:01", ssid="Factory-WiFi"))
    event = detector.observe(link("11:22:33:44:55:01", ssid="Office-WiFi"))
    assert event is not None
    assert event.kind == "network_change"


def test_drop_and_return_to_a_new_ap_is_a_reconnect():
    detector = RoamDetector()
    detector.observe(link("AA:BB:CC:00:00:01"))
    assert detector.observe(link(None, connected=False)) is None
    event = detector.observe(link("AA:BB:CC:00:00:02"))
    assert event is not None
    assert event.kind == "reconnect"
    assert event.gap_ms is not None


def test_reset_clears_state():
    detector = RoamDetector()
    detector.observe(link("AA:BB:CC:00:00:01"))
    detector.reset()
    assert detector.current_bssid is None
    assert detector.observe(link("AA:BB:CC:00:00:02")) is None
