"""Cisco AireOS WLC (e.g. WLC 3504) monitoring over SNMP.

This is the client-side survey's blind spot filled in from the other end: the
rest of the app infers roaming and mesh health from what one laptop's radio
sees. This module asks the controller directly - every AP it manages, each
radio's channel and load, and (per AP) which client MACs it currently holds and
at what RSSI - so a survey can cross-check what the client believes against
what the network believes.

Honesty policy, same as everywhere else in this app: a column this device does
not expose comes back as ``None``, never a manufactured zero, and a genuinely
unreachable controller is reported as exactly that rather than as "no APs
found". See ``ACCURACY NOTE`` below before trusting a specific OID column.

ACCURACY NOTE
-------------
The table layout below (AIRESPACE-WIRELESS-MIB, enterprise OID 14179 - Cisco
kept Airespace's original MIB after acquiring them) is well-established and
used by most third-party WLC monitoring tools, but the exact OID for a given
column was written from documentation, not confirmed against a live WLC 3504 -
this codebase has never had one to test against. ``raw_walk()`` and the
``/api/controller/raw`` endpoint exist specifically to verify or correct these
against a real device: point it at the AP or radio table root and compare the
returned columns to what shows in the WLC's own web UI or a `show ap summary`.
Treat the constants below as the first draft, not a confirmed fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import ControllerConfig
from . import snmp

# ---- MIB-II (RFC 1213) - standardised, not Cisco-specific, no uncertainty here.
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"

# ---- AIRESPACE-WIRELESS-MIB (see ACCURACY NOTE above).
_AIRESPACE_ROOT = "1.3.6.1.4.1.14179"

# bsnAPTable: one row per access point the controller manages.
_AP_TABLE = f"{_AIRESPACE_ROOT}.2.2.1.1"
_AP_COLUMNS = {
    "name": 3,  # bsnAPName
    "ip_address": 19,  # bsnAPIpAddress
    "operation_status": 6,  # bsnAPOperationStatus: 1=associated, 2=disassociated (typical)
    "model": 16,  # bsnAPModel
    "mac_address": 2,  # bsnAPDot3MacAddress
    "location": 4,  # bsnAPLocation
}

# bsnAPIfTable: one row per radio (2.4/5 GHz) on each AP.
_AP_IF_TABLE = f"{_AIRESPACE_ROOT}.2.2.2.1"
_AP_IF_COLUMNS = {
    "channel": 4,  # bsnAPIfPhyChannelNumber
    "operation_status": 6,  # bsnApIfOperStatus: 1=up, 2=down (typical)
    "tx_power_level": 8,  # bsnAPIfPhyTxPowerLevel
    "client_count": 39,  # bsnAPIfNoOfUsers
    "channel_utilization": 43,  # bsnAPIfLoadChannelUtilization (%)
}

# bsnMobileStationTable: one row per client currently associated anywhere.
_CLIENT_TABLE = f"{_AIRESPACE_ROOT}.2.1.4.1"
_CLIENT_COLUMNS = {
    "ap_mac": 2,  # bsnMobileStationAPMacAddr
    "status": 4,  # bsnMobileStationStatus
    "ssid": 5,  # bsnMobileStationSsid
    "rssi": 20,  # bsnMobileStationRSSI (dBm)
    "snr": 21,  # bsnMobileStationSnr (dB)
}

OPERATION_STATUS_LABELS = {1: "up", 2: "down"}


def to_snmp_target(config: ControllerConfig) -> snmp.SnmpTarget:
    """``ControllerConfig`` is the persisted, validated shape (see config.py);
    this is the transport-level shape ``services/snmp.py`` actually needs.
    Kept as a plain function rather than a method so config.py never has to
    import a services module."""
    return snmp.SnmpTarget(
        host=config.host,
        port=config.port,
        version=config.version,
        community=config.community,
        v3_user=config.v3_user or None,
        v3_auth_password=config.v3_auth_password or None,
        v3_priv_password=config.v3_priv_password or None,
        timeout_sec=config.timeout_sec,
    )


@dataclass(slots=True)
class RadioStatus:
    ap_index: str
    radio_index: str
    channel: int | None
    operation_status: str | None
    tx_power_level: int | None
    client_count: int | None
    channel_utilization_pct: int | None


@dataclass(slots=True)
class AccessPointStatus:
    index: str
    name: str | None
    ip_address: str | None
    mac_address: str | None
    model: str | None
    location: str | None
    operation_status: str | None
    radios: list[RadioStatus] = field(default_factory=list)


@dataclass(slots=True)
class ClientStatus:
    mac_address: str
    ap_mac: str | None
    ssid: str | None
    rssi: int | None
    snr: int | None
    status: str | None


async def check_reachable(settings: ControllerConfig) -> dict:
    """The one thing every AireOS device exposes without table-layout
    guesswork: standard MIB-II identity. Confirms the host, port and
    credentials actually work before trying anything Cisco-specific."""
    target = to_snmp_target(settings)
    try:
        values = await snmp.get(target, OID_SYS_DESCR, OID_SYS_UPTIME, OID_SYS_NAME)
    except snmp.SnmpError as exc:
        return {"reachable": False, "error": str(exc)}

    uptime_ticks = values.get(OID_SYS_UPTIME)
    return {
        "reachable": True,
        "error": None,
        "sys_descr": values.get(OID_SYS_DESCR),
        "sys_name": values.get(OID_SYS_NAME),
        "uptime_sec": round(uptime_ticks / 100, 1) if isinstance(uptime_ticks, int) else None,
    }


def _group_by_index(
    rows: list[tuple[str, object]], table_root: str, columns: dict[str, int]
) -> dict[str, dict]:
    """Turn a flat WALK of ``table.column.index = value`` rows into
    ``{index: {field_name: value}}``, using the column-number map above."""
    by_column = {number: name for name, number in columns.items()}
    grouped: dict[str, dict] = {}
    for oid, value in rows:
        rest = oid[len(table_root) :].lstrip(".")
        if "." not in rest:
            continue
        column_str, index = rest.split(".", 1)
        try:
            column = int(column_str)
        except ValueError:
            continue
        field_name = by_column.get(column)
        if field_name is None:
            continue
        grouped.setdefault(index, {})[field_name] = value
    return grouped


async def list_access_points(settings: ControllerConfig) -> list[AccessPointStatus]:
    """Every AP the controller manages, with each of its radios attached."""
    target = to_snmp_target(settings)

    ap_rows = await snmp.walk(target, _AP_TABLE)
    ap_fields = _group_by_index(ap_rows, _AP_TABLE, _AP_COLUMNS)

    radio_rows = await snmp.walk(target, _AP_IF_TABLE)
    radio_fields = _group_by_index(radio_rows, _AP_IF_TABLE, _AP_IF_COLUMNS)

    aps: dict[str, AccessPointStatus] = {}
    for index, fields in ap_fields.items():
        status_code = fields.get("operation_status")
        aps[index] = AccessPointStatus(
            index=index,
            name=fields.get("name"),
            ip_address=fields.get("ip_address"),
            mac_address=fields.get("mac_address"),
            model=fields.get("model"),
            location=fields.get("location"),
            operation_status=OPERATION_STATUS_LABELS.get(status_code)
            if isinstance(status_code, int)
            else None,
        )

    for radio_index, fields in radio_fields.items():
        # A radio's compound index starts with its AP's index.
        ap_index = radio_index.split(".", 1)[0]
        ap = aps.get(ap_index)
        if ap is None:
            continue  # a radio for an AP that dropped out of bsnAPTable mid-walk
        status_code = fields.get("operation_status")
        ap.radios.append(
            RadioStatus(
                ap_index=ap_index,
                radio_index=radio_index,
                channel=fields.get("channel") if isinstance(fields.get("channel"), int) else None,
                operation_status=OPERATION_STATUS_LABELS.get(status_code)
                if isinstance(status_code, int)
                else None,
                tx_power_level=fields.get("tx_power_level"),
                client_count=fields.get("client_count"),
                channel_utilization_pct=fields.get("channel_utilization"),
            )
        )

    return sorted(aps.values(), key=lambda ap: (ap.name or "", ap.index))


async def list_clients(settings: ControllerConfig) -> list[ClientStatus]:
    """Every client the controller currently holds, across every AP.

    This is what lets a survey answer a question the client side alone
    cannot: does the controller agree the survey laptop is where it thinks it
    is? A mismatch - the client believes it is on AP X, but the controller has
    no record of its MAC there - points at a stale association the AP has
    already dropped.
    """
    target = to_snmp_target(settings)
    rows = await snmp.walk(target, _CLIENT_TABLE)
    fields = _group_by_index(rows, _CLIENT_TABLE, _CLIENT_COLUMNS)

    clients = []
    for index, row in fields.items():
        # The client table's index is the station's MAC, dotted-decimal
        # (six bytes -> six numbers) rather than colon-hex.
        mac = _decimal_index_to_mac(index)
        status_code = row.get("status")
        clients.append(
            ClientStatus(
                mac_address=mac or index,
                ap_mac=row.get("ap_mac"),
                ssid=row.get("ssid"),
                rssi=row.get("rssi") if isinstance(row.get("rssi"), int) else None,
                snr=row.get("snr") if isinstance(row.get("snr"), int) else None,
                status=str(status_code) if status_code is not None else None,
            )
        )
    return clients


def _decimal_index_to_mac(index: str) -> str | None:
    """``6.170.187.204.221.238.1`` (a leading length byte, per SNMP's table
    convention for MAC-indexed rows) -> ``AA:BB:CC:DD:EE:01``."""
    parts = index.split(".")
    if parts and parts[0] == "6":
        parts = parts[1:]
    if len(parts) != 6:
        return None
    try:
        return ":".join(f"{int(part):02X}" for part in parts)
    except ValueError:
        return None


async def raw_walk(settings: ControllerConfig, root_oid: str, *, max_rows: int = 500) -> list[dict]:
    """Verification tool: dump exactly what a subtree returns, unmapped.

    This is the same instrument that resolved the Windows locale bug for
    ``netsh`` - point it at a table root, compare the raw output against the
    WLC's own CLI or web UI, and correct the column-number maps above from
    real evidence rather than from documentation.
    """
    target = to_snmp_target(settings)
    rows = await snmp.walk(target, root_oid, max_rows=max_rows)
    return [{"oid": oid, "value": value} for oid, value in rows]


def compare_client_to_controller(link: dict, clients: list[ClientStatus]) -> dict:
    """Does the controller's record of this machine agree with what the
    client's own radio reports?

    This is the one check that needs both sides: the client-side BSSID the
    rest of this app has been reading all along, and the controller's own
    client table. A mismatch - the client believes it holds AP X, but the WLC
    has no record of this MAC there - is a stale association the AP has
    already dropped, which neither side alone would reveal.
    """
    if not link.get("connected"):
        return {
            "agrees": None,
            "reason": "This machine is not associated to any WiFi network right now.",
            "client_bssid": None,
            "controller_ap_mac": None,
        }

    client_bssid = (link.get("bssid") or "").upper()
    entry = next(
        (c for c in clients if c.ap_mac and c.ap_mac.upper() == client_bssid), None
    )

    if entry is None:
        return {
            "agrees": False,
            "reason": (
                "The controller has no client record on this AP's radio for this "
                "machine's MAC - the client may be holding a stale association."
            ),
            "client_bssid": client_bssid,
            "controller_ap_mac": None,
        }
    return {
        "agrees": True,
        "reason": "The controller confirms this machine on the AP the client reports.",
        "client_bssid": client_bssid,
        "controller_ap_mac": entry.ap_mac,
        "controller_rssi": entry.rssi,
        "controller_ssid": entry.ssid,
    }
