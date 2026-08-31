"""Cisco WLC parsing logic: table grouping, MAC decoding, and the
client-vs-controller comparison - all independent of whether the specific
AIRESPACE-WIRELESS-MIB column numbers turn out to match a real WLC 3504 (see
the ACCURACY NOTE in services/controller.py; this is what raw_walk() exists
to let someone verify against real hardware).
"""

from __future__ import annotations

import asyncio
from unittest import mock

from backend.app.config import ControllerConfig
from backend.app.services import controller as c
from backend.app.services import snmp


def test_group_by_index_assembles_a_row_from_scattered_columns():
    root = c._AP_TABLE
    rows = [
        (f"{root}.3.1", "AP-Factory-01"),
        (f"{root}.19.1", "10.0.0.11"),
        (f"{root}.6.1", 1),
        (f"{root}.3.2", "AP-Factory-02"),
    ]
    grouped = c._group_by_index(rows, root, c._AP_COLUMNS)
    assert grouped["1"] == {
        "name": "AP-Factory-01",
        "ip_address": "10.0.0.11",
        "operation_status": 1,
    }
    assert grouped["2"] == {"name": "AP-Factory-02"}


def test_group_by_index_ignores_columns_outside_the_map():
    root = c._AP_TABLE
    rows = [(f"{root}.3.1", "AP-01"), (f"{root}.9999.1", "unmapped column")]
    grouped = c._group_by_index(rows, root, c._AP_COLUMNS)
    assert grouped == {"1": {"name": "AP-01"}}


def test_group_by_index_handles_a_compound_radio_index():
    root = c._AP_IF_TABLE
    rows = [(f"{root}.4.1.0", 36), (f"{root}.4.1.1", 6), (f"{root}.4.2.0", 149)]
    grouped = c._group_by_index(rows, root, c._AP_IF_COLUMNS)
    assert set(grouped) == {"1.0", "1.1", "2.0"}
    assert grouped["1.0"]["channel"] == 36


def test_decimal_index_to_mac_with_snmp_length_prefix():
    """SNMP's table-index convention prefixes a MAC-keyed row with the byte
    count (6), which must be stripped before reading it as an address."""
    assert c._decimal_index_to_mac("6.170.187.204.221.238.1") == "AA:BB:CC:DD:EE:01"


def test_decimal_index_to_mac_without_length_prefix():
    assert c._decimal_index_to_mac("170.187.204.221.238.1") == "AA:BB:CC:DD:EE:01"


def test_decimal_index_to_mac_rejects_the_wrong_shape():
    assert c._decimal_index_to_mac("1.2.3") is None
    assert c._decimal_index_to_mac("not.numbers.here.at.all.nope") is None


def _config() -> ControllerConfig:
    return ControllerConfig(enabled=True, host="10.0.0.1", community="public")


def _walk_map(mapping: dict[str, list[tuple[str, object]]]):
    async def fake_walk(target, root_oid, max_rows=5000):
        return mapping.get(root_oid, [])

    return fake_walk


def test_list_access_points_attaches_each_radio_to_its_ap():
    config = _config()
    mapping = {
        c._AP_TABLE: [
            (f"{c._AP_TABLE}.3.1", "AP-Factory-01"),
            (f"{c._AP_TABLE}.19.1", "10.0.0.11"),
            (f"{c._AP_TABLE}.6.1", 1),
            (f"{c._AP_TABLE}.16.1", "AIR-AP1852I"),
        ],
        c._AP_IF_TABLE: [
            (f"{c._AP_IF_TABLE}.4.1.0", 36),
            (f"{c._AP_IF_TABLE}.39.1.0", 8),
            (f"{c._AP_IF_TABLE}.43.1.0", 42),
        ],
    }
    with mock.patch.object(snmp, "walk", side_effect=_walk_map(mapping)):
        aps = asyncio.run(c.list_access_points(config))

    assert len(aps) == 1
    ap = aps[0]
    assert ap.name == "AP-Factory-01"
    assert ap.operation_status == "up"
    assert ap.model == "AIR-AP1852I"
    assert len(ap.radios) == 1
    assert ap.radios[0].channel == 36
    assert ap.radios[0].client_count == 8
    assert ap.radios[0].channel_utilization_pct == 42


def test_list_access_points_reports_a_down_ap_with_missing_fields_as_none():
    """An AP the controller lost contact with may not report every column -
    that must come back as an honest None, not a crash or a fabricated 0."""
    config = _config()
    mapping = {c._AP_TABLE: [(f"{c._AP_TABLE}.6.1", 2)], c._AP_IF_TABLE: []}
    with mock.patch.object(snmp, "walk", side_effect=_walk_map(mapping)):
        aps = asyncio.run(c.list_access_points(config))

    assert aps[0].operation_status == "down"
    assert aps[0].name is None
    assert aps[0].radios == []


def test_list_access_points_skips_a_radio_for_an_ap_not_in_the_table():
    """A radio row for an AP index the AP table walk never returned must not
    crash the whole listing - it is simply dropped."""
    config = _config()
    mapping = {
        c._AP_TABLE: [(f"{c._AP_TABLE}.3.1", "AP-01")],
        c._AP_IF_TABLE: [(f"{c._AP_IF_TABLE}.4.99.0", 36)],  # AP index 99 does not exist
    }
    with mock.patch.object(snmp, "walk", side_effect=_walk_map(mapping)):
        aps = asyncio.run(c.list_access_points(config))
    assert len(aps) == 1
    assert aps[0].radios == []


def test_list_clients_decodes_mac_indexed_rows():
    config = _config()
    root = c._CLIENT_TABLE
    mapping = {
        root: [
            (f"{root}.20.6.170.187.204.221.238.1", -58),
            (f"{root}.5.6.170.187.204.221.238.1", "Factory-WiFi"),
            (f"{root}.2.6.170.187.204.221.238.1", "AA:BB:CC:DD:EE:02"),
        ]
    }
    with mock.patch.object(snmp, "walk", side_effect=_walk_map(mapping)):
        clients = asyncio.run(c.list_clients(config))

    assert len(clients) == 1
    client = clients[0]
    assert client.mac_address == "AA:BB:CC:DD:EE:01"
    assert client.rssi == -58
    assert client.ssid == "Factory-WiFi"
    assert client.ap_mac == "AA:BB:CC:DD:EE:02"


def test_check_reachable_reports_uptime_and_identity():
    config = _config()

    async def fake_get(target, *oids):
        return {
            c.OID_SYS_DESCR: "Cisco Controller",
            c.OID_SYS_UPTIME: 12000,  # centiseconds -> 120.0s
            c.OID_SYS_NAME: "WLC-3504-Main",
        }

    with mock.patch.object(snmp, "get", side_effect=fake_get):
        result = asyncio.run(c.check_reachable(config))

    assert result["reachable"] is True
    assert result["sys_name"] == "WLC-3504-Main"
    assert result["uptime_sec"] == 120.0


def test_check_reachable_reports_failure_without_raising():
    config = _config()
    with mock.patch.object(snmp, "get", side_effect=snmp.SnmpError("no response")):
        result = asyncio.run(c.check_reachable(config))
    assert result == {"reachable": False, "error": "no response"}


# --------------------------------------------------- client/controller compare
def _client(
    mac: str, ap_mac: str, rssi: int = -60, ssid: str = "Factory-WiFi"
) -> c.ClientStatus:
    return c.ClientStatus(
        mac_address=mac, ap_mac=ap_mac, ssid=ssid, rssi=rssi, snr=None, status="1"
    )


def test_compare_is_none_when_the_client_is_not_connected():
    result = c.compare_client_to_controller({"connected": False}, [])
    assert result["agrees"] is None


def test_compare_agrees_when_the_controller_has_a_matching_record():
    link = {"connected": True, "bssid": "aa:bb:cc:dd:ee:01"}
    clients = [_client("11:22:33:44:55:66", ap_mac="AA:BB:CC:DD:EE:01", rssi=-57)]
    result = c.compare_client_to_controller(link, clients)
    assert result["agrees"] is True
    assert result["controller_rssi"] == -57


def test_compare_disagrees_when_the_controller_has_no_matching_record():
    """The sticky-association case this check exists for: the client claims
    an AP the controller's client table does not back up."""
    link = {"connected": True, "bssid": "AA:BB:CC:DD:EE:99"}
    clients = [_client("11:22:33:44:55:66", ap_mac="AA:BB:CC:DD:EE:01")]
    result = c.compare_client_to_controller(link, clients)
    assert result["agrees"] is False
    assert "stale association" in result["reason"]


def test_compare_is_case_insensitive_on_mac_addresses():
    link = {"connected": True, "bssid": "aa:bb:cc:dd:ee:01"}
    clients = [_client("11:22:33:44:55:66", ap_mac="AA:BB:CC:DD:EE:01")]
    assert c.compare_client_to_controller(link, clients)["agrees"] is True
