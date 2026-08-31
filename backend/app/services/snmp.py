"""A thin, timeout-safe SNMP client.

Kept separate from ``controller.py`` because nothing here is Cisco-specific -
it is just "GET this OID" and "WALK this subtree", built once so the WLC
integration and any future SNMP-speaking device can share it.

SNMPv2c is the default because it is what most existing WLC deployments already
have turned on; SNMPv3 is supported for the (safer) case where a network team
is willing to set it up. v2c's community string is sent in cleartext on the
wire, which is worth saying plainly rather than leaving implicit - see the
warning surfaced in ``services/controller.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pysnmp.hlapi.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    Udp6TransportTarget,
    UdpTransportTarget,
    UsmUserData,
    bulkCmd,
    getCmd,
    usmAesCfb128Protocol,
    usmHMACSHAAuthProtocol,
    usmNoAuthProtocol,
    usmNoPrivProtocol,
)
from pysnmp.proto.rfc1902 import OctetString
from pysnmp.proto.rfc1905 import EndOfMibView, NoSuchInstance, NoSuchObject

# The three "there is nothing here" markers SNMP can return in place of a
# value - a missing scalar, a missing table row, and walking off the end of
# the tree. All three mean the same thing to a caller: this column is absent
# on this device, not present-but-empty.
_NO_VALUE_TYPES = (NoSuchObject, NoSuchInstance, EndOfMibView)

DEFAULT_TIMEOUT_SEC = 4.0
DEFAULT_RETRIES = 1
# How many varbinds a single GETBULK asks for. Large enough that a table of a
# few hundred APs walks in a handful of round trips, small enough that one
# slow WLC CPU does not time out answering it.
BULK_MAX_REPETITIONS = 25


class SnmpError(Exception):
    """Wraps every SNMP failure mode (timeout, auth, unreachable host) into
    one type the caller can catch without knowing pysnmp's exception zoo."""


@dataclass(slots=True)
class SnmpTarget:
    host: str
    port: int = 161
    version: str = "v2c"  # "v2c" or "v3"
    community: str = "public"
    timeout_sec: float = DEFAULT_TIMEOUT_SEC
    retries: int = DEFAULT_RETRIES
    # SNMPv3 only:
    v3_user: str | None = None
    v3_auth_password: str | None = None
    v3_priv_password: str | None = None

    def auth_data(self):
        if self.version == "v3":
            if not self.v3_user:
                raise SnmpError("SNMPv3 requires a username")
            auth_protocol = usmHMACSHAAuthProtocol if self.v3_auth_password else usmNoAuthProtocol
            priv_protocol = usmAesCfb128Protocol if self.v3_priv_password else usmNoPrivProtocol
            return UsmUserData(
                self.v3_user,
                authKey=self.v3_auth_password or None,
                privKey=self.v3_priv_password or None,
                authProtocol=auth_protocol,
                privProtocol=priv_protocol,
            )
        return CommunityData(self.community, mpModel=1)  # mpModel=1 -> SNMPv2c

    def transport(self):
        # A bare IPv6 literal (no brackets, as stored in settings) still needs
        # the v6 transport; anything else - a hostname or an IPv4 literal -
        # uses the ordinary one.
        target_cls = Udp6TransportTarget if ":" in self.host else UdpTransportTarget
        return target_cls((self.host, self.port), timeout=self.timeout_sec, retries=self.retries)


async def get(target: SnmpTarget, *oids: str) -> dict[str, str | int | None]:
    """SNMP GET one or more scalar OIDs. Missing values come back as ``None``
    rather than raising, since one absent column should not fail the others."""
    engine = SnmpEngine()
    error_indication, error_status, _error_index, var_binds = await getCmd(
        engine,
        target.auth_data(),
        target.transport(),
        ContextData(),
        *(ObjectType(ObjectIdentity(oid)) for oid in oids),
    )
    _raise_if_failed(error_indication, error_status, target)

    result: dict[str, str | int | None] = {}
    for oid, object_type in zip(oids, var_binds, strict=True):
        value = object_type[1]
        result[oid] = None if isinstance(value, _NO_VALUE_TYPES) else _coerce(value)
    return result


async def walk(
    target: SnmpTarget, root_oid: str, *, max_rows: int = 5000
) -> list[tuple[str, str | int | None]]:
    """SNMP WALK a subtree via GETBULK, returning every ``(oid, value)`` under it.

    Stops the moment a returned OID falls outside ``root_oid`` - GETBULK
    happily returns the *next* table's rows once it runs off the end of this
    one, and treating those as ours would silently corrupt the result.
    """
    engine = SnmpEngine()
    transport = target.transport()
    auth = target.auth_data()
    root_prefix = root_oid.rstrip(".") + "."

    rows: list[tuple[str, str | int | None]] = []
    current = ObjectType(ObjectIdentity(root_oid))

    while len(rows) < max_rows:
        error_indication, error_status, _error_index, var_bind_table = await bulkCmd(
            engine, auth, transport, ContextData(), 0, BULK_MAX_REPETITIONS, current
        )
        _raise_if_failed(error_indication, error_status, target)
        if not var_bind_table:
            break

        exhausted = False
        for row in var_bind_table:
            for object_type in row:
                value = object_type[1]
                if isinstance(value, _NO_VALUE_TYPES):
                    exhausted = True
                    break
                oid_str = str(object_type[0])
                if not oid_str.startswith(root_prefix):
                    exhausted = True
                    break
                rows.append((oid_str, _coerce(value)))
            if exhausted:
                break
        if exhausted or not var_bind_table:
            break
        current = ObjectType(var_bind_table[-1][-1][0])

    return rows


def _coerce(value) -> str | int | None:
    """pysnmp's typed values need different handling to come out useful.

    Numeric types (Integer32, Counter32, Gauge32, TimeTicks) stringify to
    plain digits already and are kept as ``int`` so a caller can compare or
    sum them directly. ``OctetString`` covers two very different things in
    practice - human text (an AP name, an SSID) and raw binary (a MAC
    address, some vendor-specific field). Running a raw MAC through plain
    ``str()`` produces unprintable garbage rather than an error - exactly the
    kind of silent-wrong-answer this app avoids everywhere else - so a binary
    OctetString is hex-encoded instead of stringified blind.
    """
    if isinstance(value, OctetString):
        raw = value.asOctets()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return _hex(raw)
        return text if text.isprintable() else _hex(raw)

    text = str(value)
    try:
        return int(text)
    except ValueError:
        return text


def _hex(raw: bytes) -> str:
    return ":".join(f"{byte:02X}" for byte in raw)


def _raise_if_failed(error_indication, error_status, target: SnmpTarget) -> None:
    if error_indication:
        raise SnmpError(f"{target.host}:{target.port} - {error_indication}")
    if error_status:
        raise SnmpError(f"{target.host}:{target.port} - {error_status.prettyPrint()}")
