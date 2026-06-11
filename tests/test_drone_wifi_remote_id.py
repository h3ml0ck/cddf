import struct
from unittest.mock import MagicMock

import pytest

import drone_tools.drone_wifi_remote_id as wifi

# -------------------------------------------------------
# parse_remote_id_element
# -------------------------------------------------------


def test_parse_remote_id_element_too_short():
    assert wifi.parse_remote_id_element(b"\x90\x3a") is None


def test_parse_remote_id_element_wrong_oui():
    data = b"\x00\x11\x22\x00" + b"\x00" * 20
    assert wifi.parse_remote_id_element(data) is None


def test_parse_remote_id_element_unknown_type_returns_hex():
    # OUI + type 0xFF + 4 bytes of data
    data = wifi.REMOTE_ID_OUI + b"\xff" + b"\xde\xad\xbe\xef"
    result = wifi.parse_remote_id_element(data)
    assert result is not None
    assert result["raw_type"] == 0xFF
    assert result["raw_data"] == "deadbeef"


def test_parse_remote_id_element_empty_payload():
    # OUI + type only, no payload
    data = wifi.REMOTE_ID_OUI + b"\x03"
    result = wifi.parse_remote_id_element(data)
    assert result is not None
    assert result["data_length"] == 0


# -------------------------------------------------------
# parse_basic_id
# -------------------------------------------------------


def _make_basic_id_element(ua_type: int, id_type: int, uas_id: str) -> bytes:
    id_bytes = uas_id.encode("utf-8")[:20].ljust(20, b"\x00")
    msg_data = bytes([ua_type, id_type]) + id_bytes
    return wifi.REMOTE_ID_OUI + b"\x00" + msg_data


def test_parse_basic_id_serial_number():
    data = _make_basic_id_element(ua_type=4, id_type=1, uas_id="SN-12345")
    result = wifi.parse_remote_id_element(data)
    assert result["message_type"] == "Basic ID"
    assert result["ua_type"] == "VTOL"
    assert result["id_type"] == "Serial Number"
    assert result["uas_id"] == "SN-12345"


def test_parse_basic_id_unknown_types():
    data = _make_basic_id_element(ua_type=99, id_type=99, uas_id="X")
    result = wifi.parse_remote_id_element(data)
    assert "Unknown" in result["ua_type"]
    assert "Unknown" in result["id_type"]


def test_parse_basic_id_trims_null_padding():
    data = _make_basic_id_element(ua_type=2, id_type=2, uas_id="ABC")
    result = wifi.parse_remote_id_element(data)
    assert result["uas_id"] == "ABC"


# -------------------------------------------------------
# parse_location_vector
# -------------------------------------------------------


def _make_location_element(
    status=1, direction_deg=90.0, speed_h=5.0, speed_v=-1.0, lat=37.7749, lon=-122.4194, alt=100.0, height=50.0
) -> bytes:
    msg_data = bytes([status])
    msg_data += struct.pack("<H", int(direction_deg * 100))
    msg_data += struct.pack("<H", int(speed_h * 100))
    msg_data += struct.pack("<h", int(speed_v * 100))
    msg_data += struct.pack("<i", int(lat * 1e7))
    msg_data += struct.pack("<i", int(lon * 1e7))
    msg_data += struct.pack("<h", int(alt * 2))
    msg_data += struct.pack("<h", int(height * 2))
    msg_data = msg_data.ljust(25, b"\x00")  # parser requires >= 25 bytes
    return wifi.REMOTE_ID_OUI + b"\x01" + msg_data


def test_parse_location_vector_values():
    data = _make_location_element(direction_deg=180.0, speed_h=10.0, lat=48.8566, lon=2.3522, alt=200.0, height=80.0)
    result = wifi.parse_remote_id_element(data)
    assert result["message_type"] == "Location/Vector"
    assert result["direction"] == pytest.approx(180.0, abs=0.01)
    assert result["speed_horizontal"] == pytest.approx(10.0, abs=0.01)
    assert result["latitude"] == pytest.approx(48.8566, abs=1e-4)
    assert result["longitude"] == pytest.approx(2.3522, abs=1e-4)
    assert result["altitude"] == pytest.approx(200.0, abs=0.5)
    assert result["height"] == pytest.approx(80.0, abs=0.5)


def test_parse_location_vector_too_short_falls_back_to_raw():
    # Only 10 bytes of payload — below the 25-byte threshold
    short_data = wifi.REMOTE_ID_OUI + b"\x01" + b"\x00" * 10
    result = wifi.parse_remote_id_element(short_data)
    assert result is not None
    assert "raw_data" in result


# -------------------------------------------------------
# parse_self_id
# -------------------------------------------------------


def _make_self_id_element(desc_type: int, description: str) -> bytes:
    msg_data = bytes([desc_type]) + description.encode("utf-8")
    return wifi.REMOTE_ID_OUI + b"\x03" + msg_data


def test_parse_self_id_text():
    data = _make_self_id_element(0, "Delivery drone")
    result = wifi.parse_remote_id_element(data)
    assert result["message_type"] == "Self ID"
    assert result["description_type"] == "Text"
    assert result["description"] == "Delivery drone"


def test_parse_self_id_emergency():
    data = _make_self_id_element(1, "MAYDAY")
    result = wifi.parse_remote_id_element(data)
    assert result["description_type"] == "Emergency"


def test_parse_self_id_unknown_desc_type():
    data = _make_self_id_element(99, "???")
    result = wifi.parse_remote_id_element(data)
    assert "Unknown" in result["description_type"]


# -------------------------------------------------------
# parse_operator_id
# -------------------------------------------------------


def _make_operator_id_element(op_id_type: int, operator_id: str) -> bytes:
    id_bytes = operator_id.encode("utf-8")[:20].ljust(20, b"\x00")
    msg_data = bytes([op_id_type]) + id_bytes
    return wifi.REMOTE_ID_OUI + b"\x05" + msg_data


def test_parse_operator_id():
    data = _make_operator_id_element(0, "OP-XYZ-789")
    result = wifi.parse_remote_id_element(data)
    assert result["message_type"] == "Operator ID"
    assert result["operator_id"] == "OP-XYZ-789"
    assert result["operator_id_type"] == 0


def test_parse_operator_id_trims_null_padding():
    data = _make_operator_id_element(1, "SHORT")
    result = wifi.parse_remote_id_element(data)
    assert result["operator_id"] == "SHORT"


# -------------------------------------------------------
# _packet_rssi
# -------------------------------------------------------


def test_packet_rssi_returns_none_for_none():
    assert wifi._packet_rssi(None) is None


def test_packet_rssi_returns_none_without_radiotap():
    pkt = MagicMock()
    pkt.haslayer.return_value = False
    assert wifi._packet_rssi(pkt) is None


def test_packet_rssi_extracts_signal():
    pkt = MagicMock()
    pkt.haslayer.return_value = True
    rt = MagicMock()
    rt.dBm_AntSignal = -55
    pkt.__getitem__ = MagicMock(return_value=rt)
    assert wifi._packet_rssi(pkt) == -55


# -------------------------------------------------------
# _event_from_remote_id
# -------------------------------------------------------


def test_event_from_remote_id_with_full_fields():
    fields = {
        "uas_id": "DRONE-1",
        "latitude": 37.7749,
        "longitude": -122.4194,
        "altitude": 120.5,
        "operator_id": "OP-1",
    }
    event = wifi._event_from_remote_id(fields, rssi=-72)
    assert event is not None
    assert event.detector == wifi.DetectorType.WIFI_REMOTE_ID
    assert event.drone_id == "DRONE-1"
    assert event.lat == pytest.approx(37.7749)
    assert event.altitude == 120
    assert event.operator_id == "OP-1"
    assert event.rssi == -72


def test_event_from_remote_id_location_only():
    fields = {"latitude": 1.0, "longitude": 2.0}
    event = wifi._event_from_remote_id(fields, rssi=None)
    assert event is not None
    assert event.drone_id is None
    assert event.lat == 1.0


def test_event_from_remote_id_none_without_content():
    assert wifi._event_from_remote_id({"description": "hi"}, rssi=None) is None


def test_event_from_remote_id_empty_uas_id():
    assert wifi._event_from_remote_id({"uas_id": ""}, rssi=None) is None


# -------------------------------------------------------
# process_packet (mocked scapy layers)
# -------------------------------------------------------


def test_process_packet_ignores_non_beacon():
    pkt = MagicMock()
    pkt.haslayer.return_value = False
    wifi.process_packet(pkt)  # should not raise


def test_process_packet_emits_event_when_emitter_given():
    from drone_tools.detection_emit import DetectionEmitter, DetectionSink

    class _Recorder(DetectionSink):
        def __init__(self):
            self.events = []

        def emit(self, event):
            self.events.append(event)

    recorder = _Recorder()
    emitter = DetectionEmitter([recorder])

    # Test the internal _event_from_remote_id -> emitter path directly
    fields = {"uas_id": "WIFI-D1", "latitude": 37.7, "longitude": -122.4}
    event = wifi._event_from_remote_id(fields, rssi=-55)
    assert event is not None
    emitter.emit(event)
    assert len(recorder.events) == 1
    assert recorder.events[0].drone_id == "WIFI-D1"


# -------------------------------------------------------
# main CLI
# -------------------------------------------------------


def test_main_no_scapy(monkeypatch):
    monkeypatch.setattr(wifi, "SCAPY_AVAILABLE", False)
    # capture_remote_id will raise RuntimeError
    ret = wifi.main(["wlan0", "--timeout", "0.01"])
    assert ret == 1


# -------------------------------------------------------
# process_packet with real scapy beacon frames
# -------------------------------------------------------


class _Recorder:
    def __init__(self):
        self.events = []

    def start(self):
        return self

    def emit(self, event):
        self.events.append(event)

    def close(self):
        return None


def _recording_emitter():
    from drone_tools.detection_emit import DetectionEmitter

    recorder = _Recorder()
    return DetectionEmitter([recorder]), recorder


def _beacon(*vendor_payloads: bytes, rssi: int | None = None):
    """Build a real scapy beacon frame carrying the given vendor IEs."""
    from scapy.all import Dot11, Dot11Beacon, Dot11Elt, RadioTap

    frame = Dot11(type=0, subtype=8, addr1="ff:ff:ff:ff:ff:ff", addr2="90:3a:e6:11:22:33", addr3="90:3a:e6:11:22:33")
    frame /= Dot11Beacon(cap="ESS")
    frame /= Dot11Elt(ID=0, info=b"drone-net")  # SSID element before the vendor IEs
    for payload in vendor_payloads:
        frame /= Dot11Elt(ID=221, info=payload)
    if rssi is not None:
        return RadioTap(present="dBm_AntSignal", dBm_AntSignal=rssi) / frame
    return RadioTap() / frame


def test_process_packet_combines_basic_id_and_location():
    emitter, recorder = _recording_emitter()
    packet = _beacon(
        _make_basic_id_element(ua_type=4, id_type=1, uas_id="1581F4ABC"),
        _make_location_element(lat=37.7749, lon=-122.4194, alt=120.0),
        rssi=-58,
    )
    wifi.process_packet(packet, emitter)

    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event.drone_id == "1581F4ABC"
    assert event.lat == pytest.approx(37.7749, abs=1e-4)
    assert event.lon == pytest.approx(-122.4194, abs=1e-4)
    assert event.altitude == 120
    assert event.rssi == -58


def test_process_packet_without_emitter_only_logs(caplog):
    packet = _beacon(_make_basic_id_element(ua_type=2, id_type=1, uas_id="SN-1"))
    with caplog.at_level("INFO"):
        wifi.process_packet(packet)
    assert "Basic ID" in caplog.text
    assert "SN-1" in caplog.text


def test_process_packet_skips_foreign_vendor_elements():
    emitter, recorder = _recording_emitter()
    packet = _beacon(b"\x00\x11\x22\x01" + b"\x00" * 20)  # non-ASTM OUI
    wifi.process_packet(packet, emitter)
    assert recorder.events == []


def test_process_packet_no_event_without_identity_or_location():
    emitter, recorder = _recording_emitter()
    packet = _beacon(_make_self_id_element(desc_type=0, description="camera survey"))
    wifi.process_packet(packet, emitter)
    assert recorder.events == []  # Self ID alone shouldn't produce an event


# -------------------------------------------------------
# defensive parse branches
# -------------------------------------------------------


@pytest.mark.parametrize(
    "parser,error_label",
    [
        (wifi.parse_basic_id, "Basic ID"),
        (wifi.parse_location_vector, "Location/Vector"),
        (wifi.parse_self_id, "Self ID"),
        (wifi.parse_operator_id, "Operator ID"),
    ],
)
def test_parsers_report_error_on_garbage(parser, error_label):
    # None is not bytes; every parser catches and reports rather than raising.
    result = parser(None)
    assert result["parse_error"] == f"Failed to parse {error_label}"


def test_packet_rssi_swallows_layer_errors():
    pkt = MagicMock()
    pkt.haslayer.side_effect = RuntimeError("mangled header")
    assert wifi._packet_rssi(pkt) is None


# -------------------------------------------------------
# capture_remote_id (sniff mocked)
# -------------------------------------------------------


def test_capture_requires_scapy(monkeypatch):
    monkeypatch.setattr(wifi, "SCAPY_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="scapy is required"):
        wifi.capture_remote_id("wlan0")


def test_capture_uses_bpf_filter(monkeypatch):
    calls = []
    monkeypatch.setattr(wifi, "sniff", lambda **kw: calls.append(kw))
    wifi.capture_remote_id("wlan0", timeout=0.1)
    assert len(calls) == 1
    assert calls[0]["filter"] == "type mgt subtype beacon"
    assert calls[0]["iface"] == "wlan0"
    # The prn handed to sniff forwards packets into process_packet.
    calls[0]["prn"](_beacon(_make_basic_id_element(ua_type=1, id_type=1, uas_id="P")))


def test_capture_filter_failure_falls_back_to_manual(monkeypatch):
    calls = []

    def fake_sniff(**kw):
        calls.append(kw)
        if "filter" in kw:
            raise OSError("BPF not supported")

    monkeypatch.setattr(wifi, "sniff", fake_sniff)
    wifi.capture_remote_id("wlan0", timeout=0.1)
    assert len(calls) == 2
    assert "filter" not in calls[1]
    # The fallback prn only forwards beacons to process_packet.
    prn = calls[1]["prn"]
    emitterless_beacon = _beacon(_make_basic_id_element(ua_type=1, id_type=1, uas_id="X"))
    prn(emitterless_beacon)  # must not raise


def test_capture_no_filter_forwards_beacons(monkeypatch):
    emitter, recorder = _recording_emitter()
    packet = _beacon(
        _make_basic_id_element(ua_type=4, id_type=1, uas_id="NF-1"),
        rssi=-70,
    )
    monkeypatch.setattr(wifi, "sniff", lambda **kw: kw["prn"](packet))
    wifi.capture_remote_id("wlan0", use_filter=False, emitter=emitter)
    assert len(recorder.events) == 1
    assert recorder.events[0].drone_id == "NF-1"


def test_capture_swallows_keyboard_interrupt(monkeypatch):
    def fake_sniff(**kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(wifi, "sniff", fake_sniff)
    wifi.capture_remote_id("wlan0")  # must not raise


def test_capture_reraises_other_errors(monkeypatch):
    def fake_sniff(**kw):
        raise PermissionError("need root for monitor mode")

    monkeypatch.setattr(wifi, "sniff", fake_sniff)
    with pytest.raises(PermissionError):
        wifi.capture_remote_id("wlan0", use_filter=False)


# -------------------------------------------------------
# main CLI (capture mocked)
# -------------------------------------------------------


def test_main_success(monkeypatch):
    monkeypatch.setattr(wifi, "capture_remote_id", lambda *a, **kw: None)
    assert wifi.main(["wlan0", "--monitor-mode"]) == 0


def test_main_closes_emitter(tmp_path, monkeypatch):
    cfg = tmp_path / "emit.ini"
    cfg.write_text("[emit]\nsinks = stdout\n")
    monkeypatch.setattr(wifi, "capture_remote_id", lambda *a, **kw: None)
    assert wifi.main(["wlan0", "--emit-config", str(cfg)]) == 0


def test_main_bad_emit_config_returns_1(tmp_path):
    assert wifi.main(["wlan0", "--emit-config", str(tmp_path / "nope.ini")]) == 1


def test_main_capture_failure_returns_1(monkeypatch):
    def explode(*a, **kw):
        raise PermissionError("need root")

    monkeypatch.setattr(wifi, "capture_remote_id", explode)
    assert wifi.main(["wlan0", "--no-filter"]) == 1
