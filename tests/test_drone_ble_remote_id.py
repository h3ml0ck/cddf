import struct
from unittest.mock import MagicMock, patch

import pytest

import drone_tools.drone_ble_remote_id as ble

# -------------------------------------------------------
# parse_ble_service_data
# -------------------------------------------------------


def test_parse_ble_service_data_too_short():
    assert ble.parse_ble_service_data(b"") is None
    assert ble.parse_ble_service_data(b"\x00") is None


def test_parse_ble_service_data_basic_id():
    uas_id = "DRONE-ABC-123"
    id_bytes = uas_id.encode("utf-8").ljust(20, b"\x00")
    # header byte: msg_type=0 (Basic ID), protocol version in upper nibble
    payload = bytes([0x00]) + bytes([4, 1]) + id_bytes  # ua_type=4 (VTOL), id_type=1 (Serial)
    result = ble.parse_ble_service_data(payload)
    assert result is not None
    assert result["message_type"] == "Basic ID"
    assert result["raw_type"] == 0
    assert result["uas_id"] == uas_id
    assert result["ua_type"] == "VTOL"
    assert result["id_type"] == "Serial Number"


def test_parse_ble_service_data_location_vector():
    msg_data = bytes([0x01])  # status=airborne
    msg_data += struct.pack("<H", int(90.0 * 100))  # direction
    msg_data += struct.pack("<H", int(5.0 * 100))  # speed_h
    msg_data += struct.pack("<h", int(-1.0 * 100))  # speed_v
    msg_data += struct.pack("<i", int(37.7749 * 1e7))  # lat
    msg_data += struct.pack("<i", int(-122.4194 * 1e7))  # lon
    msg_data += struct.pack("<h", int(150.0 * 2))  # alt
    msg_data += struct.pack("<h", int(100.0 * 2))  # height
    msg_data = msg_data.ljust(25, b"\x00")
    payload = bytes([0x01]) + msg_data

    result = ble.parse_ble_service_data(payload)
    assert result is not None
    assert result["message_type"] == "Location/Vector"
    assert result["latitude"] == pytest.approx(37.7749, abs=1e-4)
    assert result["longitude"] == pytest.approx(-122.4194, abs=1e-4)


def test_parse_ble_service_data_self_id():
    description = "Inspection Mission"
    payload = bytes([0x03]) + bytes([0]) + description.encode("utf-8")
    result = ble.parse_ble_service_data(payload)
    assert result is not None
    assert result["message_type"] == "Self ID"
    assert result["description"] == description


def test_parse_ble_service_data_operator_id():
    op_id = "FAA123456"
    id_bytes = op_id.encode("utf-8").ljust(20, b"\x00")
    payload = bytes([0x05]) + bytes([1]) + id_bytes
    result = ble.parse_ble_service_data(payload)
    assert result is not None
    assert result["message_type"] == "Operator ID"
    assert result["operator_id"] == op_id


def test_parse_ble_service_data_unknown_type_keeps_raw_hex():
    payload = bytes([0x0A]) + b"\xde\xad\xbe\xef"
    result = ble.parse_ble_service_data(payload)
    assert result is not None
    assert result["raw_type"] == 0x0A
    assert result["raw_data"] == "deadbeef"


def test_parse_ble_service_data_strips_protocol_version_from_header():
    # Upper nibble (protocol version) should be ignored; only lower nibble is msg_type.
    uas_id = "VER-TEST"
    id_bytes = uas_id.encode("utf-8").ljust(20, b"\x00")
    payload = bytes([0xF0]) + bytes([4, 1]) + id_bytes  # 0xF0 -> msg_type 0
    result = ble.parse_ble_service_data(payload)
    assert result is not None
    assert result["raw_type"] == 0
    assert result["message_type"] == "Basic ID"


def test_parse_ble_service_data_too_short_for_known_type_falls_back_to_raw():
    # msg_type=1 (Location/Vector) requires >= 25 bytes of msg_data, we send 3.
    payload = bytes([0x01]) + b"\x01\x02\x03"
    result = ble.parse_ble_service_data(payload)
    assert result is not None
    assert result["raw_type"] == 1
    assert "raw_data" in result


# -------------------------------------------------------
# _make_callback
# -------------------------------------------------------


def test_callback_ignores_non_remote_id_service_uuid(capsys):
    cb = ble._make_callback(verbose=False)
    device = MagicMock(address="AA:BB:CC:DD:EE:FF")
    adv = MagicMock(rssi=-60, service_data={"0000beef-0000-1000-8000-00805f9b34fb": b"\x00\x00"})
    cb(device, adv)
    assert capsys.readouterr().out == ""


def test_callback_prints_parsed_remote_id(capsys):
    uas_id = "DRONE-XYZ"
    id_bytes = uas_id.encode("utf-8").ljust(20, b"\x00")
    payload = bytes([0x00, 4, 1]) + id_bytes  # Basic ID

    cb = ble._make_callback(verbose=False)
    device = MagicMock(address="AA:BB:CC:DD:EE:FF")
    adv = MagicMock(rssi=-42, service_data={ble.REMOTE_ID_SERVICE_UUID: payload})
    cb(device, adv)

    out = capsys.readouterr().out
    assert "AA:BB:CC:DD:EE:FF" in out
    assert "-42 dBm" in out
    assert "Basic ID" in out
    assert uas_id in out


def test_callback_verbose_prints_raw_hex(capsys):
    payload = bytes([0x0A]) + b"\xab\xcd"  # unknown type -> raw_data present, but raw_hex is the adv bytes
    cb = ble._make_callback(verbose=True)
    device = MagicMock(address="11:22:33:44:55:66")
    adv = MagicMock(rssi=-70, service_data={ble.REMOTE_ID_SERVICE_UUID: payload})
    cb(device, adv)
    assert "raw_hex: 0aabcd" in capsys.readouterr().out


def test_callback_accepts_uppercase_uuid(capsys):
    payload = bytes([0x03, 0]) + b"hello"
    cb = ble._make_callback(verbose=False)
    device = MagicMock(address="AA:BB:CC:DD:EE:FF")
    adv = MagicMock(rssi=-55, service_data={ble.REMOTE_ID_SERVICE_UUID.upper(): payload})
    cb(device, adv)
    assert "Self ID" in capsys.readouterr().out


# -------------------------------------------------------
# capture_ble_remote_id
# -------------------------------------------------------


def test_capture_raises_when_bleak_unavailable():
    import asyncio

    with patch.object(ble, "BLEAK_AVAILABLE", False):
        with pytest.raises(RuntimeError, match="bleak is required"):
            asyncio.run(ble.capture_ble_remote_id(timeout=0.01))


# -------------------------------------------------------
# main
# -------------------------------------------------------


def _fake_asyncio_run(behavior):
    """Return a replacement for asyncio.run that closes the incoming coroutine
    before invoking *behavior* (which may raise or return)."""

    def runner(coro, *args, **kwargs):
        coro.close()  # avoid "coroutine was never awaited" warnings
        return behavior()

    return runner


def test_main_handles_keyboard_interrupt(monkeypatch, capsys):
    def raise_kbi():
        raise KeyboardInterrupt

    monkeypatch.setattr(ble.asyncio, "run", _fake_asyncio_run(raise_kbi))
    rc = ble.main(["--timeout", "0.01"])
    assert rc == 0
    assert "Capture stopped" in capsys.readouterr().out


def test_main_returns_one_on_exception(monkeypatch, capsys):
    def raise_exc():
        raise RuntimeError("boom")

    monkeypatch.setattr(ble.asyncio, "run", _fake_asyncio_run(raise_exc))
    rc = ble.main([])
    assert rc == 1
    assert "boom" in capsys.readouterr().err


def test_main_returns_zero_on_clean_exit(monkeypatch):
    monkeypatch.setattr(ble.asyncio, "run", _fake_asyncio_run(lambda: None))
    assert ble.main(["--timeout", "0.01"]) == 0
