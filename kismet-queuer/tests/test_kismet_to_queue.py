"""Tests for kismet_to_queue: config validation, message formatting, routing.

These avoid any live WebSocket or RabbitMQ I/O; the async paths are tested
with mock objects.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# kismet_to_queue lives outside the main package tree and requires websockets
# and aio-pika at import time. Mock them if they're not installed.
_src = str(Path(__file__).resolve().parent.parent / "src")
sys.path.insert(0, _src)

try:
    import websockets  # noqa: F401
except ImportError:
    sys.modules["websockets"] = MagicMock()
    sys.modules["websockets.exceptions"] = MagicMock()

try:
    import aio_pika  # noqa: F401
except ImportError:
    mock_aio = MagicMock()
    mock_aio.ExchangeType = MagicMock(side_effect=lambda x: x)
    mock_aio.DeliveryMode = MagicMock()
    mock_aio.DeliveryMode.PERSISTENT = 2
    sys.modules["aio_pika"] = mock_aio

import kismet_to_queue as ktq


# --- fixtures ---------------------------------------------------------------


_VALID_CONFIG = """\
[kismet]
host = localhost
port = 2501

[rabbitmq]
host = localhost
port = 5672
username = test
password = test
virtual_host = /
exchange = kismet_events
exchange_type = topic

[logging]
level = DEBUG

[general]
reconnect_delay = 5
max_reconnect_attempts = 10
"""


def _write_config(tmp_path: Path, content: str) -> str:
    cfg = tmp_path / "config.ini"
    cfg.write_text(content)
    return str(cfg)


# --- config validation ------------------------------------------------------


def test_loads_valid_config(tmp_path):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    with patch.object(ktq, "aio_pika"):
        obj = ktq.KismetToQueue(cfg_path)
    assert obj.config.get("rabbitmq", "host") == "localhost"


def test_exits_on_missing_config(tmp_path):
    with pytest.raises(SystemExit):
        ktq.KismetToQueue(str(tmp_path / "nope.ini"))


def test_exits_on_missing_kismet_section(tmp_path):
    no_kismet = _VALID_CONFIG.replace("[kismet]\n", "").replace("host = localhost\nport = 2501\n", "")
    cfg_path = _write_config(tmp_path, no_kismet)
    with pytest.raises(SystemExit):
        ktq.KismetToQueue(cfg_path)


def test_exits_on_missing_rabbitmq_fields(tmp_path):
    cfg_path = _write_config(tmp_path, "[kismet]\nhost = x\nport = 2501\n[rabbitmq]\nhost = x\n")
    with pytest.raises(SystemExit):
        ktq.KismetToQueue(cfg_path)


def test_exits_on_bad_port(tmp_path):
    bad = _VALID_CONFIG.replace("port = 2501", "port = abc")
    cfg_path = _write_config(tmp_path, bad)
    with pytest.raises(SystemExit):
        ktq.KismetToQueue(cfg_path)


def test_exits_on_port_out_of_range(tmp_path):
    bad = _VALID_CONFIG.replace("port = 5672", "port = 99999")
    cfg_path = _write_config(tmp_path, bad)
    with pytest.raises(SystemExit):
        ktq.KismetToQueue(cfg_path)


def test_exits_on_bad_reconnect_delay(tmp_path):
    bad = _VALID_CONFIG.replace("reconnect_delay = 5", "reconnect_delay = 0")
    cfg_path = _write_config(tmp_path, bad)
    with pytest.raises(SystemExit):
        ktq.KismetToQueue(cfg_path)


def test_warns_on_default_creds(tmp_path, capsys):
    guest = _VALID_CONFIG.replace("username = test", "username = guest")
    cfg_path = _write_config(tmp_path, guest)
    ktq.KismetToQueue(cfg_path)
    assert "WARNING" in capsys.readouterr().err


# --- message formatting ----------------------------------------------------


def test_format_message_device(tmp_path):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    obj = ktq.KismetToQueue(cfg_path)
    raw = {"kismet_device": {"kismet_device_base_type": "Wi-Fi AP"}}
    msg = obj._format_message(raw)
    assert msg["message_type"] == "device"
    assert msg["source"] == "kismet"
    assert msg["device_data"] == raw["kismet_device"]
    assert "T" in msg["timestamp"]


def test_format_message_alert(tmp_path):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    obj = ktq.KismetToQueue(cfg_path)
    msg = obj._format_message({"kismet_alert": {"severity": "high"}})
    assert msg["message_type"] == "alert"


def test_format_message_unknown(tmp_path):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    obj = ktq.KismetToQueue(cfg_path)
    msg = obj._format_message({"other_key": "value"})
    assert msg["message_type"] == "unknown"


# --- routing key ------------------------------------------------------------


def test_routing_key_device(tmp_path):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    obj = ktq.KismetToQueue(cfg_path)
    key = obj._get_routing_key({"message_type": "device", "device_data": {"kismet_device_base_type": "Wi-Fi AP"}})
    assert key == "kismet.device.Wi-Fi AP"


def test_routing_key_unknown(tmp_path):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    obj = ktq.KismetToQueue(cfg_path)
    key = obj._get_routing_key({})
    assert key == "kismet.unknown.unknown"


# --- max message size -------------------------------------------------------


def test_max_message_size_constant():
    assert ktq.MAX_MESSAGE_SIZE == 1_048_576


# --- main entry point -------------------------------------------------------


def test_main_calls_asyncio_run(tmp_path, monkeypatch):
    cfg_path = _write_config(tmp_path, _VALID_CONFIG)
    monkeypatch.setattr(sys, "argv", ["kismet_to_queue", cfg_path])

    def fake_run(coro):
        coro.close()  # consume the coroutine so no "never awaited" warning leaks
        raise KeyboardInterrupt

    with patch("asyncio.run", side_effect=fake_run):
        ktq.main()  # should not raise
