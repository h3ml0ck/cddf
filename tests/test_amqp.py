"""Tests for the shared AMQP helpers.

Covers URL building, publisher construction, and the async connect/publish/close
paths using mock aio-pika objects (no live broker needed).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import drone_tools.amqp as amqp

# --- URL builder -----------------------------------------------------------


def test_build_amqp_url_default_vhost():
    url = amqp.build_amqp_url("broker", 5672, "user", "pw")
    assert url == "amqp://user:pw@broker:5672//"


def test_build_amqp_url_custom_vhost():
    url = amqp.build_amqp_url("h", 5673, "u", "p", virtual_host="cddf")
    assert url == "amqp://u:p@h:5673/cddf"


def test_build_amqp_url_special_chars():
    url = amqp.build_amqp_url("host", 5672, "user@org", "p@ss/word")
    assert "user@org" in url
    assert "p@ss/word" in url


# --- publisher construction ------------------------------------------------


def test_publisher_requires_aio_pika(monkeypatch):
    monkeypatch.setattr(amqp, "AIO_PIKA_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="aio-pika is required"):
        amqp.AmqpPublisher("amqp://x", "exchange")


def test_publisher_init_stores_fields():
    if not amqp.AIO_PIKA_AVAILABLE:
        pytest.skip("aio-pika not installed")
    pub = amqp.AmqpPublisher("amqp://x", "ex", "topic")
    assert pub._url == "amqp://x"
    assert pub._exchange_name == "ex"
    assert pub._exchange_type == "topic"
    assert not pub.is_connected


# --- async connect/publish/close (mocked aio-pika) -------------------------


def _make_mock_publisher(monkeypatch):
    """Create an AmqpPublisher with mocked aio-pika internals."""
    monkeypatch.setattr(amqp, "AIO_PIKA_AVAILABLE", True)

    mock_exchange = AsyncMock()
    mock_channel = AsyncMock()
    mock_channel.is_closed = False
    mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)

    mock_conn = AsyncMock()
    mock_conn.is_closed = False
    mock_conn.channel = AsyncMock(return_value=mock_channel)
    mock_conn.close = AsyncMock()

    mock_mod = MagicMock()
    mock_mod.connect_robust = AsyncMock(return_value=mock_conn)
    mock_mod.ExchangeType = MagicMock(side_effect=lambda x: x)
    mock_mod.Message = MagicMock()
    mock_mod.DeliveryMode = MagicMock()
    mock_mod.DeliveryMode.PERSISTENT = 2

    # Inject mock into both module namespace and sys.modules
    import sys

    monkeypatch.setitem(sys.modules, "aio_pika", mock_mod)
    monkeypatch.setattr(amqp, "aio_pika", mock_mod, raising=False)
    pub = amqp.AmqpPublisher("amqp://test", "ex")
    return pub, {"module": mock_mod, "connection": mock_conn, "channel": mock_channel, "exchange": mock_exchange}


def test_connect_success(monkeypatch):
    pub, mocks = _make_mock_publisher(monkeypatch)
    result = asyncio.run(pub.connect())
    assert result is True
    assert pub.is_connected


def test_connect_failure(monkeypatch):
    pub, mocks = _make_mock_publisher(monkeypatch)
    mocks["module"].connect_robust = AsyncMock(side_effect=ConnectionError("fail"))
    result = asyncio.run(pub.connect())
    assert result is False
    assert not pub.is_connected


def test_publish_success(monkeypatch):
    pub, mocks = _make_mock_publisher(monkeypatch)

    async def go():
        await pub.connect()
        return await pub.publish("key.test", {"data": 1})

    result = asyncio.run(go())
    assert result is True
    mocks["exchange"].publish.assert_called_once()


def test_publish_reconnects_when_disconnected(monkeypatch):
    pub, mocks = _make_mock_publisher(monkeypatch)
    result = asyncio.run(pub.publish("key.test", {"data": 1}))
    assert result is True


def test_publish_failure(monkeypatch):
    pub, mocks = _make_mock_publisher(monkeypatch)

    async def go():
        await pub.connect()
        mocks["exchange"].publish = AsyncMock(side_effect=RuntimeError("fail"))
        return await pub.publish("key.test", {"data": 1})

    result = asyncio.run(go())
    assert result is False


def test_close(monkeypatch):
    pub, mocks = _make_mock_publisher(monkeypatch)

    async def go():
        await pub.connect()
        await pub.close()

    asyncio.run(go())
    mocks["connection"].close.assert_called_once()


def test_close_already_closed(monkeypatch):
    pub, mocks = _make_mock_publisher(monkeypatch)

    async def go():
        await pub.connect()
        mocks["connection"].is_closed = True
        await pub.close()

    asyncio.run(go())  # should not raise or call close
