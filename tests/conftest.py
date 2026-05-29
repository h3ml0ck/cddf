"""Shared test fixtures for the CDDF test suite."""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

import drone_tools.drone_db as drone_db
from drone_tools.drone_lora import DetectionEvent, DetectorType


@pytest.fixture()
def dbpath(tmp_path: Path) -> Path:
    """Return a fresh DB path with an initialized schema."""
    path = tmp_path / "test.db"
    drone_db.init_db(db_path=path)
    return path


@pytest.fixture()
def seeded_db(dbpath: Path) -> Path:
    """Return a DB path pre-loaded with a few reference drones."""
    drone_db.add_drone(
        manufacturer="DJI",
        model="Avata",
        manufacturer_code="1581",
        remote_id_default=True,
        remote_id_wifi=True,
        remote_id_ble=True,
        db_path=dbpath,
    )
    drone_db.add_drone(
        manufacturer="Skydio",
        model="X10",
        drone_type="quadcopter",
        db_path=dbpath,
    )
    return dbpath


@pytest.fixture()
def sample_event() -> DetectionEvent:
    """A minimal detection event for testing."""
    return DetectionEvent(
        detector=DetectorType.WIFI_REMOTE_ID,
        timestamp=1_700_000_000,
        lat=37.7749,
        lon=-122.4194,
        rssi=-67,
        drone_id="TEST-1581F4F2C8A1",
    )


@pytest.fixture()
def emit_config(tmp_path: Path) -> Path:
    """Write a minimal stdout-only emit config and return the path."""
    cfg = tmp_path / "emit.ini"
    cfg.write_text("[emit]\nsinks = stdout\n")
    return cfg


@pytest.fixture()
def rabbitmq_config_text() -> str:
    """Return a valid RabbitMQ emit config as a string."""
    return (
        "[emit]\n"
        "sinks = rabbitmq\n"
        "\n"
        "[rabbitmq]\n"
        "host = localhost\n"
        "port = 5672\n"
        "username = test\n"
        "password = test\n"
        "virtual_host = /\n"
        "exchange = test_exchange\n"
        "exchange_type = topic\n"
    )


def make_config(text: str) -> configparser.ConfigParser:
    """Parse a config string into a ConfigParser."""
    cfg = configparser.ConfigParser()
    cfg.read_string(text)
    return cfg
