"""Tests for the LoRa -> RabbitMQ bridge's pure message-shaping helpers.

These avoid any RabbitMQ or radio I/O; the async publishing path is integration
territory and not covered here.
"""

from drone_tools.drone_lora import DetectionEvent, DetectorType, ReceivedEvent
from drone_tools.lora_to_queue import event_to_dict, format_message, routing_key


def test_routing_key_lowercases_detector():
    assert routing_key("WIFI_REMOTE_ID") == "cddf.detection.wifi_remote_id"
    assert routing_key("AUDIO") == "cddf.detection.audio"


def test_event_to_dict_includes_all_fields():
    event = DetectionEvent(
        detector=DetectorType.BLE_REMOTE_ID,
        timestamp=1_700_000_000,
        lat=1.5,
        lon=-2.5,
        altitude=50,
        rssi=-70,
        drone_id="D-1",
        operator_id="OP-1",
    )
    d = event_to_dict(event)
    assert d["detector"] == "BLE_REMOTE_ID"  # enum rendered as name
    assert d["timestamp"] == 1_700_000_000
    assert d["lat"] == 1.5
    assert d["lon"] == -2.5
    assert d["altitude"] == 50
    assert d["rssi"] == -70
    assert d["drone_id"] == "D-1"
    assert d["operator_id"] == "OP-1"


def test_event_to_dict_preserves_none_fields():
    d = event_to_dict(DetectionEvent(detector=DetectorType.AUDIO, timestamp=1))
    assert d["lat"] is None
    assert d["drone_id"] is None


def test_format_message_envelope():
    received = ReceivedEvent(
        event=DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, timestamp=1, drone_id="Z"),
        from_id="!a1b2c3d4",
        rssi=-88,
        snr=6.5,
        hops_away=2,
    )
    msg = format_message(received, hostname="gateway-1")

    assert msg["hostname"] == "gateway-1"
    assert msg["source"] == "lora"
    assert msg["message_type"] == "detection"
    assert msg["detector"] == "WIFI_REMOTE_ID"
    assert msg["event"]["drone_id"] == "Z"
    assert msg["lora"] == {
        "from_id": "!a1b2c3d4",
        "rssi": -88,
        "snr": 6.5,
        "hops_away": 2,
    }
    # timestamp is the relay time and must be an ISO8601 string.
    assert "T" in msg["timestamp"]


def test_format_message_is_json_serializable():
    import json

    received = ReceivedEvent(event=DetectionEvent(detector=DetectorType.RF, timestamp=1))
    body = json.dumps(format_message(received, hostname="h"))
    assert "cddf" not in body  # routing key isn't in the body
    assert '"source": "lora"' in body
