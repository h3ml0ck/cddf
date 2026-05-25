"""Tests for the LoRa detection-event codec.

These cover the wire format only (encode_event / decode_event), which has no
hardware or meshtastic dependency, so they run anywhere.
"""

import struct

import pytest

from drone_tools.drone_lora import (
    PROTOCOL_VERSION,
    DetectionEvent,
    DetectionThrottle,
    DetectorType,
    decode_event,
    default_throttle_key,
    encode_event,
)


def _assert_roundtrip(event: DetectionEvent) -> DetectionEvent:
    decoded = decode_event(encode_event(event))
    assert decoded.detector == event.detector
    assert decoded.timestamp == event.timestamp
    return decoded


def test_minimal_event_roundtrip():
    event = DetectionEvent(detector=DetectorType.AUDIO, timestamp=1_700_000_000)
    decoded = _assert_roundtrip(event)
    # Optional fields stay absent.
    assert decoded.lat is None
    assert decoded.lon is None
    assert decoded.altitude is None
    assert decoded.rssi is None
    assert decoded.drone_id is None
    assert decoded.operator_id is None


def test_minimal_event_is_header_only():
    # No optional fields set -> just the 7-byte header on the wire.
    assert len(encode_event(DetectionEvent(detector=DetectorType.RF, timestamp=1))) == 7


def test_full_event_roundtrip():
    event = DetectionEvent(
        detector=DetectorType.WIFI_REMOTE_ID,
        timestamp=1_700_000_001,
        lat=37.7749,
        lon=-122.4194,
        altitude=120,
        rssi=-67,
        drone_id="TEST-1581F4F2C8A1",
        operator_id="OP-FAA-12345",
    )
    decoded = _assert_roundtrip(event)
    # Fixed-point coords keep ~1cm precision.
    assert decoded.lat == pytest.approx(event.lat, abs=1e-6)
    assert decoded.lon == pytest.approx(event.lon, abs=1e-6)
    assert decoded.altitude == 120
    assert decoded.rssi == -67
    assert decoded.drone_id == "TEST-1581F4F2C8A1"
    assert decoded.operator_id == "OP-FAA-12345"


def test_negative_coordinates_and_altitude():
    event = DetectionEvent(
        detector=DetectorType.BLE_REMOTE_ID,
        timestamp=42,
        lat=-33.8688,
        lon=151.2093,
        altitude=-15,
        rssi=-110,
    )
    decoded = _assert_roundtrip(event)
    assert decoded.lat == pytest.approx(-33.8688, abs=1e-6)
    assert decoded.lon == pytest.approx(151.2093, abs=1e-6)
    assert decoded.altitude == -15
    assert decoded.rssi == -110


def test_fits_in_meshtastic_payload():
    # Worst case: every field set with max-length IDs must stay under the
    # ~237-byte Meshtastic data payload limit.
    event = DetectionEvent(
        detector=DetectorType.RTL_POWER,
        timestamp=1_700_000_000,
        lat=89.9999999,
        lon=-179.9999999,
        altitude=32000,
        rssi=-128,
        drone_id="X" * 64,
        operator_id="Y" * 64,
    )
    assert len(encode_event(event)) < 237


def test_unknown_detector_decodes_as_unknown():
    # A detector byte outside the enum must not blow up the receiver.
    frame = struct.pack("<BBIB", PROTOCOL_VERSION, 99, 1234, 0)
    decoded = decode_event(frame)
    assert decoded.detector == DetectorType.UNKNOWN
    assert decoded.timestamp == 1234


def test_unsupported_version_rejected():
    frame = struct.pack("<BBIB", PROTOCOL_VERSION + 1, 0, 0, 0)
    with pytest.raises(ValueError, match="unsupported protocol version"):
        decode_event(frame)


def test_frame_too_short_rejected():
    with pytest.raises(ValueError, match="frame too short"):
        decode_event(b"\x01\x02")


def test_truncated_optional_field_rejected():
    # Flag says a location follows, but the body is missing.
    frame = struct.pack("<BBIB", PROTOCOL_VERSION, 1, 0, 0x01)  # FLAG_LOCATION
    with pytest.raises(ValueError, match="truncated frame"):
        decode_event(frame)


def test_long_id_truncated_to_255_bytes():
    event = DetectionEvent(detector=DetectorType.AUDIO, timestamp=1, drone_id="Z" * 300)
    decoded = decode_event(encode_event(event))
    assert decoded.drone_id is not None
    assert len(decoded.drone_id) == 255


def test_timestamp_defaults_to_now():
    before = int(__import__("time").time())
    event = DetectionEvent(detector=DetectorType.AUDIO)
    assert event.timestamp >= before


# --- DetectionThrottle -----------------------------------------------------


class _FakeClock:
    """Controllable monotonic clock for deterministic throttle tests."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_default_key_prefers_drone_id():
    with_id = DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, drone_id="ABC")
    no_id = DetectionEvent(detector=DetectorType.AUDIO)
    assert default_throttle_key(with_id) == "id:ABC"
    assert default_throttle_key(no_id) == "det:AUDIO"


def test_throttle_suppresses_repeat_within_interval():
    clock = _FakeClock()
    throttle = DetectionThrottle(interval=30.0, time_fn=clock)
    event = DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, drone_id="DRONE-1")

    assert throttle.allow(event) is True  # first one goes
    clock.advance(10)
    assert throttle.allow(event) is False  # still within interval
    clock.advance(25)  # now 35s since first
    assert throttle.allow(event) is True  # interval elapsed


def test_throttle_keys_are_independent():
    clock = _FakeClock()
    throttle = DetectionThrottle(interval=30.0, time_fn=clock)
    a = DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, drone_id="A")
    b = DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, drone_id="B")

    assert throttle.allow(a) is True
    assert throttle.allow(b) is True  # different drone, not suppressed
    assert throttle.allow(a) is False


def test_throttle_same_drone_across_detectors_collapses():
    # Default key is the drone_id, so Wi-Fi + BLE sightings of one drone
    # collapse to a single relayed event.
    clock = _FakeClock()
    throttle = DetectionThrottle(interval=30.0, time_fn=clock)
    wifi = DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, drone_id="SHARED")
    ble = DetectionEvent(detector=DetectorType.BLE_REMOTE_ID, drone_id="SHARED")

    assert throttle.allow(wifi) is True
    assert throttle.allow(ble) is False


def test_throttle_custom_key_fn():
    clock = _FakeClock()
    # Key on detector only, so any RF detection throttles regardless of id.
    throttle = DetectionThrottle(interval=30.0, key_fn=lambda e: e.detector.name, time_fn=clock)
    assert throttle.allow(DetectionEvent(detector=DetectorType.RF, drone_id="X")) is True
    assert throttle.allow(DetectionEvent(detector=DetectorType.RF, drone_id="Y")) is False


def test_throttle_prunes_expired_keys():
    clock = _FakeClock()
    throttle = DetectionThrottle(interval=10.0, max_keys=5, time_fn=clock)
    # Fill past max_keys with distinct keys, then let them expire.
    for i in range(10):
        throttle.allow(DetectionEvent(detector=DetectorType.AUDIO, drone_id=f"d{i}"))
    clock.advance(20)  # everything is now expired
    # A new allow triggers a prune that clears the stale keys.
    throttle.allow(DetectionEvent(detector=DetectorType.AUDIO, drone_id="fresh"))
    assert len(throttle._last_sent) <= throttle.max_keys


def test_throttle_negative_interval_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        DetectionThrottle(interval=-1.0)
