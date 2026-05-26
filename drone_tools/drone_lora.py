"""Broadcast and receive drone detection events between nodes over LoRa.

Uses a Meshtastic device (Heltec/T-Beam/RAK over USB-serial or TCP) as the
radio. Meshtastic already handles mesh routing, encryption, addressing, and
tags every packet with the sender's node ID, so this module only adds two
things on top of it:

  * A compact binary codec for detection events. Meshtastic's data payload is
    capped at ~237 bytes, so events are bit-packed rather than sent as JSON.
  * A thin link that broadcasts events on a private Meshtastic port number and
    surfaces received ones through a callback.

The codec (DetectionEvent / encode_event / decode_event) has no hardware
dependency and can be used and tested without meshtastic installed. The radio
layer (MeshLink) requires the optional ``meshtastic`` extra:

    pip install -e ".[lora]"

CLI: monitor incoming detections, or send a test event to verify the link.

    drone-lora-relay                       # listen, auto-detect serial device
    drone-lora-relay --device /dev/ttyUSB0 # listen on a specific port
    drone-lora-relay --host 10.0.0.5       # connect over TCP instead of serial
    drone-lora-relay --send-test           # broadcast one sample event and exit
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum

try:
    import meshtastic
    import meshtastic.serial_interface
    import meshtastic.tcp_interface
    from meshtastic import portnums_pb2
    from pubsub import pub

    MESHTASTIC_AVAILABLE = True
except ImportError:
    MESHTASTIC_AVAILABLE = False

# Wire format version. Bump when the layout in encode_event changes
# incompatibly so receivers can reject frames they cannot parse.
PROTOCOL_VERSION = 1

# Fixed header: version (u8), detector (u8), timestamp (u32 LE), flags (u8).
_HEADER = struct.Struct("<BBIB")
_HEADER_LEN = _HEADER.size  # 7 bytes

# Meshtastic port number used for our private app traffic. Keeps detection
# frames off the text-message channel so they don't show up as chat.
_PRIVATE_PORT_NAME = "PRIVATE_APP"

# Broadcast address understood by meshtastic's sendData.
_BROADCAST_ADDR = "^all"

# Coordinates are sent as fixed-point degrees * 1e7 (same scale Meshtastic and
# ASTM Remote ID use), which keeps ~1cm precision in a signed 32-bit int.
_COORD_SCALE = 1e7

# Presence flags for the optional fields that follow the header, in body order.
FLAG_LOCATION = 1 << 0
FLAG_ALTITUDE = 1 << 1
FLAG_RSSI = 1 << 2
FLAG_DRONE_ID = 1 << 3
FLAG_OPERATOR_ID = 1 << 4


class DetectorType(IntEnum):
    """Which CDDF sensor produced a detection."""

    UNKNOWN = 0
    AUDIO = 1
    RF = 2
    WIFI_REMOTE_ID = 3
    BLE_REMOTE_ID = 4
    RTL_POWER = 5
    VISION = 6


@dataclass
class DetectionEvent:
    """A single drone detection, compact enough to fit one LoRa frame.

    Only ``detector`` and ``timestamp`` are always present; every other field
    is optional and omitted from the wire frame when ``None`` so an audio
    detection (which has no location) costs nothing for the location bytes.
    """

    detector: DetectorType
    timestamp: int = field(default_factory=lambda: int(time.time()))  # unix seconds, UTC
    lat: float | None = None  # degrees
    lon: float | None = None  # degrees
    altitude: int | None = None  # meters, signed
    rssi: int | None = None  # dBm, signed
    drone_id: str | None = None  # ASTM Remote ID serial / UAS ID
    operator_id: str | None = None  # ASTM operator ID
    # Local enrichment from the drone reference DB (see drone_db.classify). These
    # are NOT put on the LoRa wire by encode_event -- they stay small and a
    # receiving gateway can re-classify from drone_id with its own catalog.
    manufacturer: str | None = None
    model: str | None = None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _encode_str(text: str) -> bytes:
    """Length-prefixed UTF-8, truncated to 255 bytes (one length byte)."""
    raw = text.encode("utf-8")[:255]
    return struct.pack("<B", len(raw)) + raw


def _decode_str(data: bytes, offset: int) -> tuple[str, int]:
    """Read a length-prefixed UTF-8 string, returning (text, new_offset)."""
    if offset >= len(data):
        raise ValueError("truncated frame: missing string length")
    length = data[offset]
    offset += 1
    end = offset + length
    if end > len(data):
        raise ValueError("truncated frame: string longer than remaining bytes")
    return data[offset:end].decode("utf-8", errors="replace"), end


def encode_event(event: DetectionEvent) -> bytes:
    """Serialize a DetectionEvent to a compact binary frame.

    Layout: 7-byte header (version, detector, timestamp, flags) followed by the
    optional fields whose flag bits are set, in flag-bit order. A typical
    Remote ID event lands around 40 bytes, well under Meshtastic's ~237-byte
    data payload limit.
    """
    flags = 0
    body = b""

    if event.lat is not None and event.lon is not None:
        flags |= FLAG_LOCATION
        body += struct.pack("<ii", round(event.lat * _COORD_SCALE), round(event.lon * _COORD_SCALE))
    if event.altitude is not None:
        flags |= FLAG_ALTITUDE
        body += struct.pack("<h", _clamp(int(event.altitude), -32768, 32767))
    if event.rssi is not None:
        flags |= FLAG_RSSI
        body += struct.pack("<b", _clamp(int(event.rssi), -128, 127))
    if event.drone_id:
        flags |= FLAG_DRONE_ID
        body += _encode_str(event.drone_id)
    if event.operator_id:
        flags |= FLAG_OPERATOR_ID
        body += _encode_str(event.operator_id)

    header = _HEADER.pack(
        PROTOCOL_VERSION,
        int(event.detector),
        event.timestamp & 0xFFFFFFFF,
        flags,
    )
    return header + body


def decode_event(data: bytes) -> DetectionEvent:
    """Parse a binary frame produced by encode_event.

    Raises ValueError on an unsupported version or a truncated/malformed frame.
    """
    if len(data) < _HEADER_LEN:
        raise ValueError(f"frame too short: {len(data)} bytes (need >= {_HEADER_LEN})")

    version, detector_raw, timestamp, flags = _HEADER.unpack(data[:_HEADER_LEN])
    if version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported protocol version: {version}")

    try:
        detector = DetectorType(detector_raw)
    except ValueError:
        detector = DetectorType.UNKNOWN

    event = DetectionEvent(detector=detector, timestamp=timestamp)
    offset = _HEADER_LEN

    if flags & FLAG_LOCATION:
        end = offset + 8
        if end > len(data):
            raise ValueError("truncated frame: missing location")
        lat_i, lon_i = struct.unpack("<ii", data[offset:end])
        event.lat = lat_i / _COORD_SCALE
        event.lon = lon_i / _COORD_SCALE
        offset = end
    if flags & FLAG_ALTITUDE:
        end = offset + 2
        if end > len(data):
            raise ValueError("truncated frame: missing altitude")
        (event.altitude,) = struct.unpack("<h", data[offset:end])
        offset = end
    if flags & FLAG_RSSI:
        end = offset + 1
        if end > len(data):
            raise ValueError("truncated frame: missing rssi")
        (event.rssi,) = struct.unpack("<b", data[offset:end])
        offset = end
    if flags & FLAG_DRONE_ID:
        event.drone_id, offset = _decode_str(data, offset)
    if flags & FLAG_OPERATOR_ID:
        event.operator_id, offset = _decode_str(data, offset)

    return event


# Metadata pulled off a received Meshtastic packet and handed to the callback.
@dataclass
class ReceivedEvent:
    event: DetectionEvent
    from_id: str | None = None  # sender Meshtastic node id, e.g. "!a1b2c3d4"
    rssi: int | None = None  # link RSSI of the received packet, dBm
    snr: float | None = None  # link SNR, dB
    hops_away: int | None = None


# Called for each successfully decoded detection. Receives the event plus link
# metadata. Exceptions raised here are caught and logged, never crash the radio.
EventCallback = Callable[[ReceivedEvent], None]


def default_throttle_key(event: DetectionEvent) -> str:
    """Dedup key: the drone's identity when known, else the detector type.

    Keying on ``drone_id`` collapses the same drone seen by several sensors
    (e.g. Wi-Fi + BLE Remote ID) into a single relayed event. Detections with
    no ID (audio, RF, RTL power) are instead throttled per detector type.
    """
    if event.drone_id:
        return f"id:{event.drone_id}"
    return f"det:{event.detector.name}"


class DetectionThrottle:
    """Rate-limit detection events so LoRa duty-cycle limits aren't blown.

    Records when an event was last allowed for each dedup key and suppresses
    repeats within ``interval`` seconds. A detector that sees a hovering drone
    in every beacon frame then emits at most one LoRa broadcast per interval
    instead of flooding the mesh.

    Elapsed time is measured with a monotonic clock, so it is unaffected by
    system clock changes. ``time_fn`` is injectable for testing.
    """

    def __init__(
        self,
        interval: float = 30.0,
        key_fn: Callable[[DetectionEvent], str] | None = None,
        max_keys: int = 4096,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if interval < 0:
            raise ValueError("interval must be non-negative")
        self.interval = interval
        self.max_keys = max_keys
        self._key_fn = key_fn or default_throttle_key
        self._time_fn = time_fn
        self._last_sent: dict[str, float] = {}

    def allow(self, event: DetectionEvent) -> bool:
        """Return True if this event should be sent now, recording it if so."""
        key = self._key_fn(event)
        now = self._time_fn()
        last = self._last_sent.get(key)
        if last is not None and (now - last) < self.interval:
            return False
        self._last_sent[key] = now
        if len(self._last_sent) > self.max_keys:
            self._prune(now)
        return True

    def _prune(self, now: float) -> None:
        """Bound memory: drop keys past their interval, then oldest if needed."""
        for key in [k for k, t in self._last_sent.items() if (now - t) >= self.interval]:
            del self._last_sent[key]
        overflow = len(self._last_sent) - self.max_keys
        if overflow > 0:
            oldest = sorted(self._last_sent, key=lambda k: self._last_sent[k])[:overflow]
            for key in oldest:
                del self._last_sent[key]


class MeshLink:
    """Broadcast and receive DetectionEvents over a Meshtastic radio.

    Use as a context manager so the serial/TCP interface is always closed::

        with MeshLink(device="/dev/ttyUSB0", on_event=handle) as link:
            link.broadcast(event)
    """

    def __init__(
        self,
        device: str | None = None,
        host: str | None = None,
        on_event: EventCallback | None = None,
        on_error: Callable[[str, Exception], None] | None = None,
        throttle: DetectionThrottle | None = None,
    ) -> None:
        """
        Args:
            device: Serial port path (e.g. ``/dev/ttyUSB0``). ``None`` lets
                meshtastic auto-detect a connected device. Ignored if ``host``
                is set.
            host: Hostname/IP for a Meshtastic device exposing the TCP API.
                Takes precedence over ``device`` when given.
            on_event: Called with a ReceivedEvent for each decoded detection.
            on_error: Called as ``(context, exception)`` when a received packet
                cannot be decoded. Defaults to printing to stderr.
            throttle: Optional DetectionThrottle. When set, ``broadcast`` skips
                events the throttle suppresses and returns False for them.
        """
        self.device = device
        self.host = host
        self.on_event = on_event
        self.on_error = on_error or self._default_on_error
        self.throttle = throttle
        self.interface = None

    @staticmethod
    def _default_on_error(context: str, exc: Exception) -> None:
        print(f"[lora] {context}: {exc}", file=sys.stderr)

    def connect(self) -> MeshLink:
        if not MESHTASTIC_AVAILABLE:
            raise RuntimeError(
                'meshtastic is required for the radio link but not installed. Install with: pip install -e ".[lora]"'
            )
        # Subscribe before opening the interface so we don't miss early packets.
        pub.subscribe(self._on_receive, "meshtastic.receive")
        if self.host:
            self.interface = meshtastic.tcp_interface.TCPInterface(hostname=self.host)
        else:
            self.interface = meshtastic.serial_interface.SerialInterface(devPath=self.device)
        return self

    def broadcast(self, event: DetectionEvent) -> bool:
        """Broadcast a detection event to every node on the mesh.

        Returns True if the frame was transmitted, or False if a configured
        throttle suppressed it as a duplicate within its interval.
        """
        if self.interface is None:
            raise RuntimeError("MeshLink is not connected; call connect() first")
        if self.throttle is not None and not self.throttle.allow(event):
            return False
        self.interface.sendData(
            encode_event(event),
            destinationId=_BROADCAST_ADDR,
            portNum=portnums_pb2.PortNum.PRIVATE_APP,
            wantAck=False,
        )
        return True

    def _on_receive(self, packet=None, interface=None) -> None:  # noqa: ARG002
        """pubsub callback for every packet Meshtastic decodes."""
        try:
            decoded = (packet or {}).get("decoded") or {}
            if decoded.get("portnum") != _PRIVATE_PORT_NAME:
                return  # not ours (text, position, telemetry, ...)
            payload = decoded.get("payload")
            if not payload:
                return
            event = decode_event(payload)
        except Exception as exc:  # malformed or foreign PRIVATE_APP traffic
            self.on_error("failed to decode received frame", exc)
            return

        received = ReceivedEvent(
            event=event,
            from_id=packet.get("fromId"),
            rssi=packet.get("rxRssi"),
            snr=packet.get("rxSnr"),
            hops_away=packet.get("hopsAway"),
        )
        if self.on_event is not None:
            try:
                self.on_event(received)
            except Exception as exc:
                self.on_error("on_event callback raised", exc)

    def close(self) -> None:
        if self.interface is not None:
            try:
                pub.unsubscribe(self._on_receive, "meshtastic.receive")
            except Exception:
                pass
            self.interface.close()
            self.interface = None

    def __enter__(self) -> MeshLink:
        return self.connect()

    def __exit__(self, *exc_info) -> None:
        self.close()


def _format_received(received: ReceivedEvent) -> str:
    e = received.event
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp))
    parts = [f"[{ts}] {e.detector.name}"]
    src = received.from_id or "?"
    link = f"from {src}"
    if received.rssi is not None:
        link += f" RSSI {received.rssi}dBm"
    if received.snr is not None:
        link += f" SNR {received.snr}dB"
    if received.hops_away is not None:
        link += f" {received.hops_away} hop(s)"
    parts.append(link)
    if e.drone_id:
        parts.append(f"drone_id={e.drone_id}")
    if e.operator_id:
        parts.append(f"operator={e.operator_id}")
    if e.lat is not None and e.lon is not None:
        parts.append(f"loc={e.lat:.6f},{e.lon:.6f}")
    if e.altitude is not None:
        parts.append(f"alt={e.altitude}m")
    if e.rssi is not None:
        parts.append(f"signal={e.rssi}dBm")
    return "  ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Relay drone detection events between CDDF nodes over a Meshtastic LoRa radio."
    )
    parser.add_argument(
        "--device",
        help="Serial port of the Meshtastic device (default: auto-detect)",
    )
    parser.add_argument(
        "--host",
        help="Connect over TCP to a Meshtastic device at this host instead of serial",
    )
    parser.add_argument(
        "--send-test",
        action="store_true",
        help="Broadcast one sample detection event and exit (verifies the link)",
    )
    args = parser.parse_args(argv)

    if not MESHTASTIC_AVAILABLE:
        print(
            'Error: meshtastic is not installed. Install with: pip install -e ".[lora]"',
            file=sys.stderr,
        )
        return 1

    try:
        with MeshLink(
            device=args.device,
            host=args.host,
            on_event=lambda r: print(_format_received(r)),
        ) as link:
            if args.send_test:
                sample = DetectionEvent(
                    detector=DetectorType.WIFI_REMOTE_ID,
                    lat=37.7749,
                    lon=-122.4194,
                    altitude=120,
                    rssi=-67,
                    drone_id="TEST-1581F4F2C8A1",
                )
                link.broadcast(sample)
                print(f"Broadcast test event ({len(encode_event(sample))} bytes).")
                # Give the radio a moment to actually transmit before closing.
                time.sleep(2)
                return 0

            print("Listening for drone detection events over LoRa. Press Ctrl+C to stop.\n")
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
