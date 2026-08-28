"""Band/channel maths and the parsers for each OS's scan output."""

from __future__ import annotations

import pytest
from backend.app.wifi.base import (
    band_for_channel,
    band_for_frequency,
    channel_to_frequency,
    quality_from_rssi,
    rssi_from_quality,
)
from backend.app.wifi.linux import LinuxWifiAdapter
from backend.app.wifi.mock import MockWifiAdapter
from backend.app.wifi.windows import WindowsWifiAdapter


@pytest.mark.parametrize(
    ("freq", "band"),
    [
        (2412, "2.4 GHz"),
        (2484, "2.4 GHz"),
        (5180, "5 GHz"),
        (5220, "5 GHz"),
        (5955, "6 GHz"),
        (6415, "6 GHz"),
        (None, None),
        (1000, None),
    ],
)
def test_band_for_frequency(freq, band):
    assert band_for_frequency(freq) == band


def test_frequency_wins_over_channel_because_channels_repeat():
    """Channel 1 exists at both 2.4 GHz and 6 GHz - only the frequency is unambiguous."""
    assert band_for_channel(1, 2412) == "2.4 GHz"
    assert band_for_channel(1, 5955) == "6 GHz"
    assert band_for_channel(1, None) == "2.4 GHz"  # documented fallback


def test_channel_to_frequency_round_trips():
    assert channel_to_frequency(1) == 2412
    assert channel_to_frequency(6) == 2437
    assert channel_to_frequency(14) == 2484
    assert channel_to_frequency(36) == 5180
    assert channel_to_frequency(44) == 5220
    assert channel_to_frequency(149) == 5745
    assert channel_to_frequency(1, "6 GHz") == 5955


def test_quality_and_rssi_are_inverses_at_the_anchors():
    assert quality_from_rssi(-90) == 0
    assert quality_from_rssi(-30) == 100
    assert quality_from_rssi(-60) == 50
    assert rssi_from_quality(0) == -90
    assert rssi_from_quality(100) == -30
    assert rssi_from_quality(50) == -60


def test_nmcli_scan_parsing_handles_escaped_colons_in_bssids():
    adapter = LinuxWifiAdapter()
    line = "yes:Factory-WiFi:AA\\:BB\\:CC\\:DD\\:EE\\:01:72:44:5220 MHz:WPA2:540 Mbit/s"
    networks = adapter._parse_nmcli_scan(line)

    assert len(networks) == 1
    net = networks[0]
    assert net.ssid == "Factory-WiFi"
    assert net.bssid == "AA:BB:CC:DD:EE:01"
    assert net.channel == 44
    assert net.frequency_mhz == 5220
    assert net.band == "5 GHz"
    assert net.quality_pct == 72
    assert net.rssi == rssi_from_quality(72)


def test_iw_scan_parsing():
    adapter = LinuxWifiAdapter()
    out = """BSS aa:bb:cc:dd:ee:01(on wlan0)
\tSSID: Factory-WiFi
\tsignal: -48.00 dBm
\tfreq: 5180
BSS aa:bb:cc:dd:ee:02(on wlan0)
\tSSID: Office-WiFi
\tsignal: -72.00 dBm
\tfreq: 2437
"""
    networks = adapter._parse_iw_scan(out)
    assert [n.bssid for n in networks] == ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]
    assert networks[0].rssi == -48
    assert networks[0].channel == 36
    assert networks[0].band == "5 GHz"
    assert networks[1].channel == 6
    assert networks[1].band == "2.4 GHz"


def test_netsh_scan_parsing_keeps_ssids_with_spaces():
    adapter = WindowsWifiAdapter()
    out = """Interface name : Wi-Fi
There are 2 networks currently visible.

SSID 1 : Factory WiFi
    Network type            : Infrastructure
    Authentication          : WPA2-Enterprise
    Encryption              : CCMP
    BSSID 1                 : aa:bb:cc:dd:ee:01
         Signal             : 90%
         Radio type         : 802.11ac
         Band               : 5 GHz
         Channel            : 44
    BSSID 2                 : aa:bb:cc:dd:ee:02
         Signal             : 60%
         Radio type         : 802.11ac
         Band               : 5 GHz
         Channel            : 36

SSID 2 : Guest-WiFi
    Network type            : Infrastructure
    Authentication          : Open
    Encryption              : None
    BSSID 1                 : 11:22:33:44:55:03
         Signal             : 40%
         Band               : 2.4 GHz
         Channel            : 11
"""
    networks = adapter._parse_scan(out)
    assert len(networks) == 3
    assert networks[0].ssid == "Factory WiFi"
    assert networks[0].bssid == "AA:BB:CC:DD:EE:01"
    assert networks[0].channel == 44
    assert networks[0].band == "5 GHz"
    assert networks[0].quality_pct == 90
    assert networks[0].rssi == rssi_from_quality(90)
    assert networks[2].ssid == "Guest-WiFi"
    assert networks[2].band == "2.4 GHz"


def test_mock_adapter_produces_a_usable_link():
    adapter = MockWifiAdapter()
    link = adapter.get_link()
    assert link.ssid == "Factory-WiFi"
    assert link.bssid is not None
    assert -95 < link.rssi < 0
    assert link.band in {"2.4 GHz", "5 GHz"}
    assert link.warnings, "simulated readings must say so"


def test_mock_adapter_scan_sees_more_than_the_joined_network():
    networks = MockWifiAdapter().scan()
    assert len(networks) >= 4
    assert {n.ssid for n in networks} > {"Factory-WiFi"}
    assert all(n.bssid for n in networks)
