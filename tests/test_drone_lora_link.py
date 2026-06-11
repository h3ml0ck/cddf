"""Tests for the MeshLink radio layer and drone-lora-relay CLI.

The codec tests live in test_drone_lora.py. Here the meshtastic stack is
faked at module level (interface classes, pubsub, port numbers) so the
connect/broadcast/receive/close paths run without hardware or the optional
``lora`` extra installed.
"""

from unittest.mock import MagicMock

import pytest

import drone_tools.drone_lora as dl
from drone_tools.drone_lora import (
    DetectionEvent,
    DetectionThrottle,
    DetectorType,
    MeshLink,
    ReceivedEvent,
    _format_received,
    encode_event,
    main,
)


def _event(**kwargs) -> DetectionEvent:
    defaults = dict(detector=DetectorType.WIFI_REMOTE_ID, timestamp=1700000000)
    defaults.update(kwargs)
    return DetectionEvent(**defaults)


@pytest.fixture
def fake_meshtastic(monkeypatch):
    """Install fake meshtastic/pubsub modules into the drone_lora namespace.

    The real names only exist when the optional dependency is installed, so
    raising=False lets these tests run either way.
    """
    serial_iface = MagicMock(name="serial_interface_instance")
    tcp_iface = MagicMock(name="tcp_interface_instance")

    fake_mesh = MagicMock()
    fake_mesh.serial_interface.SerialInterface = MagicMock(return_value=serial_iface)
    fake_mesh.tcp_interface.TCPInterface = MagicMock(return_value=tcp_iface)

    fake_pub = MagicMock()
    fake_portnums = MagicMock()
    fake_portnums.PortNum.PRIVATE_APP = 256

    monkeypatch.setattr(dl, "MESHTASTIC_AVAILABLE", True)
    monkeypatch.setattr(dl, "meshtastic", fake_mesh, raising=False)
    monkeypatch.setattr(dl, "pub", fake_pub, raising=False)
    monkeypatch.setattr(dl, "portnums_pb2", fake_portnums, raising=False)
    return {"mesh": fake_mesh, "pub": fake_pub, "serial": serial_iface, "tcp": tcp_iface}


# --- connect / close ---------------------------------------------------------


def test_connect_requires_meshtastic(monkeypatch):
    monkeypatch.setattr(dl, "MESHTASTIC_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="meshtastic is required"):
        MeshLink().connect()


def test_connect_serial_subscribes_first(fake_meshtastic):
    link = MeshLink(device="/dev/ttyUSB0").connect()
    fake_meshtastic["pub"].subscribe.assert_called_once_with(link._on_receive, "meshtastic.receive")
    fake_meshtastic["mesh"].serial_interface.SerialInterface.assert_called_once_with(devPath="/dev/ttyUSB0")
    assert link.interface is fake_meshtastic["serial"]


def test_connect_host_takes_precedence_over_device(fake_meshtastic):
    link = MeshLink(device="/dev/ttyUSB0", host="10.0.0.5").connect()
    fake_meshtastic["mesh"].tcp_interface.TCPInterface.assert_called_once_with(hostname="10.0.0.5")
    fake_meshtastic["mesh"].serial_interface.SerialInterface.assert_not_called()
    assert link.interface is fake_meshtastic["tcp"]


def test_close_unsubscribes_and_closes_interface(fake_meshtastic):
    link = MeshLink().connect()
    iface = link.interface
    link.close()
    fake_meshtastic["pub"].unsubscribe.assert_called_once()
    iface.close.assert_called_once()
    assert link.interface is None
    link.close()  # second close is a no-op
    iface.close.assert_called_once()


def test_close_suppresses_unsubscribe_failure(fake_meshtastic):
    fake_meshtastic["pub"].unsubscribe.side_effect = RuntimeError("not subscribed")
    link = MeshLink().connect()
    link.close()  # must not raise
    fake_meshtastic["serial"].close.assert_called_once()


def test_context_manager_connects_and_closes(fake_meshtastic):
    with MeshLink() as link:
        assert link.interface is not None
    assert link.interface is None


# --- broadcast ----------------------------------------------------------------


def test_broadcast_requires_connect():
    with pytest.raises(RuntimeError, match="not connected"):
        MeshLink().broadcast(_event())


def test_broadcast_sends_encoded_frame(fake_meshtastic):
    link = MeshLink().connect()
    event = _event(drone_id="1581F4ABC")
    assert link.broadcast(event) is True
    call = fake_meshtastic["serial"].sendData.call_args
    assert call.args[0] == encode_event(event)
    assert call.kwargs["destinationId"] == "^all"
    assert call.kwargs["portNum"] == 256
    assert call.kwargs["wantAck"] is False


def test_broadcast_respects_throttle(fake_meshtastic):
    link = MeshLink(throttle=DetectionThrottle(interval=30.0)).connect()
    event = _event(drone_id="SAME")
    assert link.broadcast(event) is True
    assert link.broadcast(event) is False
    assert fake_meshtastic["serial"].sendData.call_count == 1


# --- receive path --------------------------------------------------------------


def _packet(event: DetectionEvent, **overrides) -> dict:
    packet = {
        "decoded": {"portnum": "PRIVATE_APP", "payload": encode_event(event)},
        "fromId": "!a1b2c3d4",
        "rxRssi": -90,
        "rxSnr": 5.5,
        "hopsAway": 1,
    }
    packet.update(overrides)
    return packet


def test_on_receive_decodes_and_calls_back():
    received: list[ReceivedEvent] = []
    link = MeshLink(on_event=received.append)
    link._on_receive(packet=_packet(_event(drone_id="ID-9", rssi=-60)))
    assert len(received) == 1
    assert received[0].event.drone_id == "ID-9"
    assert received[0].from_id == "!a1b2c3d4"
    assert received[0].rssi == -90
    assert received[0].snr == 5.5
    assert received[0].hops_away == 1


def test_on_receive_ignores_other_ports():
    received = []
    link = MeshLink(on_event=received.append)
    link._on_receive(packet=_packet(_event(), decoded={"portnum": "TEXT_MESSAGE_APP", "payload": b"hi"}))
    assert received == []


def test_on_receive_ignores_empty_payload():
    received = []
    link = MeshLink(on_event=received.append)
    link._on_receive(packet=_packet(_event(), decoded={"portnum": "PRIVATE_APP", "payload": b""}))
    link._on_receive(packet=None)
    assert received == []


def test_on_receive_reports_malformed_frame():
    errors = []
    link = MeshLink(on_event=lambda r: None, on_error=lambda ctx, exc: errors.append(ctx))
    link._on_receive(packet=_packet(_event(), decoded={"portnum": "PRIVATE_APP", "payload": b"\xff\xff"}))
    assert errors == ["failed to decode received frame"]


def test_on_receive_isolates_callback_failure():
    errors = []

    def explode(received):
        raise RuntimeError("boom")

    link = MeshLink(on_event=explode, on_error=lambda ctx, exc: errors.append(ctx))
    link._on_receive(packet=_packet(_event()))
    assert errors == ["on_event callback raised"]


def test_default_on_error_logs(caplog):
    with caplog.at_level("ERROR"):
        MeshLink._default_on_error("decode failed", ValueError("bad frame"))
    assert "decode failed" in caplog.text


# --- formatting / CLI -----------------------------------------------------------


def test_format_received_includes_all_fields():
    received = ReceivedEvent(
        event=_event(
            lat=37.7749,
            lon=-122.4194,
            altitude=120,
            rssi=-67,
            drone_id="ID-1",
            operator_id="OP-1",
        ),
        from_id="!a1b2c3d4",
        rssi=-90,
        snr=5.5,
        hops_away=2,
    )
    text = _format_received(received)
    for fragment in (
        "WIFI_REMOTE_ID",
        "from !a1b2c3d4",
        "RSSI -90dBm",
        "SNR 5.5dB",
        "2 hop(s)",
        "drone_id=ID-1",
        "operator=OP-1",
        "loc=37.774900,-122.419400",
        "alt=120m",
        "signal=-67dBm",
    ):
        assert fragment in text


def test_main_requires_meshtastic(monkeypatch):
    monkeypatch.setattr(dl, "MESHTASTIC_AVAILABLE", False)
    assert main([]) == 1


def test_main_send_test_broadcasts_once(monkeypatch):
    link = MagicMock()
    link.__enter__ = MagicMock(return_value=link)
    link.__exit__ = MagicMock(return_value=None)
    monkeypatch.setattr(dl, "MESHTASTIC_AVAILABLE", True)
    monkeypatch.setattr(dl, "MeshLink", MagicMock(return_value=link))
    monkeypatch.setattr(dl.time, "sleep", lambda s: None)
    assert main(["--send-test"]) == 0
    link.broadcast.assert_called_once()


def test_main_listen_loop_stops_on_interrupt(monkeypatch):
    link = MagicMock()
    link.__enter__ = MagicMock(return_value=link)
    link.__exit__ = MagicMock(return_value=None)
    monkeypatch.setattr(dl, "MESHTASTIC_AVAILABLE", True)
    monkeypatch.setattr(dl, "MeshLink", MagicMock(return_value=link))
    monkeypatch.setattr(dl.time, "sleep", MagicMock(side_effect=KeyboardInterrupt))
    assert main([]) == 0


def test_main_connect_failure_returns_1(monkeypatch):
    monkeypatch.setattr(dl, "MESHTASTIC_AVAILABLE", True)
    monkeypatch.setattr(dl, "MeshLink", MagicMock(side_effect=ConnectionError("no radio")))
    assert main(["--host", "10.0.0.5"]) == 1
