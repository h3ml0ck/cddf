"""Capture drone Remote ID over BLE (ASTM F3411).

Listens for BLE advertisements containing Remote ID service data
(Service UUID 0xFFFA) and decodes ASTM F3411 messages.

Requires a Bluetooth adapter. Uses the bleak library for cross-platform
BLE scanning. Pairs with mock_sniffle_remote_id.py for offline testing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

try:
    from bleak import BleakScanner
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData

    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False

from drone_tools.drone_wifi_remote_id import (
    REMOTE_ID_MESSAGE_TYPES,
    parse_basic_id,
    parse_location_vector,
    parse_operator_id,
    parse_self_id,
)

# BLE Remote ID service UUID (ASTM F3411, 16-bit UUID 0xFFFA)
REMOTE_ID_SERVICE_UUID = "0000fffa-0000-1000-8000-00805f9b34fb"


def parse_ble_service_data(service_data: bytes) -> dict | None:
    """Parse ASTM F3411 Remote ID payload from BLE service data.

    The first byte is a header: bits 3:0 = message type, bits 7:4 = protocol
    version. The remaining bytes are the message body, with the same layout
    used by drone_wifi_remote_id parsers.
    """
    if len(service_data) < 2:
        return None

    msg_type = service_data[0] & 0x0F
    msg_data = service_data[1:]

    result: dict = {
        "message_type": REMOTE_ID_MESSAGE_TYPES.get(msg_type, f"Unknown({msg_type})"),
        "raw_type": msg_type,
        "data_length": len(msg_data),
    }

    if msg_type == 0 and len(msg_data) >= 22:  # Basic ID
        result.update(parse_basic_id(msg_data))
    elif msg_type == 1 and len(msg_data) >= 25:  # Location/Vector
        result.update(parse_location_vector(msg_data))
    elif msg_type == 3 and len(msg_data) >= 1:  # Self ID
        result.update(parse_self_id(msg_data))
    elif msg_type == 5 and len(msg_data) >= 20:  # Operator ID
        result.update(parse_operator_id(msg_data))
    else:
        result["raw_data"] = msg_data.hex()

    return result


def _make_callback(verbose: bool):
    """Return a BleakScanner detection callback."""

    def callback(device: BLEDevice, adv: AdvertisementData) -> None:
        for uuid, data in adv.service_data.items():
            if uuid.lower() != REMOTE_ID_SERVICE_UUID:
                continue
            parsed = parse_ble_service_data(data)
            if not parsed:
                continue
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{timestamp}] BLE Remote ID from {device.address} (RSSI: {adv.rssi} dBm)")
            print(f"  Message Type: {parsed['message_type']}")
            for key, value in parsed.items():
                if key not in ("message_type", "raw_type", "data_length"):
                    print(f"  {key}: {value}")
            if verbose:
                print(f"  raw_hex: {data.hex()}")

    return callback


async def capture_ble_remote_id(timeout: float | None = None, verbose: bool = False) -> None:
    """Scan for BLE Remote ID advertisements.

    Args:
        timeout: Stop after this many seconds. None runs indefinitely.
        verbose: Print raw hex alongside decoded fields.
    """
    if not BLEAK_AVAILABLE:
        raise RuntimeError("bleak is required but not installed. Install with: pip install bleak")

    print("Starting BLE Remote ID capture...")
    print("Listening for ASTM F3411 Remote ID advertisements (UUID 0xFFFA)...")
    print("Press Ctrl+C to stop\n")

    async with BleakScanner(detection_callback=_make_callback(verbose)):
        if timeout is not None:
            await asyncio.sleep(timeout)
        else:
            while True:
                await asyncio.sleep(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture drone Remote ID over BLE (ASTM F3411, UUID 0xFFFA)")
    parser.add_argument(
        "--timeout",
        type=float,
        help="Stop after this many seconds (default: run indefinitely)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print raw hex alongside decoded fields",
    )
    args = parser.parse_args(argv)

    try:
        asyncio.run(capture_ble_remote_id(timeout=args.timeout, verbose=args.verbose))
        return 0
    except KeyboardInterrupt:
        print("\nCapture stopped.")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
