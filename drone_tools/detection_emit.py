"""Emit drone detection events to one or more destinations ("sinks").

Detector modules produce ``DetectionEvent`` objects; this module decides where
they go. A node is configured with whichever sinks it can reach:

  * ``RabbitMQSink``  - publish directly to the central RabbitMQ over AMQP
                        (for nodes with network connectivity).
  * ``LoRaSink``      - broadcast over the Meshtastic mesh (for off-grid nodes;
                        a gateway running ``lora_to_queue`` bridges these in).
  * ``StdoutSink``    - print to the console (local / debugging).

A ``DetectionEmitter`` fans a single event out to several sinks at once, so a
node can publish directly *and* broadcast over LoRa as a backup. One sink
failing (broker down, radio unplugged) never stops the others or the detector.

The same detector code runs everywhere; topology is just configuration. Build
an emitter from an INI file and hand it to your detectors:

    emitter = load_emitter("emit.ini")
    emitter.emit(DetectionEvent(detector=DetectorType.WIFI_REMOTE_ID, ...))
    emitter.close()

RabbitMQSink needs the optional ``amqp`` extra (aio-pika); LoRaSink needs the
``lora`` extra (meshtastic). A hybrid node installs both: ``pip install -e
".[amqp,lora]"``.
"""

from __future__ import annotations

import argparse
import asyncio
import configparser
import contextlib
import logging
import socket
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone

from drone_tools.amqp import AIO_PIKA_AVAILABLE, AmqpPublisher, build_amqp_url
from drone_tools.drone_lora import (
    MESHTASTIC_AVAILABLE,
    DetectionEvent,
    DetectionThrottle,
    DetectorType,
    MeshLink,
)

logger = logging.getLogger(__name__)

# Seconds start() waits for a sink's background loop to come up.
_START_TIMEOUT = 5.0


# --- shared message format (also used by lora_to_queue) --------------------


def event_to_dict(event: DetectionEvent) -> dict:
    """Flatten a DetectionEvent to a JSON-serializable dict."""
    return {
        "detector": event.detector.name,
        "timestamp": event.timestamp,  # original detection time (unix seconds, UTC)
        "lat": event.lat,
        "lon": event.lon,
        "altitude": event.altitude,
        "rssi": event.rssi,
        "drone_id": event.drone_id,
        "operator_id": event.operator_id,
        "manufacturer": event.manufacturer,
        "model": event.model,
    }


def routing_key(detector_name: str) -> str:
    """Topic routing key for a detection, e.g. ``cddf.detection.wifi_remote_id``."""
    return f"cddf.detection.{detector_name.lower()}"


def format_detection_message(
    event: DetectionEvent,
    hostname: str,
    source: str = "local",
    lora_meta: dict | None = None,
) -> dict:
    """Build the RabbitMQ message body for a detection.

    Shares the envelope kismet_to_queue.py uses (hostname, timestamp, source,
    message_type) so downstream consumers handle all sources uniformly.
    ``source`` is "local" for a node publishing its own detections and "lora"
    for the gateway bridge, which also passes link metadata in ``lora_meta``.
    """
    message = {
        "hostname": hostname,
        "timestamp": datetime.now(timezone.utc).isoformat(),  # publish time
        "source": source,
        "message_type": "detection",
        "detector": event.detector.name,
        "event": event_to_dict(event),
    }
    if lora_meta is not None:
        message["lora"] = lora_meta
    return message


# --- sinks -----------------------------------------------------------------


class DetectionSink(ABC):
    """Destination for detection events. ``start``/``close`` default to no-ops."""

    def start(self) -> DetectionSink:
        return self

    @abstractmethod
    def emit(self, event: DetectionEvent) -> None: ...

    def close(self) -> None:
        return None


class StdoutSink(DetectionSink):
    """Print a one-line summary of each event. Useful locally and for tests."""

    def emit(self, event: DetectionEvent) -> None:
        ts = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        bits = [f"[{ts}] {event.detector.name}"]
        if event.drone_id:
            bits.append(f"drone_id={event.drone_id}")
        if event.lat is not None and event.lon is not None:
            bits.append(f"loc={event.lat:.6f},{event.lon:.6f}")
        if event.rssi is not None:
            bits.append(f"rssi={event.rssi}dBm")
        print("  ".join(bits))


class LoRaSink(DetectionSink):
    """Broadcast events over the Meshtastic mesh.

    Send-only: receiving/bridging back to RabbitMQ is the gateway's job
    (``lora_to_queue``). An optional throttle keeps duty-cycle in check.
    """

    def __init__(
        self,
        device: str | None = None,
        host: str | None = None,
        throttle: DetectionThrottle | None = None,
    ) -> None:
        if not MESHTASTIC_AVAILABLE:
            raise RuntimeError(
                'meshtastic is required for LoRaSink but not installed. Install with: pip install -e ".[lora]"'
            )
        self._link = MeshLink(device=device, host=host, throttle=throttle)

    def start(self) -> LoRaSink:
        self._link.connect()
        return self

    def emit(self, event: DetectionEvent) -> None:
        self._link.broadcast(event)  # returns False if throttled; nothing to do

    def close(self) -> None:
        self._link.close()


class RabbitMQSink(DetectionSink):
    """Publish detection events directly to RabbitMQ over AMQP.

    aio-pika is async, but most detectors are synchronous, so this sink runs
    its own asyncio loop on a daemon thread and exposes a synchronous,
    non-blocking ``emit()``. Events are handed to the loop through a bounded
    queue; if the broker stalls, new events are dropped rather than blocking
    the detector or growing memory. ``connect_robust`` handles reconnection.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        exchange: str,
        virtual_host: str = "/",
        exchange_type: str = "topic",
        source: str = "local",
        hostname: str | None = None,
        queue_maxsize: int = 1000,
    ) -> None:
        if not AIO_PIKA_AVAILABLE:
            raise RuntimeError(
                'aio-pika is required for RabbitMQSink but not installed. Install with: pip install -e ".[amqp]"'
            )
        self._url = build_amqp_url(host, port, username, password, virtual_host)
        self._exchange_name = exchange
        self._exchange_type = exchange_type
        self.source = source
        self.hostname = hostname or socket.gethostname()
        self.queue_maxsize = queue_maxsize

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._aqueue: asyncio.Queue | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._publisher_obj: AmqpPublisher | None = None

    def start(self) -> RabbitMQSink:
        self._thread = threading.Thread(target=self._thread_main, name="rabbitmq-sink", daemon=True)
        self._thread.start()
        # Wait until the loop + queue exist so emit() never races them.
        if not self._ready.wait(timeout=_START_TIMEOUT):
            logger.warning("RabbitMQSink loop did not start within %ss", _START_TIMEOUT)
        return self

    def emit(self, event: DetectionEvent) -> None:
        loop = self._loop
        if loop is None:
            return  # not started
        message = format_detection_message(event, self.hostname, self.source)
        loop.call_soon_threadsafe(self._enqueue, message)

    def close(self) -> None:
        loop = self._loop
        if loop is not None:
            # Drain queued events before stopping so a detector that emits
            # then immediately closes (one-shot scans) doesn't lose its event.
            try:
                fut = asyncio.run_coroutine_threadsafe(self._drain_and_stop(), loop)
                fut.result(timeout=_START_TIMEOUT + 1.0)
            except Exception:
                if self._stop is not None:
                    loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout=_START_TIMEOUT)

    async def _drain_and_stop(self) -> None:
        """Wait (bounded) for queued events to publish, then signal stop."""
        if self._aqueue is not None:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._aqueue.join(), timeout=_START_TIMEOUT)
        if self._stop is not None:
            self._stop.set()

    # -- background thread / loop --

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as e:  # never let the sink thread crash silently
            logger.error("RabbitMQSink thread exited: %s", type(e).__name__)
            logger.debug("RabbitMQSink thread error detail: %s", e)

    async def _run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._aqueue = asyncio.Queue(maxsize=self.queue_maxsize)
        self._stop = asyncio.Event()
        self._publisher_obj = AmqpPublisher(self._url, self._exchange_name, self._exchange_type, log=logger)
        self._ready.set()
        try:
            await self._connect_with_retry()
            if self._stop.is_set():
                return
            publisher = asyncio.create_task(self._publisher())
            await self._stop.wait()
            publisher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await publisher
        finally:
            await self._cleanup()

    def _enqueue(self, message: dict) -> None:
        """Runs on the loop thread; bounded, drops on overflow."""
        if self._aqueue is None:
            return
        try:
            self._aqueue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("RabbitMQSink queue full, dropping detection")

    async def _connect_with_retry(self) -> None:
        assert self._stop is not None and self._publisher_obj is not None
        delay = 1.0
        while not self._stop.is_set():
            if await self._publisher_obj.connect():
                return
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            delay = min(delay * 2, 30.0)

    async def _publisher(self) -> None:
        assert self._aqueue is not None and self._publisher_obj is not None
        while True:
            message = await self._aqueue.get()
            try:
                await self._publisher_obj.publish(routing_key(message["detector"]), message)
            finally:
                self._aqueue.task_done()

    async def _cleanup(self) -> None:
        if self._publisher_obj is not None:
            await self._publisher_obj.close()


# --- emitter ---------------------------------------------------------------


class DetectionEmitter:
    """Fan a detection event out to several sinks, isolating per-sink failures.

    An optional ``enricher`` runs once per event before fan-out (e.g. to attach
    manufacturer/model from the reference DB). It mutates the event in place and
    its failures are isolated like a sink's.

    An optional ``dedup`` throttle suppresses duplicate events. When multiple
    sinks (LoRa relay + direct AMQP) or multiple nodes report the same drone
    within ``dedup_interval`` seconds, only the first one reaches consumers.
    """

    def __init__(
        self,
        sinks: list[DetectionSink],
        enricher: Callable[[DetectionEvent], None] | None = None,
        dedup: DetectionThrottle | None = None,
    ) -> None:
        self.sinks = list(sinks)
        self.enricher = enricher
        self.dedup = dedup

    def start(self) -> DetectionEmitter:
        for sink in self.sinks:
            sink.start()
        return self

    def emit(self, event: DetectionEvent) -> None:
        if self.dedup is not None and not self.dedup.allow(event):
            logger.debug("dedup suppressed %s event (drone_id=%s)", event.detector.name, event.drone_id)
            return
        if self.enricher is not None:
            try:
                self.enricher(event)
            except Exception as e:
                logger.error("detection enricher failed: %s", type(e).__name__)
                logger.debug("enricher error detail: %s", e)
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception as e:
                logger.error("%s.emit failed: %s", type(sink).__name__, type(e).__name__)
                logger.debug("sink emit error detail: %s", e)

    def close(self) -> None:
        for sink in self.sinks:
            with contextlib.suppress(Exception):
                sink.close()

    def __enter__(self) -> DetectionEmitter:
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.close()


# --- config-driven construction --------------------------------------------


_VALID_SINKS = {"rabbitmq", "lora", "stdout"}
_REQUIRED_RABBITMQ_FIELDS = ("host", "port", "username", "password", "exchange")


def validate_config(config: configparser.ConfigParser) -> list[str]:
    """Check an emit config for structural errors.

    Returns a list of human-readable error messages. An empty list means the
    config is valid.
    """
    errors: list[str] = []

    if not config.has_section("emit"):
        errors.append("missing required [emit] section")
        return errors

    raw = config.get("emit", "sinks", fallback="").strip()
    if not raw:
        errors.append("[emit] sinks is empty; list at least one of: rabbitmq, lora, stdout")
        return errors

    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    for name in names:
        if name not in _VALID_SINKS:
            errors.append(f"unknown sink '{name}' in [emit] sinks (expected rabbitmq, lora, or stdout)")

    if "rabbitmq" in names:
        if not config.has_section("rabbitmq"):
            errors.append("[emit] lists 'rabbitmq' but the [rabbitmq] section is missing")
        else:
            for field in _REQUIRED_RABBITMQ_FIELDS:
                if not config.has_option("rabbitmq", field):
                    errors.append(f"[rabbitmq] is missing required field: {field}")
            if config.has_option("rabbitmq", "port"):
                try:
                    port = config.getint("rabbitmq", "port")
                    if not 1 <= port <= 65535:
                        errors.append(f"[rabbitmq] port must be 1-65535, got {port}")
                except ValueError:
                    errors.append("[rabbitmq] port must be a valid integer")

    if "lora" in names and not config.has_section("lora"):
        errors.append("[emit] lists 'lora' but the [lora] section is missing")

    return errors


def build_emitter(config: configparser.ConfigParser) -> DetectionEmitter:
    """Construct a DetectionEmitter from config.

    Reads ``[emit] sinks`` (comma-separated: ``rabbitmq``, ``lora``, ``stdout``)
    and the matching sink sections. Returns an emitter that is NOT yet started;
    call ``.start()`` (or use it as a context manager) to open connections.
    """
    errors = validate_config(config)
    if errors:
        raise ValueError("; ".join(errors))

    names = [n.strip().lower() for n in config.get("emit", "sinks", fallback="").split(",") if n.strip()]
    if not names:
        raise ValueError("[emit] sinks is empty; list at least one of: rabbitmq, lora, stdout")

    hostname = config.get("emit", "hostname", fallback="") or socket.gethostname()
    source = config.get("emit", "source", fallback="local")

    sinks: list[DetectionSink] = []
    for name in names:
        if name == "stdout":
            sinks.append(StdoutSink())
        elif name == "rabbitmq":
            sinks.append(_build_rabbitmq_sink(config, hostname, source))
        elif name == "lora":
            sinks.append(_build_lora_sink(config))
        else:
            raise ValueError(f"unknown sink '{name}' in [emit] sinks (expected rabbitmq, lora, or stdout)")

    enricher = None
    if config.getboolean("emit", "classify", fallback=False):
        db_path = config.get("emit", "classify_db", fallback="") or None
        enricher = make_db_enricher(db_path)

    dedup = None
    dedup_interval = config.getfloat("emit", "dedup_interval", fallback=0.0)
    if dedup_interval > 0:
        dedup = DetectionThrottle(interval=dedup_interval)

    return DetectionEmitter(sinks, enricher=enricher, dedup=dedup)


def make_db_enricher(db_path: str | None = None) -> Callable[[DetectionEvent], None]:
    """Return an enricher that fills in manufacturer/model from the reference DB.

    Looks up ``event.drone_id`` via ``drone_db.classify`` and copies the matched
    make/model onto the event. No-op when the event already has them, carries no
    ID, or no catalog match is found. ``db_path=None`` uses the default DB.
    """
    from drone_tools import drone_db

    def enrich(event: DetectionEvent) -> None:
        if event.manufacturer or event.model or not event.drone_id:
            return
        match = drone_db.classify(event.drone_id, db_path=db_path)
        if match:
            event.manufacturer = match.get("manufacturer")
            event.model = match.get("model")

    return enrich


def _build_rabbitmq_sink(config: configparser.ConfigParser, hostname: str, source: str) -> RabbitMQSink:
    return RabbitMQSink(
        host=config.get("rabbitmq", "host"),
        port=config.getint("rabbitmq", "port"),
        username=config.get("rabbitmq", "username"),
        password=config.get("rabbitmq", "password"),
        virtual_host=config.get("rabbitmq", "virtual_host", fallback="/"),
        exchange=config.get("rabbitmq", "exchange"),
        exchange_type=config.get("rabbitmq", "exchange_type", fallback="topic"),
        source=source,
        hostname=hostname,
    )


def _build_lora_sink(config: configparser.ConfigParser) -> LoRaSink:
    device = config.get("lora", "device", fallback="") or None
    host = config.get("lora", "host", fallback="") or None
    interval = config.getfloat("lora", "throttle_interval", fallback=30.0)
    throttle = DetectionThrottle(interval=interval) if interval > 0 else None
    return LoRaSink(device=device, host=host, throttle=throttle)


def load_emitter(config_file: str) -> DetectionEmitter:
    """Load config from an INI file and build a (not-yet-started) emitter."""
    config = configparser.ConfigParser()
    if not config.read(config_file):
        raise FileNotFoundError(f"could not read config file: {config_file}")
    return build_emitter(config)


# --- detector CLI integration ----------------------------------------------


def add_emit_args(parser: argparse.ArgumentParser) -> None:
    """Add the standard ``--emit-config`` option to a detector's argument parser.

    Every detector uses this so the flag and help text stay identical.
    """
    parser.add_argument(
        "--emit-config",
        metavar="PATH",
        help=(
            "Send detections to the sinks defined in this INI file "
            "(RabbitMQ and/or LoRa; see emit.ini.example). "
            "Without it, detections are only printed."
        ),
    )


def open_emitter(args: argparse.Namespace) -> DetectionEmitter | None:
    """Build and start an emitter from parsed args, or None if --emit-config absent.

    Raises on a bad config or an unavailable sink so the detector can fail
    loudly rather than silently not emitting when the user asked it to.
    """
    path = getattr(args, "emit_config", None)
    if not path:
        return None
    return load_emitter(path).start()


def main(argv: list[str] | None = None) -> int:
    """Verify a node's emit config by sending one sample detection through it."""
    parser = argparse.ArgumentParser(
        description="Send a sample detection event through a node's configured emitter (config check)."
    )
    parser.add_argument("--config", default="emit.ini", help="Path to INI config (default: emit.ini)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    try:
        emitter = load_emitter(args.config)
    except (ValueError, FileNotFoundError) as e:
        logger.error("Error: %s", e)
        return 1

    sample = DetectionEvent(
        detector=DetectorType.WIFI_REMOTE_ID,
        lat=37.7749,
        lon=-122.4194,
        rssi=-67,
        drone_id="TEST-1581F4F2C8A1",
    )
    try:
        with emitter:
            emitter.emit(sample)
            logger.info("Emitted sample event to %d sink(s). Allowing time to flush...", len(emitter.sinks))
            import time

            time.sleep(2)
        return 0
    except Exception as e:
        logger.error("Error: %s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
