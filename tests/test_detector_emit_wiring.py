"""Tests for wiring the emitter into detectors.

Covers the per-detector event mappers and the shared --emit-config CLI helper.
These need neither radio/broker nor scapy/bleak (the optional radio imports in
those modules are guarded).
"""

import argparse

import pytest

from drone_tools.detection_emit import DetectionEmitter, add_emit_args, open_emitter
from drone_tools.drone_ble_remote_id import _event_from_ble
from drone_tools.drone_lora import DetectorType
from drone_tools.drone_wifi_remote_id import _event_from_remote_id

# --- Wi-Fi Remote ID mapper ------------------------------------------------


def test_wifi_event_from_basic_id_only():
    event = _event_from_remote_id({"uas_id": "DRONE-1"}, rssi=-72)
    assert event is not None
    assert event.detector == DetectorType.WIFI_REMOTE_ID
    assert event.drone_id == "DRONE-1"
    assert event.lat is None
    assert event.rssi == -72


def test_wifi_event_combines_id_and_location():
    fields = {
        "uas_id": "DRONE-1",
        "latitude": 37.7749,
        "longitude": -122.4194,
        "altitude": 120.0,
        "operator_id": "OP-1",
    }
    event = _event_from_remote_id(fields, rssi=None)
    assert event.drone_id == "DRONE-1"
    assert event.lat == pytest.approx(37.7749)
    assert event.lon == pytest.approx(-122.4194)
    assert event.altitude == 120  # coerced to int
    assert event.operator_id == "OP-1"
    assert event.rssi is None


def test_wifi_event_none_without_id_or_location():
    # A vendor element that decoded only a Self ID description isn't emittable.
    assert _event_from_remote_id({"description": "hello"}, rssi=-50) is None


def test_wifi_event_empty_uas_id_treated_as_absent():
    assert _event_from_remote_id({"uas_id": ""}, rssi=None) is None


# --- BLE Remote ID mapper --------------------------------------------------


def test_ble_event_from_basic_id():
    event = _event_from_ble({"uas_id": "BLE-DRONE"}, rssi=-88)
    assert event is not None
    assert event.detector == DetectorType.BLE_REMOTE_ID
    assert event.drone_id == "BLE-DRONE"
    assert event.rssi == -88


def test_ble_event_location_only():
    event = _event_from_ble({"latitude": 1.5, "longitude": -2.5}, rssi=None)
    assert event is not None
    assert event.drone_id is None
    assert event.lat == pytest.approx(1.5)


def test_ble_event_none_without_content():
    assert _event_from_ble({"description_type": "Text"}, rssi=-60) is None


# --- shared --emit-config helper -------------------------------------------


def test_add_emit_args_adds_option():
    parser = argparse.ArgumentParser()
    add_emit_args(parser)
    args = parser.parse_args(["--emit-config", "x.ini"])
    assert args.emit_config == "x.ini"


def test_open_emitter_none_without_flag():
    assert open_emitter(argparse.Namespace(emit_config=None)) is None


def test_open_emitter_builds_and_starts(tmp_path):
    cfg = tmp_path / "emit.ini"
    cfg.write_text("[emit]\nsinks = stdout\n")
    emitter = open_emitter(argparse.Namespace(emit_config=str(cfg)))
    assert isinstance(emitter, DetectionEmitter)
    assert len(emitter.sinks) == 1
    emitter.close()


def test_open_emitter_bad_config_raises(tmp_path):
    cfg = tmp_path / "bad.ini"
    cfg.write_text("[emit]\nsinks = nonsense\n")
    with pytest.raises(ValueError, match="unknown sink"):
        open_emitter(argparse.Namespace(emit_config=str(cfg)))
