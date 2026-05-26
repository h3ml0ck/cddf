"""Shared async RabbitMQ publisher for CDDF's two AMQP producers.

Both the detection emitter's ``RabbitMQSink`` (``detection_emit``) and the LoRa
gateway (``lora_to_queue``) publish detections to the same broker. Rather than
each reimplementing connect / declare-exchange / publish-with-reconnect, they
share ``AmqpPublisher`` here.

(The standalone ``kismet-queuer`` app is intentionally *not* coupled to this:
it ships and deploys independently with its own requirements, so it keeps its
own copy of the publishing logic.)

aio-pika is optional. Importing this module never requires it; constructing an
``AmqpPublisher`` does (``pip install -e ".[amqp]"``).
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

try:
    import aio_pika

    AIO_PIKA_AVAILABLE = True
except ImportError:
    AIO_PIKA_AVAILABLE = False

logger = logging.getLogger(__name__)


def build_amqp_url(host: str, port: int, username: str, password: str, virtual_host: str = "/") -> str:
    """Assemble an amqp:// connection URL from its parts."""
    return f"amqp://{username}:{password}@{host}:{port}/{virtual_host}"


class AmqpPublisher:
    """Publish JSON messages to a durable topic exchange, reconnecting as needed.

    Errors are logged (type only, to avoid leaking the credentials embedded in
    the URL) and surfaced as a ``False`` return rather than raised, so callers
    can keep running across a broker outage.
    """

    def __init__(
        self,
        url: str,
        exchange: str,
        exchange_type: str = "topic",
        *,
        log: logging.Logger | None = None,
    ) -> None:
        if not AIO_PIKA_AVAILABLE:
            raise RuntimeError(
                'aio-pika is required for RabbitMQ publishing but not installed. Install with: pip install -e ".[amqp]"'
            )
        self._url = url
        self._exchange_name = exchange
        self._exchange_type = exchange_type
        self._log = log or logger
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None

    @property
    def is_connected(self) -> bool:
        return self._channel is not None and not self._channel.is_closed and self._exchange is not None

    async def connect(self) -> bool:
        """Open a robust connection and declare the exchange. Returns success."""
        try:
            self._connection = await aio_pika.connect_robust(self._url)
            self._channel = await self._connection.channel()
            self._exchange = await self._channel.declare_exchange(
                self._exchange_name, aio_pika.ExchangeType(self._exchange_type), durable=True
            )
            self._log.info("Connected to RabbitMQ exchange: %s", self._exchange_name)
            return True
        except Exception as e:
            # Log type only to avoid leaking credentials embedded in the URL.
            self._log.error("Failed to connect to RabbitMQ: %s", type(e).__name__)
            self._log.debug("RabbitMQ connection error detail: %s", e)
            return False

    async def publish(self, routing_key: str, message: dict[str, Any]) -> bool:
        """Publish one persistent JSON message. Reconnects first if needed."""
        try:
            if not self.is_connected and not await self.connect():
                return False
            assert self._exchange is not None
            body = json.dumps(message, default=str).encode()
            await self._exchange.publish(
                aio_pika.Message(
                    body=body,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type="application/json",
                ),
                routing_key=routing_key,
            )
            self._log.debug("Published %s (%d bytes)", routing_key, len(body))
            return True
        except Exception as e:
            self._log.error("Failed to publish message to RabbitMQ: %s", type(e).__name__)
            self._log.debug("RabbitMQ publish error detail: %s", e)
            return False

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            with contextlib.suppress(Exception):
                await self._connection.close()
