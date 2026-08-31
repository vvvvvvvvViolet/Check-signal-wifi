"""The generic SNMP client: GET/WALK semantics, missing-value handling, and
the binary-vs-text decoding that a naive ``str()`` would get wrong.

These mock pysnmp's own coroutines rather than hitting a real agent, so the
suite needs no SNMP daemon in CI. The real wire behaviour (GET, WALK,
wrong-community, unreachable-host) was verified by hand against a local
``snmpd`` before this file was written; what is worth locking down here is
this module's own control flow.

No async test plugin is set up in this project, so each test wraps its
coroutine in ``asyncio.run`` rather than adding one just for this file.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest
from backend.app.services import snmp
from pysnmp.hlapi.asyncio import ObjectIdentity
from pysnmp.proto.rfc1902 import Integer32, OctetString
from pysnmp.proto.rfc1905 import EndOfMibView, NoSuchInstance, NoSuchObject


def test_coerce_renders_a_binary_mac_as_colon_hex():
    """The bug this module exists to avoid: str() on a raw-byte OctetString
    produces unprintable garbage, not an error - so it must never be trusted
    blind for a value that might be binary."""
    raw = OctetString(bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0x01]))
    assert snmp._coerce(raw) == "AA:BB:CC:DD:EE:01"


def test_coerce_keeps_printable_text_as_text():
    assert snmp._coerce(OctetString("AP-Factory-01")) == "AP-Factory-01"


def test_coerce_handles_utf8_text():
    assert snmp._coerce(OctetString("โรงงาน A".encode())) == "โรงงาน A"


def test_coerce_handles_empty_octet_string():
    assert snmp._coerce(OctetString("")) == ""


def test_coerce_keeps_integers_as_int():
    assert snmp._coerce(Integer32(42)) == 42
    assert isinstance(snmp._coerce(Integer32(42)), int)


@pytest.fixture
def target():
    return snmp.SnmpTarget(host="10.0.0.1", community="public", timeout_sec=1, retries=0)


def _oid_value(oid_str: str, value):
    # spec=ObjectIdentity makes isinstance() checks pass, which walk() relies
    # on when it feeds the last row's OID back in as the next page's cursor.
    oid = mock.Mock(spec=ObjectIdentity)
    oid.__str__ = mock.Mock(return_value=oid_str)
    return (oid, value)


def test_get_returns_none_for_each_no_value_marker(target):
    """NoSuchObject, NoSuchInstance and EndOfMibView all mean the same thing
    to a caller: this column is absent, not present-but-empty."""
    for marker_cls in (NoSuchObject, NoSuchInstance, EndOfMibView):
        var_binds = [(mock.Mock(), marker_cls())]
        with mock.patch.object(
            snmp, "getCmd", new=mock.AsyncMock(return_value=(None, 0, 0, var_binds))
        ):
            result = asyncio.run(snmp.get(target, "1.2.3"))
        assert result["1.2.3"] is None


def test_get_raises_on_error_indication(target):
    with mock.patch.object(
        snmp, "getCmd", new=mock.AsyncMock(return_value=("timeout", 0, 0, []))
    ), pytest.raises(snmp.SnmpError, match="timeout"):
        asyncio.run(snmp.get(target, "1.2.3"))


def test_get_raises_on_error_status(target):
    status = mock.Mock()
    status.prettyPrint.return_value = "noSuchName"
    with mock.patch.object(
        snmp, "getCmd", new=mock.AsyncMock(return_value=(None, status, 0, []))
    ), pytest.raises(snmp.SnmpError, match="noSuchName"):
        asyncio.run(snmp.get(target, "1.2.3"))


def test_walk_stops_at_the_end_of_the_requested_subtree(target):
    """GETBULK happily returns the *next* table's rows once it runs off the
    end of this one; treating those as ours would corrupt the result."""
    root = "1.3.6.1.4.1.99.1"
    page = [
        (_oid_value(f"{root}.1", Integer32(10)),),
        (_oid_value(f"{root}.2", Integer32(20)),),
        # This row belongs to a different subtree entirely.
        (_oid_value("1.3.6.1.4.1.99.2.1", Integer32(999)),),
    ]
    with mock.patch.object(
        snmp, "bulkCmd", new=mock.AsyncMock(return_value=(None, 0, 0, page))
    ):
        rows = asyncio.run(snmp.walk(target, root))
    assert rows == [(f"{root}.1", 10), (f"{root}.2", 20)]


def test_walk_stops_on_end_of_mib_view(target):
    root = "1.3.6.1.4.1.99.1"
    page = [(_oid_value(f"{root}.1", EndOfMibView()),)]
    with mock.patch.object(
        snmp, "bulkCmd", new=mock.AsyncMock(return_value=(None, 0, 0, page))
    ):
        rows = asyncio.run(snmp.walk(target, root))
    assert rows == []


def test_walk_paginates_across_multiple_bulk_responses(target):
    root = "1.3.6.1.4.1.99.1"
    first_page = [(_oid_value(f"{root}.1", Integer32(1)),)]
    second_page = [(_oid_value(f"{root}.2", Integer32(2)),)]
    third_page = [(_oid_value("1.3.6.1.4.1.99.2", Integer32(0)),)]  # exhausted

    responses = iter([first_page, second_page, third_page])

    async def fake_bulk(*_args, **_kwargs):
        return (None, 0, 0, next(responses))

    with mock.patch.object(snmp, "bulkCmd", side_effect=fake_bulk):
        rows = asyncio.run(snmp.walk(target, root))
    assert rows == [(f"{root}.1", 1), (f"{root}.2", 2)]


def test_walk_raises_on_error_indication(target):
    with mock.patch.object(
        snmp, "bulkCmd", new=mock.AsyncMock(return_value=("no response", 0, 0, []))
    ), pytest.raises(snmp.SnmpError):
        asyncio.run(snmp.walk(target, "1.2.3"))


def test_v3_target_without_a_username_is_rejected():
    target = snmp.SnmpTarget(host="10.0.0.1", version="v3")
    with pytest.raises(snmp.SnmpError, match="username"):
        target.auth_data()


def test_ipv6_host_selects_the_v6_transport():
    target = snmp.SnmpTarget(host="fe80::1")
    transport = target.transport()
    assert type(transport).__name__ == "Udp6TransportTarget"


def test_ipv4_host_selects_the_v4_transport():
    target = snmp.SnmpTarget(host="10.0.0.1")
    transport = target.transport()
    assert type(transport).__name__ == "UdpTransportTarget"
