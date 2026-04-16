import struct

import pytest

import drone_tools.mock_sniffle_remote_id as mock

SAMPLE = mock.SAMPLE_DRONES[0]


# -------------------------------------------------------
# MockSniffleDrone message generation
# -------------------------------------------------------


def test_basic_id_message_layout():
    drone = mock.MockSniffleDrone(SAMPLE)
    msg = drone.generate_basic_id_message()
    assert len(msg) == 25
    assert msg[0] == 0x00  # msg type
    assert msg[1] == SAMPLE["ua_type"]
    assert msg[2] == 1  # id type (Serial Number)
    # UAS ID is placed at bytes 3:23, null-padded
    recovered = msg[3:23].rstrip(b"\x00").decode("utf-8")
    assert recovered == SAMPLE["uas_id"]


def test_basic_id_message_truncates_long_uas_id():
    drone_data = dict(SAMPLE, uas_id="X" * 40)
    drone = mock.MockSniffleDrone(drone_data)
    msg = drone.generate_basic_id_message()
    # Only 20 bytes of UAS ID land in the buffer
    assert msg[3:23] == b"X" * 20


def test_location_message_roundtrip():
    drone = mock.MockSniffleDrone(SAMPLE)
    # Pin state to known values so we can reverse the encoding
    drone.direction = 90.0
    drone.speed_h = 5.0
    drone.speed_v = -1.0
    drone.latitude = 37.7749
    drone.longitude = -122.4194
    drone.altitude = 150.0
    drone.height = 100.0

    msg = drone.generate_location_message()
    assert len(msg) == 26
    assert msg[0] == 0x01
    assert msg[1] == 0x01  # status airborne

    direction = struct.unpack("<H", msg[2:4])[0] / 100.0
    speed_h = struct.unpack("<H", msg[4:6])[0] / 100.0
    speed_v = struct.unpack("<h", msg[6:8])[0] / 100.0
    lat = struct.unpack("<i", msg[8:12])[0] / 1e7
    lon = struct.unpack("<i", msg[12:16])[0] / 1e7
    alt = struct.unpack("<h", msg[16:18])[0] / 2.0
    height = struct.unpack("<h", msg[18:20])[0] / 2.0

    assert direction == pytest.approx(90.0, abs=0.01)
    assert speed_h == pytest.approx(5.0, abs=0.01)
    assert speed_v == pytest.approx(-1.0, abs=0.01)
    assert lat == pytest.approx(37.7749, abs=1e-4)
    assert lon == pytest.approx(-122.4194, abs=1e-4)
    assert alt == pytest.approx(150.0, abs=0.5)
    assert height == pytest.approx(100.0, abs=0.5)


def test_self_id_message_layout():
    drone = mock.MockSniffleDrone(SAMPLE)
    msg = drone.generate_self_id_message()
    assert len(msg) == 25
    assert msg[0] == 0x03
    assert msg[1] == 0x00  # description type = Text
    desc = msg[2:].rstrip(b"\x00").decode("utf-8")
    assert desc == SAMPLE["description"][:23]


def test_operator_id_message_layout():
    drone = mock.MockSniffleDrone(SAMPLE)
    msg = drone.generate_operator_id_message()
    assert len(msg) == 25
    assert msg[0] == 0x05
    assert msg[1] == 1
    op = msg[2:22].rstrip(b"\x00").decode("utf-8")
    assert op == SAMPLE["operator_id"]


def test_system_message_layout():
    drone = mock.MockSniffleDrone(SAMPLE)
    msg = drone.generate_system_message()
    assert len(msg) == 24
    assert msg[0] == 0x04
    assert msg[1] == 0x01
    op_lat = struct.unpack("<i", msg[2:6])[0] / 1e7
    op_lon = struct.unpack("<i", msg[6:10])[0] / 1e7
    # The drone's op position was randomized around base; stay within a loose tolerance.
    assert op_lat == pytest.approx(SAMPLE["base_lat"], abs=0.01)
    assert op_lon == pytest.approx(SAMPLE["base_lon"], abs=0.01)


# -------------------------------------------------------
# MockSniffleDrone.update_position
# -------------------------------------------------------


def test_update_position_clamps_altitude(monkeypatch):
    drone = mock.MockSniffleDrone(SAMPLE)
    # Force a big update interval and a downward vertical speed to push altitude below floor.
    drone.last_update = 0
    drone.speed_v = -100.0
    drone.altitude = 60.0
    drone.update_position()
    assert 50 <= drone.altitude <= 400

    # Push altitude above ceiling
    drone.last_update = 0
    drone.speed_v = 500.0
    drone.altitude = 380.0
    drone.update_position()
    assert drone.altitude <= 400


def test_update_position_noop_within_half_second():
    drone = mock.MockSniffleDrone(SAMPLE)
    lat_before = drone.latitude
    lon_before = drone.longitude
    # Set last_update to "now" so dt is < 0.5 and update is skipped.
    import time as _time

    drone.last_update = _time.time()
    drone.update_position()
    assert drone.latitude == lat_before
    assert drone.longitude == lon_before


# -------------------------------------------------------
# MockSniffle helpers and output
# -------------------------------------------------------


def test_format_hex_dump():
    sniffle = mock.MockSniffle()
    assert sniffle.format_hex_dump(b"\x01\xab\xcd") == "01 AB CD"
    assert sniffle.format_hex_dump(b"") == ""


def test_generate_sniffle_packet_output_contains_expected_fields():
    sniffle = mock.MockSniffle(verbose=True)
    drone = sniffle.drones[0]
    msg = drone.generate_basic_id_message()
    out = sniffle.generate_sniffle_packet_output(drone, msg, rssi=-55)
    assert "BLE Advertisement" in out
    assert drone.mac_address in out
    assert "-55 dBm" in out
    assert "Service UUID: FFFA" in out
    assert "Message Type: Basic ID" in out  # verbose branch
    assert drone.uas_id in out


def test_generate_sniffle_packet_output_location_verbose_decodes_position():
    sniffle = mock.MockSniffle(verbose=True)
    drone = sniffle.drones[0]
    # Pin to known values
    drone.latitude = 40.0
    drone.longitude = -75.0
    drone.altitude = 200.0
    msg = drone.generate_location_message()
    out = sniffle.generate_sniffle_packet_output(drone, msg, rssi=-60)
    assert "Position: 40.000000, -75.000000 @ 200.0m" in out


def test_generate_wireshark_style_output_contains_mac_and_protocol():
    sniffle = mock.MockSniffle(verbose=True)
    drone = sniffle.drones[0]
    msg = drone.generate_self_id_message()
    out = sniffle.generate_wireshark_style_output(drone, msg, rssi=-65)
    assert drone.mac_address in out
    assert "BT-BLE" in out
    assert "Remote-ID" in out
    assert "Self ID" in out  # verbose decoded message type


# -------------------------------------------------------
# MockSniffle.run_simulation
# -------------------------------------------------------


def test_run_simulation_writes_to_output_file(tmp_path, monkeypatch):
    # Remove the per-packet sleep so the test runs fast.
    monkeypatch.setattr(mock.time, "sleep", lambda _s: None)

    out_path = tmp_path / "capture.txt"
    sniffle = mock.MockSniffle(verbose=False, output_file=str(out_path))

    # Short duration; loop checks time >= start+duration before generating.
    sniffle.run_simulation(duration=1, output_format="sniffle")

    # duration=1 combined with sleep=0 and time advancing should produce >= 1 packet.
    assert out_path.exists()
    content = out_path.read_text()
    assert "BLE Advertisement" in content


def test_run_simulation_stdout_when_no_file(monkeypatch, capsys):
    monkeypatch.setattr(mock.time, "sleep", lambda _s: None)
    sniffle = mock.MockSniffle(verbose=False)
    sniffle.run_simulation(duration=1, output_format="sniffle")
    captured = capsys.readouterr()
    assert "BLE Advertisement" in captured.out


# -------------------------------------------------------
# main
# -------------------------------------------------------


def test_main_returns_zero_on_clean_run(monkeypatch):
    monkeypatch.setattr(mock.MockSniffle, "run_simulation", lambda self, **kw: None)
    monkeypatch.setattr(mock.sys, "argv", ["mock"])
    assert mock.main() == 0


def test_main_returns_zero_on_keyboard_interrupt(monkeypatch):
    def boom(self, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(mock.MockSniffle, "run_simulation", boom)
    monkeypatch.setattr(mock.sys, "argv", ["mock"])
    assert mock.main() == 0


def test_main_returns_one_on_exception(monkeypatch, capsys):
    def boom(self, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(mock.MockSniffle, "run_simulation", boom)
    monkeypatch.setattr(mock.sys, "argv", ["mock"])
    rc = mock.main()
    assert rc == 1
    assert "boom" in capsys.readouterr().err
