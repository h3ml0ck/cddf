"""Tests for the shared AMQP helpers.

The live publish path needs a broker and aio-pika; only the dependency-free
helpers are covered here.
"""

import pytest

import drone_tools.amqp as amqp


def test_build_amqp_url_default_vhost():
    # Default vhost "/" appends after the path slash (matches prior behavior).
    url = amqp.build_amqp_url("broker", 5672, "user", "pw")
    assert url == "amqp://user:pw@broker:5672//"


def test_build_amqp_url_custom_vhost():
    url = amqp.build_amqp_url("h", 5673, "u", "p", virtual_host="cddf")
    assert url == "amqp://u:p@h:5673/cddf"


def test_publisher_requires_aio_pika(monkeypatch):
    monkeypatch.setattr(amqp, "AIO_PIKA_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="aio-pika is required"):
        amqp.AmqpPublisher("amqp://x", "exchange")
