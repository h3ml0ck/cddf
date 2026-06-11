"""Tests for the LoRa -> RabbitMQ bridge.

Covers message formatting, config validation, the LoraToQueue class
construction, and the enqueue/on_event paths. Radio and broker I/O are mocked.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from drone_tools.drone_lora import DetectionEvent, DetectorType, ReceivedEvent
from drone_tools.lora_to_queue import (
    EVENT_QUEUE_MAXSIZE,
    LoraToQueue,
    event_to_dict,
    format_message,
    main,
    routing_key,
)

# --- message helpers (pure functions) ---------------------------------------


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
    assert d["detector"] == "BLE_REMOTE_ID"
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
    assert msg["lora"] == {"from_id": "!a1b2c3d4", "rssi": -88, "snr": 6.5, "hops_away": 2}
    assert "T" in msg["timestamp"]


def test_format_message_is_json_serializable():
    import json

    received = ReceivedEvent(event=DetectionEvent(detector=DetectorType.RF, timestamp=1))
    body = json.dumps(format_message(received, hostname="h"))
    assert '"source": "lora"' in body


# --- config loading / validation -------------------------------------------


def _write_config(tmp_path, content):
    cfg = tmp_path / "config.ini"
    cfg.write_text(content)
    return str(cfg)


_VALID_CONFIG = """\
[rabbitmq]
host = localhost
port = 5672
username = test
password = test
virtual_host = /
exchange = test_exchange
exchange_type = topic

[logging]
level = DEBUG
"""


def test_lora_to_queue_loads_valid_config(tmp_path, monkeypatch):
    monkeypatch.setattr("drone_tools.amqp.AIO_PIKA_AVAILABLE", True)
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    with patch("drone_tools.amqp.AmqpPublisher"):
        bridge = LoraToQueue(cfg_path)
    assert bridge.config.get("rabbitmq", "host") == "localhost"


def test_lora_to_queue_exits_on_missing_config(tmp_path):
    with pytest.raises(SystemExit):
        LoraToQueue(str(tmp_path / "nonexistent.ini"))


def test_lora_to_queue_exits_on_missing_rabbitmq_section(tmp_path):
    cfg_path = _write_config(tmp_path, "[logging]\nlevel = INFO\n")
    with pytest.raises(SystemExit):
        LoraToQueue(cfg_path)


def test_lora_to_queue_exits_on_missing_required_fields(tmp_path):
    cfg_path = _write_config(tmp_path, "[rabbitmq]\nhost = x\n")
    with pytest.raises(SystemExit):
        LoraToQueue(cfg_path)


def test_lora_to_queue_exits_on_bad_port(tmp_path):
    bad = _VALID_CONFIG.replace("port = 5672", "port = abc")
    cfg_path = _write_config(tmp_path, bad)
    with pytest.raises(SystemExit):
        LoraToQueue(cfg_path)


def test_lora_to_queue_exits_on_port_out_of_range(tmp_path):
    bad = _VALID_CONFIG.replace("port = 5672", "port = 99999")
    cfg_path = _write_config(tmp_path, bad)
    with pytest.raises(SystemExit):
        LoraToQueue(cfg_path)


def test_lora_to_queue_warns_on_default_creds(tmp_path, capsys):
    guest = _VALID_CONFIG.replace("username = test", "username = guest")
    cfg_path = _write_config(tmp_path, guest)
    LoraToQueue(cfg_path)
    assert "WARNING" in capsys.readouterr().err


# --- enqueue / on_event paths ----------------------------------------------


def test_enqueue_drops_when_queue_full(tmp_path, monkeypatch):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    bridge = LoraToQueue(cfg_path)
    bridge._queue = asyncio.Queue(maxsize=1)
    bridge._queue.put_nowait("placeholder")

    received = ReceivedEvent(event=DetectionEvent(detector=DetectorType.AUDIO, timestamp=1))
    bridge._enqueue(received)  # should not raise, just drop


def test_enqueue_noop_without_queue(tmp_path):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    bridge = LoraToQueue(cfg_path)
    assert bridge._queue is None
    received = ReceivedEvent(event=DetectionEvent(detector=DetectorType.AUDIO, timestamp=1))
    bridge._enqueue(received)  # should not raise


def test_on_event_forwards_to_loop(tmp_path, monkeypatch):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    bridge = LoraToQueue(cfg_path)
    loop = MagicMock()
    bridge._loop = loop
    received = ReceivedEvent(event=DetectionEvent(detector=DetectorType.RF, timestamp=1))
    bridge._on_event(received)
    loop.call_soon_threadsafe.assert_called_once()


def test_on_event_noop_without_loop(tmp_path):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    bridge = LoraToQueue(cfg_path)
    assert bridge._loop is None
    received = ReceivedEvent(event=DetectionEvent(detector=DetectorType.RF, timestamp=1))
    bridge._on_event(received)  # should not raise


# --- CLI entry point -------------------------------------------------------


def test_main_missing_deps(monkeypatch):
    monkeypatch.setattr("drone_tools.lora_to_queue.AIO_PIKA_AVAILABLE", False)
    monkeypatch.setattr("drone_tools.lora_to_queue.MESHTASTIC_AVAILABLE", False)
    ret = main(["--config", "x.ini"])
    assert ret == 1


def test_main_keyboard_interrupt(tmp_path, monkeypatch):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    monkeypatch.setattr("drone_tools.lora_to_queue.AIO_PIKA_AVAILABLE", True)
    monkeypatch.setattr("drone_tools.lora_to_queue.MESHTASTIC_AVAILABLE", True)
    def fake_run(coro):
        coro.close()  # consume the coroutine so no "never awaited" warning leaks
        raise KeyboardInterrupt

    monkeypatch.setattr("asyncio.run", fake_run)
    ret = main(["--config", cfg_path])
    assert ret == 0
