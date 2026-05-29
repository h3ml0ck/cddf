"""Tests for the detection emitter, sinks, and config-driven construction.

The RabbitMQSink's live AMQP path needs a broker and isn't covered here; we
test the message envelope, fan-out/error isolation, and config wiring with
fake sinks.
"""

import configparser

import pytest

import drone_tools.drone_db as drone_db
from drone_tools.detection_emit import (
    DetectionEmitter,
    DetectionSink,
    StdoutSink,
    build_emitter,
    event_to_dict,
    format_detection_message,
    make_db_enricher,
    routing_key,
    validate_config,
)
from drone_tools.drone_lora import DetectionEvent, DetectionThrottle, DetectorType


class _RecordingSink(DetectionSink):
    def __init__(self):
        self.events = []
        self.started = False
        self.closed = False

    def start(self):
        self.started = True
        return self

    def emit(self, event):
        self.events.append(event)

    def close(self):
        self.closed = True


class _ExplodingSink(DetectionSink):
    def emit(self, event):
        raise RuntimeError("boom")


# --- message format --------------------------------------------------------


def test_routing_key_lowercases_detector():
    assert routing_key("WIFI_REMOTE_ID") == "cddf.detection.wifi_remote_id"


def test_event_to_dict_preserves_none_fields():
    d = event_to_dict(DetectionEvent(detector=DetectorType.AUDIO, timestamp=1))
    assert d["detector"] == "AUDIO"
    assert d["lat"] is None


def test_format_detection_message_local_has_no_lora_key():
    event = DetectionEvent(detector=DetectorType.RF, timestamp=1, drone_id="X")
    msg = format_detection_message(event, hostname="node-1")
    assert msg["source"] == "local"
    assert msg["message_type"] == "detection"
    assert msg["detector"] == "RF"
    assert msg["event"]["drone_id"] == "X"
    assert "lora" not in msg


def test_format_detection_message_includes_lora_meta_when_given():
    event = DetectionEvent(detector=DetectorType.BLE_REMOTE_ID, timestamp=1)
    msg = format_detection_message(event, hostname="gw", source="lora", lora_meta={"from_id": "!abcd", "rssi": -90})
    assert msg["source"] == "lora"
    assert msg["lora"] == {"from_id": "!abcd", "rssi": -90}


# --- emitter fan-out -------------------------------------------------------


def test_emitter_fans_out_to_all_sinks():
    a, b = _RecordingSink(), _RecordingSink()
    emitter = DetectionEmitter([a, b])
    event = DetectionEvent(detector=DetectorType.AUDIO, timestamp=1)
    emitter.emit(event)
    assert a.events == [event]
    assert b.events == [event]


def test_emitter_isolates_sink_failure():
    good = _RecordingSink()
    # Exploding sink must not stop the healthy one.
    emitter = DetectionEmitter([_ExplodingSink(), good])
    event = DetectionEvent(detector=DetectorType.AUDIO, timestamp=1)
    emitter.emit(event)  # should not raise
    assert good.events == [event]


def test_emitter_start_and_close_propagate():
    a, b = _RecordingSink(), _RecordingSink()
    emitter = DetectionEmitter([a, b])
    with emitter:
        assert a.started and b.started
    assert a.closed and b.closed


def test_emitter_close_isolates_failure():
    class _BadClose(DetectionSink):
        def emit(self, event):
            pass

        def close(self):
            raise RuntimeError("close boom")

    good = _RecordingSink()
    DetectionEmitter([_BadClose(), good]).close()  # should not raise
    assert good.closed


# --- config-driven construction --------------------------------------------


def _config(text: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read_string(text)
    return cfg


def test_build_emitter_stdout_only():
    emitter = build_emitter(_config("[emit]\nsinks = stdout\n"))
    assert len(emitter.sinks) == 1
    assert isinstance(emitter.sinks[0], StdoutSink)


def test_build_emitter_requires_emit_section():
    with pytest.raises(ValueError, match="emit"):
        build_emitter(_config("[rabbitmq]\nhost = x\n"))


def test_build_emitter_empty_sinks_rejected():
    with pytest.raises(ValueError, match="at least one"):
        build_emitter(_config("[emit]\nsinks =\n"))


def test_build_emitter_unknown_sink_rejected():
    with pytest.raises(ValueError, match="unknown sink"):
        build_emitter(_config("[emit]\nsinks = carrierpigeon\n"))


def test_build_emitter_rabbitmq_missing_section_rejected():
    with pytest.raises(ValueError, match="rabbitmq"):
        build_emitter(_config("[emit]\nsinks = rabbitmq\n"))


def test_stdout_sink_emits(capsys):
    StdoutSink().emit(DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, timestamp=1, drone_id="D1", rssi=-50))
    out = capsys.readouterr().out
    assert "WIFI_REMOTE_ID" in out
    assert "drone_id=D1" in out


# --- enrichment ------------------------------------------------------------


def test_event_to_dict_includes_make_model():
    d = event_to_dict(DetectionEvent(detector=DetectorType.VISION, timestamp=1, manufacturer="DJI", model="Avata"))
    assert d["manufacturer"] == "DJI"
    assert d["model"] == "Avata"


def test_emitter_runs_enricher_before_fanout():
    def enrich(event):
        event.manufacturer = "Enriched"

    sink = _RecordingSink()
    emitter = DetectionEmitter([sink], enricher=enrich)
    emitter.emit(DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, timestamp=1, drone_id="X"))
    assert sink.events[0].manufacturer == "Enriched"


def test_emitter_isolates_enricher_failure():
    def boom(event):
        raise RuntimeError("enrich boom")

    sink = _RecordingSink()
    emitter = DetectionEmitter([sink], enricher=boom)
    event = DetectionEvent(detector=DetectorType.AUDIO, timestamp=1)
    emitter.emit(event)  # must not raise; sink still receives the event
    assert sink.events == [event]


@pytest.fixture()
def seeded_db(tmp_path):
    path = tmp_path / "drones.db"
    drone_db.init_db(db_path=path)
    drone_db.add_drone(manufacturer="DJI", model="Avata", db_path=path)
    return path


def test_db_enricher_populates_make_model(seeded_db):
    enrich = make_db_enricher(str(seeded_db))
    event = DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, timestamp=1, drone_id="op-Avata-9")
    enrich(event)
    assert event.manufacturer == "DJI"
    assert event.model == "Avata"


def test_db_enricher_noop_without_drone_id(seeded_db):
    enrich = make_db_enricher(str(seeded_db))
    event = DetectionEvent(detector=DetectorType.AUDIO, timestamp=1)
    enrich(event)
    assert event.manufacturer is None


def test_db_enricher_skips_already_enriched(seeded_db):
    enrich = make_db_enricher(str(seeded_db))
    event = DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, timestamp=1, drone_id="op-Avata-9", manufacturer="Set")
    enrich(event)
    assert event.manufacturer == "Set"  # left untouched


def test_build_emitter_wires_classify(seeded_db):
    cfg = _config(f"[emit]\nsinks = stdout\nclassify = true\nclassify_db = {seeded_db}\n")
    emitter = build_emitter(cfg)
    sink = _RecordingSink()
    emitter.sinks = [sink]
    emitter.emit(DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, timestamp=1, drone_id="op-Avata-9"))
    assert sink.events[0].model == "Avata"


def test_build_emitter_no_classify_has_no_enricher():
    emitter = build_emitter(_config("[emit]\nsinks = stdout\n"))
    assert emitter.enricher is None


# --- validate_config -------------------------------------------------------


def test_validate_config_valid_stdout():
    assert validate_config(_config("[emit]\nsinks = stdout\n")) == []


def test_validate_config_missing_emit_section():
    errors = validate_config(_config("[rabbitmq]\nhost = x\n"))
    assert any("emit" in e for e in errors)


def test_validate_config_empty_sinks():
    errors = validate_config(_config("[emit]\nsinks =\n"))
    assert any("empty" in e for e in errors)


def test_validate_config_unknown_sink():
    errors = validate_config(_config("[emit]\nsinks = carrier_pigeon\n"))
    assert any("unknown" in e for e in errors)


def test_validate_config_rabbitmq_missing_section():
    errors = validate_config(_config("[emit]\nsinks = rabbitmq\n"))
    assert any("rabbitmq" in e.lower() for e in errors)


def test_validate_config_rabbitmq_missing_fields():
    errors = validate_config(_config("[emit]\nsinks = rabbitmq\n[rabbitmq]\nhost = x\n"))
    assert any("port" in e for e in errors)


def test_validate_config_rabbitmq_bad_port():
    cfg = "[emit]\nsinks = rabbitmq\n[rabbitmq]\nhost = x\nport = abc\nusername = u\npassword = p\nexchange = ex\n"
    errors = validate_config(_config(cfg))
    assert any("integer" in e for e in errors)


def test_validate_config_rabbitmq_port_out_of_range():
    cfg = "[emit]\nsinks = rabbitmq\n[rabbitmq]\nhost = x\nport = 99999\nusername = u\npassword = p\nexchange = ex\n"
    errors = validate_config(_config(cfg))
    assert any("65535" in e for e in errors)


def test_validate_config_lora_missing_section():
    errors = validate_config(_config("[emit]\nsinks = lora\n"))
    assert any("lora" in e.lower() for e in errors)


def test_validate_config_valid_rabbitmq():
    cfg = "[emit]\nsinks = rabbitmq\n[rabbitmq]\nhost = x\nport = 5672\nusername = u\npassword = p\nexchange = ex\n"
    assert validate_config(_config(cfg)) == []


# --- deduplication ---------------------------------------------------------


def test_emitter_dedup_suppresses_repeat():
    sink = _RecordingSink()
    dedup = DetectionThrottle(interval=60.0)
    emitter = DetectionEmitter([sink], dedup=dedup)
    event = DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, timestamp=1, drone_id="D1")
    emitter.emit(event)
    emitter.emit(event)  # same drone_id, should be suppressed
    assert len(sink.events) == 1


def test_emitter_dedup_allows_different_drones():
    sink = _RecordingSink()
    dedup = DetectionThrottle(interval=60.0)
    emitter = DetectionEmitter([sink], dedup=dedup)
    emitter.emit(DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, timestamp=1, drone_id="D1"))
    emitter.emit(DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, timestamp=2, drone_id="D2"))
    assert len(sink.events) == 2


def test_emitter_no_dedup_allows_all():
    sink = _RecordingSink()
    emitter = DetectionEmitter([sink])
    event = DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, timestamp=1, drone_id="D1")
    emitter.emit(event)
    emitter.emit(event)
    assert len(sink.events) == 2


def test_build_emitter_wires_dedup():
    emitter = build_emitter(_config("[emit]\nsinks = stdout\ndedup_interval = 30\n"))
    assert emitter.dedup is not None
    assert emitter.dedup.interval == 30.0


def test_build_emitter_no_dedup_by_default():
    emitter = build_emitter(_config("[emit]\nsinks = stdout\n"))
    assert emitter.dedup is None
