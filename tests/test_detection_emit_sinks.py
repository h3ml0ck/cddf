"""Tests for the transport sinks and CLI of detection_emit.

Covers the RabbitMQSink background-loop lifecycle, LoRaSink delegation to
MeshLink, the config-driven sink builders, and the drone-emit-test entry
point. No live broker or radio: aio-pika's publisher and the mesh link are
replaced with fakes.
"""

import asyncio
import configparser
import threading
from unittest.mock import MagicMock

import pytest

import drone_tools.detection_emit as de
from drone_tools.detection_emit import (
    LoRaSink,
    RabbitMQSink,
    StdoutSink,
    build_emitter,
    load_emitter,
    main,
    routing_key,
)
from drone_tools.drone_lora import DetectionEvent, DetectorType


def _event(**kwargs) -> DetectionEvent:
    defaults = dict(detector=DetectorType.WIFI_REMOTE_ID, timestamp=1700000000)
    defaults.update(kwargs)
    return DetectionEvent(**defaults)


def _config(text: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read_string(text)
    return config


_RABBITMQ_INI = """
[emit]
sinks = rabbitmq

[rabbitmq]
host = broker.local
port = 5672
username = u
password = p
exchange = cddf
"""


# --- StdoutSink --------------------------------------------------------------


def test_stdout_sink_includes_location_and_rssi(capsys):
    StdoutSink().emit(_event(lat=37.7749, lon=-122.4194, rssi=-67))
    out = capsys.readouterr().out
    assert "loc=37.774900,-122.419400" in out
    assert "rssi=-67dBm" in out


# --- LoRaSink ----------------------------------------------------------------


def test_lora_sink_requires_meshtastic(monkeypatch):
    monkeypatch.setattr(de, "MESHTASTIC_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="meshtastic is required"):
        LoRaSink()


@pytest.fixture
def fake_mesh_link(monkeypatch):
    """Patch MeshLink with a recording fake and enable the meshtastic gate."""
    link = MagicMock()
    monkeypatch.setattr(de, "MESHTASTIC_AVAILABLE", True)
    monkeypatch.setattr(de, "MeshLink", MagicMock(return_value=link))
    return link


def test_lora_sink_lifecycle_delegates_to_mesh_link(fake_mesh_link):
    sink = LoRaSink(device="/dev/ttyUSB0")
    assert sink.start() is sink
    fake_mesh_link.connect.assert_called_once()

    event = _event(drone_id="ID-1")
    sink.emit(event)
    fake_mesh_link.broadcast.assert_called_once_with(event)

    sink.close()
    fake_mesh_link.close.assert_called_once()


# --- RabbitMQSink ------------------------------------------------------------


def test_rabbitmq_sink_requires_aio_pika(monkeypatch):
    monkeypatch.setattr(de, "AIO_PIKA_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="aio-pika is required"):
        RabbitMQSink(host="h", port=5672, username="u", password="p", exchange="ex")


class _FakePublisher:
    """In-memory AmqpPublisher stand-in recording every publish."""

    def __init__(self, *args, connect_results=None, **kwargs):
        self.published: list[tuple[str, dict]] = []
        self.closed = threading.Event()
        self._connect_results = list(connect_results or [True])

    async def connect(self) -> bool:
        if len(self._connect_results) > 1:
            return self._connect_results.pop(0)
        return self._connect_results[0]

    async def publish(self, key: str, message: dict) -> bool:
        self.published.append((key, message))
        return True

    async def close(self) -> None:
        self.closed.set()


def _make_sink(monkeypatch, **publisher_kwargs) -> tuple[RabbitMQSink, _FakePublisher]:
    monkeypatch.setattr(de, "AIO_PIKA_AVAILABLE", True)
    fake = _FakePublisher(**publisher_kwargs)
    monkeypatch.setattr(de, "AmqpPublisher", lambda *a, **kw: fake)
    sink = RabbitMQSink(host="broker", port=5672, username="u", password="p", exchange="cddf", hostname="node-1")
    return sink, fake


def test_rabbitmq_sink_publishes_emitted_event(monkeypatch):
    sink, fake = _make_sink(monkeypatch)
    sink.start()
    try:
        sink.emit(_event(drone_id="1581F4ABC", rssi=-60))
    finally:
        sink.close()  # close drains the queue before stopping

    assert len(fake.published) == 1
    key, message = fake.published[0]
    assert key == routing_key("WIFI_REMOTE_ID")
    assert message["hostname"] == "node-1"
    assert message["message_type"] == "detection"
    assert message["event"]["drone_id"] == "1581F4ABC"
    assert fake.closed.is_set()


def test_rabbitmq_sink_emit_before_start_is_noop(monkeypatch):
    sink, fake = _make_sink(monkeypatch)
    sink.emit(_event())  # no loop yet; must not raise
    assert fake.published == []


def test_rabbitmq_sink_close_without_start_is_noop(monkeypatch):
    sink, _ = _make_sink(monkeypatch)
    sink.close()  # must not raise


def test_rabbitmq_sink_enqueue_drops_on_overflow(monkeypatch, caplog):
    sink, _ = _make_sink(monkeypatch)
    sink._aqueue = asyncio.Queue(maxsize=1)
    sink._enqueue({"detector": "AUDIO"})
    with caplog.at_level("WARNING"):
        sink._enqueue({"detector": "AUDIO"})
    assert "dropping detection" in caplog.text
    assert sink._aqueue.qsize() == 1


def test_rabbitmq_sink_enqueue_before_queue_exists(monkeypatch):
    sink, _ = _make_sink(monkeypatch)
    sink._enqueue({"detector": "AUDIO"})  # _aqueue is None; must not raise


def test_rabbitmq_sink_connect_retries_until_success(monkeypatch):
    sink, fake = _make_sink(monkeypatch, connect_results=[False, True])

    async def run():
        sink._stop = asyncio.Event()
        sink._publisher_obj = fake
        # Shrink the retry backoff so the test doesn't sleep for real.
        await asyncio.wait_for(sink._connect_with_retry(), timeout=5.0)

    monkeypatch.setattr(de, "_START_TIMEOUT", 5.0)
    asyncio.run(run())
    assert fake._connect_results == [True]


def test_rabbitmq_sink_connect_retry_aborts_on_stop(monkeypatch):
    sink, fake = _make_sink(monkeypatch, connect_results=[False])

    async def run():
        sink._stop = asyncio.Event()
        sink._stop.set()
        sink._publisher_obj = fake
        await asyncio.wait_for(sink._connect_with_retry(), timeout=5.0)

    asyncio.run(run())  # returns immediately without connecting


# --- config-driven construction ---------------------------------------------


def test_build_emitter_constructs_rabbitmq_sink(monkeypatch):
    monkeypatch.setattr(de, "AIO_PIKA_AVAILABLE", True)
    monkeypatch.setattr(de, "AmqpPublisher", MagicMock())
    emitter = build_emitter(_config(_RABBITMQ_INI))
    assert len(emitter.sinks) == 1
    assert isinstance(emitter.sinks[0], RabbitMQSink)
    assert emitter.sinks[0].hostname  # defaulted from socket.gethostname()


def test_build_emitter_constructs_lora_sink(fake_mesh_link):
    emitter = build_emitter(_config("[emit]\nsinks = lora\n\n[lora]\ndevice = /dev/ttyUSB0\n"))
    assert len(emitter.sinks) == 1
    assert isinstance(emitter.sinks[0], LoRaSink)
    # Default throttle_interval (30s) wires a throttle into MeshLink.
    assert de.MeshLink.call_args.kwargs["throttle"] is not None


def test_build_emitter_lora_sink_no_throttle_when_zero(fake_mesh_link):
    build_emitter(_config("[emit]\nsinks = lora\n\n[lora]\nthrottle_interval = 0\n"))
    assert de.MeshLink.call_args.kwargs["throttle"] is None


def test_build_emitter_rejects_effectively_empty_sinks():
    # "," survives validate_config's non-empty check but yields no sink names.
    with pytest.raises(ValueError, match="sinks is empty"):
        build_emitter(_config("[emit]\nsinks = ,\n"))


def test_load_emitter_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_emitter(str(tmp_path / "nope.ini"))


# --- drone-emit-test CLI -----------------------------------------------------


def test_main_stdout_config_emits_sample(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "emit.ini"
    cfg.write_text("[emit]\nsinks = stdout\n")
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert main(["--config", str(cfg)]) == 0
    assert "WIFI_REMOTE_ID" in capsys.readouterr().out


def test_main_bad_config_returns_1(tmp_path):
    cfg = tmp_path / "emit.ini"
    cfg.write_text("[emit]\nsinks = carrierpigeon\n")
    assert main(["--config", str(cfg)]) == 1


def test_main_missing_file_returns_1(tmp_path):
    assert main(["--config", str(tmp_path / "nope.ini")]) == 1


def test_main_sink_failure_returns_1(tmp_path, monkeypatch):
    cfg = tmp_path / "emit.ini"
    cfg.write_text("[emit]\nsinks = stdout\n")

    class _ExplodingEmitter:
        sinks = []

        def start(self):
            raise RuntimeError("boom")

        def __enter__(self):
            return self.start()

        def __exit__(self, *exc_info):
            return None

        def close(self):
            return None

    monkeypatch.setattr(de, "load_emitter", lambda path: _ExplodingEmitter())
    assert main(["--config", str(cfg)]) == 1
