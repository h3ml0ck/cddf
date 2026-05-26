"""Bridge drone detection events received over LoRa into RabbitMQ.

A node running this acts as a gateway: it listens on the Meshtastic mesh for
detection events broadcast by other CDDF nodes (see ``drone_tools.drone_lora``)
and republishes each one to the same RabbitMQ exchange used by kismet-queuer.
Off-grid nodes can broadcast detections over LoRa, and whichever node has
network connectivity relays them into the central pipeline.

RabbitMQ connection settings are read from the same INI format kismet-queuer
uses (the ``[rabbitmq]`` and ``[logging]`` sections), so a node can point this
bridge and ``kismet_to_queue.py`` at one shared config file. Messages are
published with routing key ``cddf.detection.{detector}`` (a separate namespace
from kismet's ``kismet.*`` keys) so consumers opt in explicitly.

Requires the optional ``lora-bridge`` extra (meshtastic + aio-pika):

    pip install -e ".[lora-bridge]"

CLI:

    drone-lora-to-queue --config config.ini                      # auto-detect serial radio
    drone-lora-to-queue --config config.ini --device /dev/ttyUSB0
    drone-lora-to-queue --config config.ini --host 10.0.0.5      # radio over TCP
"""

from __future__ import annotations

import argparse
import asyncio
import configparser
import logging
import socket
import sys

from drone_tools.amqp import AIO_PIKA_AVAILABLE, AmqpPublisher, build_amqp_url
from drone_tools.detection_emit import (
    event_to_dict,  # re-exported for callers/tests
    format_detection_message,
    routing_key,  # re-exported for callers/tests
)
from drone_tools.drone_lora import (
    MESHTASTIC_AVAILABLE,
    MeshLink,
    ReceivedEvent,
)

__all__ = ["event_to_dict", "routing_key", "format_message", "LoraToQueue", "main"]

# Bound on buffered events between the radio thread and the publisher task.
# If RabbitMQ stalls, the oldest detections are dropped rather than growing
# memory without limit.
EVENT_QUEUE_MAXSIZE = 1000


def format_message(received: ReceivedEvent, hostname: str) -> dict:
    """Build the RabbitMQ message body for a detection received over LoRa.

    Delegates to the shared envelope used across CDDF sources (source="lora"),
    attaching the LoRa link metadata under a ``lora`` key.
    """
    return format_detection_message(
        received.event,
        hostname,
        source="lora",
        lora_meta={
            "from_id": received.from_id,
            "rssi": received.rssi,
            "snr": received.snr,
            "hops_away": received.hops_away,
        },
    )


class LoraToQueue:
    def __init__(self, config_file: str, device: str | None = None, host: str | None = None) -> None:
        self.config = self._load_config(config_file)
        self.device = device
        self.host = host
        self.hostname = socket.gethostname()
        self.logger = self._setup_logging()
        self.publisher: AmqpPublisher | None = None
        self._queue: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _load_config(self, config_file: str) -> configparser.ConfigParser:
        config = configparser.ConfigParser()
        if not config.read(config_file):
            sys.stderr.write(f"Error: Could not read config file: {config_file}\n")
            sys.exit(1)
        self._validate_config(config)
        return config

    def _validate_config(self, config: configparser.ConfigParser) -> None:
        if not config.has_section("rabbitmq"):
            sys.stderr.write("Error: Missing required config section: [rabbitmq]\n")
            sys.exit(1)

        required = ["username", "password", "host", "port", "virtual_host", "exchange"]
        missing = [f for f in required if not config.has_option("rabbitmq", f)]
        if missing:
            sys.stderr.write("Error: Missing required [rabbitmq] fields:\n")
            for field in missing:
                sys.stderr.write(f"  - {field}\n")
            sys.exit(1)

        try:
            port = config.getint("rabbitmq", "port")
            if not 1 <= port <= 65535:
                sys.stderr.write(f"Error: [rabbitmq] port must be 1-65535, got {port}\n")
                sys.exit(1)
        except ValueError:
            sys.stderr.write("Error: [rabbitmq] port must be a valid integer\n")
            sys.exit(1)

        user = config.get("rabbitmq", "username")
        password = config.get("rabbitmq", "password")
        if user in ("guest", "CHANGE_ME") or password in ("guest", "CHANGE_ME"):
            sys.stderr.write(
                "WARNING: RabbitMQ credentials appear to be default/placeholder values. "
                "Update [rabbitmq] username and password before production use.\n"
            )

    def _setup_logging(self) -> logging.Logger:
        level = self.config.get("logging", "level", fallback="INFO")
        fmt = self.config.get("logging", "format", fallback="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        logging.basicConfig(level=getattr(logging, level.upper()), format=fmt)
        return logging.getLogger(__name__)

    async def _connect_rabbitmq(self) -> bool:
        if self.publisher is None:
            url = build_amqp_url(
                host=self.config.get("rabbitmq", "host"),
                port=self.config.getint("rabbitmq", "port"),
                username=self.config.get("rabbitmq", "username"),
                password=self.config.get("rabbitmq", "password"),
                virtual_host=self.config.get("rabbitmq", "virtual_host"),
            )
            self.publisher = AmqpPublisher(
                url,
                self.config.get("rabbitmq", "exchange"),
                self.config.get("rabbitmq", "exchange_type", fallback="topic"),
                log=self.logger,
            )
        return await self.publisher.connect()

    def _enqueue(self, received: ReceivedEvent) -> None:
        """Runs on the event loop thread; bounded, drops on overflow."""
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(received)
        except asyncio.QueueFull:
            self.logger.warning("Event queue full, dropping detection from %s", received.from_id or "?")

    def _on_event(self, received: ReceivedEvent) -> None:
        """Meshtastic pubsub callback (background thread). Hand off to the loop."""
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._enqueue, received)

    async def cleanup(self) -> None:
        if self.publisher is not None:
            await self.publisher.close()
            self.logger.info("RabbitMQ connection closed")

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=EVENT_QUEUE_MAXSIZE)

        if not await self._connect_rabbitmq():
            self.logger.error("Failed to establish initial RabbitMQ connection")
            return

        link = MeshLink(device=self.device, host=self.host, on_event=self._on_event)
        try:
            link.connect()
        except Exception as e:
            self.logger.error("Failed to connect to Meshtastic radio: %s", type(e).__name__)
            self.logger.debug("Radio connection error detail: %s", e)
            await self.cleanup()
            return

        self.logger.info("Bridging LoRa detections to RabbitMQ. Press Ctrl+C to stop.")
        try:
            while True:
                received = await self._queue.get()
                message = format_message(received, self.hostname)
                assert self.publisher is not None  # connected above
                if not await self.publisher.publish(routing_key(message["detector"]), message):
                    self.logger.error("Failed to publish detection, continuing...")
        except asyncio.CancelledError:
            raise
        finally:
            link.close()
            await self.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bridge drone detection events received over LoRa into RabbitMQ.")
    parser.add_argument("--config", default="config.ini", help="Path to INI config (default: config.ini)")
    parser.add_argument("--device", help="Serial port of the Meshtastic device (default: auto-detect)")
    parser.add_argument("--host", help="Connect to a Meshtastic device over TCP instead of serial")
    args = parser.parse_args(argv)

    if not AIO_PIKA_AVAILABLE or not MESHTASTIC_AVAILABLE:
        missing = []
        if not MESHTASTIC_AVAILABLE:
            missing.append("meshtastic")
        if not AIO_PIKA_AVAILABLE:
            missing.append("aio-pika")
        sys.stderr.write(
            f'Error: missing dependencies ({", ".join(missing)}). Install with: pip install -e ".[lora-bridge]"\n'
        )
        return 1

    bridge = LoraToQueue(args.config, device=args.device, host=args.host)
    try:
        asyncio.run(bridge.run())
        return 0
    except KeyboardInterrupt:
        print("\nShutting down...")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
