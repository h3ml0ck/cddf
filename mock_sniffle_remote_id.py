#!/usr/bin/env python3
"""Mock Sniffle Remote ID capture script.

This script simulates Sniffle's output for Remote ID drone detection without
requiring actual Sniffle hardware. It generates realistic Remote ID packets
based on ASTM F3411 standard for testing and demonstration purposes.
"""

import argparse
import random
import struct
import sys
import time
from datetime import datetime
from typing import Dict, List


# Sample drone data for realistic simulation
SAMPLE_DRONES = [
    {
        'uas_id': 'DJI-MAVIC-ABC123',
        'ua_type': 4,  # VTOL
        'operator_id': 'FAA123456789',
        'description': 'Survey Mission Alpha',
        'base_lat': 37.7749,
        'base_lon': -122.4194,
        'base_alt': 150.0,
        'mac_address': 'AA:BB:CC:DD:EE:F1'
    },
    {
        'uas_id': 'AUTEL-EVO-XYZ789',
        'ua_type': 4,  # VTOL
        'operator_id': 'FAA987654321',
        'description': 'Infrastructure Inspection',
        'base_lat': 37.7849,
        'base_lon': -122.4294,
        'base_alt': 200.0,
        'mac_address': 'AA:BB:CC:DD:EE:F2'
    },
    {
        'uas_id': 'PARROT-ANAFI-DEF456',
        'ua_type': 4,  # VTOL
        'operator_id': 'FAA555666777',
        'description': 'Real Estate Photography',
        'base_lat': 37.7649,
        'base_lon': -122.4094,
        'base_alt': 120.0,
        'mac_address': 'AA:BB:CC:DD:EE:F3'
    }
]

# ASTM F3411 Remote ID message types
MESSAGE_TYPES = {
    0x0: "Basic ID",
    0x1: "Location/Vector",
    0x2: "Authentication",
    0x3: "Self ID",
    0x4: "System",
    0x5: "Operator ID"
}


class MockSniffleDrone:
    """Represents a simulated drone with Remote ID broadcasts."""

    def __init__(self, drone_data: Dict):
        self.uas_id = drone_data['uas_id']
        self.ua_type = drone_data['ua_type']
        self.operator_id = drone_data['operator_id']
        self.description = drone_data['description']
        self.mac_address = drone_data['mac_address']

        # Initial position and movement
        self.latitude = drone_data['base_lat'] + random.uniform(-0.001, 0.001)
        self.longitude = drone_data['base_lon'] + random.uniform(-0.001, 0.001)
        self.altitude = drone_data['base_alt'] + random.uniform(-20, 20)
        self.height = self.altitude - 50  # AGL

        # Movement parameters
        self.speed_h = random.uniform(2.0, 15.0)  # m/s horizontal
        self.speed_v = random.uniform(-2.0, 2.0)  # m/s vertical
        self.direction = random.uniform(0, 360)   # degrees

        # Operator position (slightly different from drone)
        self.op_latitude = drone_data['base_lat'] + random.uniform(-0.0005, 0.0005)
        self.op_longitude = drone_data['base_lon'] + random.uniform(-0.0005, 0.0005)
        self.op_altitude = 10.0  # operator on ground

        # Timing
        self.last_update = time.time()
        self.message_counter = 0

    def update_position(self):
        """Update drone position for realistic movement."""
        now = time.time()
        dt = now - self.last_update

        if dt > 0.5:  # Update every 0.5 seconds
            # Simple movement simulation
            direction_rad = self.direction * 3.14159 / 180
            dlat = (self.speed_h * dt * 0.000009) * random.uniform(0.8, 1.2)
            dlon = (self.speed_h * dt * 0.000011) * random.uniform(0.8, 1.2)

            self.latitude += dlat
            self.longitude += dlon
            self.altitude += self.speed_v * dt * random.uniform(0.8, 1.2)

            # Keep altitude reasonable
            self.altitude = max(50, min(400, self.altitude))
            self.height = self.altitude - 50

            # Occasional direction changes
            if random.random() < 0.1:
                self.direction += random.uniform(-30, 30)
                self.direction = self.direction % 360

            # Occasional speed changes
            if random.random() < 0.1:
                self.speed_h += random.uniform(-2, 2)
                self.speed_h = max(1, min(20, self.speed_h))

            self.last_update = now

    def generate_basic_id_message(self) -> bytes:
        """Generate Basic ID message (type 0x0)."""
        msg = bytearray(25)
        msg[0] = 0x0  # Basic ID message type
        msg[1] = self.ua_type  # UA type
        msg[2] = 1  # ID type (Serial Number)

        # UAS ID (20 bytes, null-terminated)
        uas_id_bytes = self.uas_id.encode('utf-8')[:20]
        msg[3:3+len(uas_id_bytes)] = uas_id_bytes

        return bytes(msg)

    def generate_location_message(self) -> bytes:
        """Generate Location/Vector message (type 0x1)."""
        msg = bytearray(26)
        msg[0] = 0x1  # Location message type
        msg[1] = 0x01  # Status (airborne)

        # Direction (2 bytes, little-endian, degrees * 100)
        struct.pack_into('<H', msg, 2, int(self.direction * 100))

        # Speeds (2 bytes each, little-endian, m/s * 100)
        struct.pack_into('<H', msg, 4, int(self.speed_h * 100))
        struct.pack_into('<h', msg, 6, int(self.speed_v * 100))

        # Position (4 bytes each, little-endian, degrees * 1e7)
        struct.pack_into('<i', msg, 8, int(self.latitude * 1e7))
        struct.pack_into('<i', msg, 12, int(self.longitude * 1e7))

        # Altitudes (2 bytes each, little-endian, meters * 2)
        struct.pack_into('<h', msg, 16, int(self.altitude * 2))
        struct.pack_into('<h', msg, 18, int(self.height * 2))

        # Accuracy values
        msg[20] = 3  # Vertical accuracy
        msg[21] = 3  # Horizontal accuracy
        msg[22] = 2  # Barometric accuracy
        msg[23] = 2  # Speed accuracy

        # Timestamp (2 bytes, little-endian, deciseconds)
        timestamp_ds = int((time.time() % 3600) * 10)
        struct.pack_into('<H', msg, 24, timestamp_ds)

        return bytes(msg)

    def generate_self_id_message(self) -> bytes:
        """Generate Self ID message (type 0x3)."""
        msg = bytearray(25)
        msg[0] = 0x3  # Self ID message type
        msg[1] = 0x0  # Description type (Text)

        # Description (23 bytes, null-terminated)
        desc_bytes = self.description.encode('utf-8')[:23]
        msg[2:2+len(desc_bytes)] = desc_bytes

        return bytes(msg)

    def generate_operator_id_message(self) -> bytes:
        """Generate Operator ID message (type 0x5)."""
        msg = bytearray(25)
        msg[0] = 0x5  # Operator ID message type
        msg[1] = 1  # Operator ID type (CAA Registration)

        # Operator ID (20 bytes, null-terminated)
        op_id_bytes = self.operator_id.encode('utf-8')[:20]
        msg[2:2+len(op_id_bytes)] = op_id_bytes

        return bytes(msg)

    def generate_system_message(self) -> bytes:
        """Generate System message (type 0x4)."""
        msg = bytearray(24)
        msg[0] = 0x4  # System message type
        msg[1] = 0x01  # Operator status (operational)

        # Operator position (4 bytes each, little-endian, degrees * 1e7)
        struct.pack_into('<i', msg, 2, int(self.op_latitude * 1e7))
        struct.pack_into('<i', msg, 6, int(self.op_longitude * 1e7))

        # Area parameters
        struct.pack_into('<H', msg, 10, 1)    # Area count
        struct.pack_into('<H', msg, 12, 500)  # Area radius (meters)
        struct.pack_into('<h', msg, 14, int(400 * 2))  # Area ceiling (meters * 2)
        struct.pack_into('<h', msg, 16, int(0 * 2))    # Area floor (meters * 2)

        msg[18] = 1  # Category (Open)
        msg[19] = 1  # Class value

        # Operator altitude (2 bytes, little-endian, meters * 2)
        struct.pack_into('<h', msg, 20, int(self.op_altitude * 2))

        # Timestamp (2 bytes, little-endian, deciseconds)
        timestamp_ds = int((time.time() % 3600) * 10)
        struct.pack_into('<H', msg, 22, timestamp_ds)

        return bytes(msg)


class MockSniffle:
    """Mock Sniffle BLE sniffer for Remote ID simulation."""

    def __init__(self, verbose: bool = False, output_file: str = None):
        self.verbose = verbose
        self.output_file = output_file
        # Create all sample drones
        self.drones = [MockSniffleDrone(drone_data) for drone_data in SAMPLE_DRONES]
        self.packet_count = 0

        # Message type rotation for realistic simulation
        self.message_types = [0x0, 0x1, 0x3, 0x5, 0x4]  # Basic, Location, Self, Operator, System
        self.message_index = 0

    def format_hex_dump(self, data: bytes) -> str:
        """Format data as hex dump similar to Sniffle output."""
        hex_str = data.hex().upper()
        return ' '.join(hex_str[i:i+2] for i in range(0, len(hex_str), 2))

    def generate_sniffle_packet_output(self, drone: MockSniffleDrone, message_data: bytes, rssi: int) -> str:
        """Generate Sniffle-style packet output."""
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]  # millisecond precision

        # Sniffle packet format
        lines = []
        lines.append(f"[{timestamp}] BLE Advertisement")
        lines.append(f"  Advertiser: {drone.mac_address} (Random)")
        lines.append(f"  RSSI: {rssi} dBm")
        lines.append(f"  UAS ID: {drone.uas_id}")
        lines.append(f"  Service UUID: FFFA (Remote ID)")
        lines.append(f"  Service Data ({len(message_data)} bytes): {self.format_hex_dump(message_data)}")

        if self.verbose:
            msg_type = message_data[0] if len(message_data) > 0 else 0
            msg_name = MESSAGE_TYPES.get(msg_type, f"Unknown({msg_type:02X})")
            lines.append(f"  Message Type: {msg_name}")

            # Add parsed data for some message types
            if msg_type == 0x0:  # Basic ID
                if len(message_data) >= 23:
                    uas_id = message_data[3:23].rstrip(b'\x00').decode('utf-8', errors='ignore')
                    lines.append(f"  UAS ID: {uas_id}")
            elif msg_type == 0x1:  # Location
                if len(message_data) >= 25:
                    lat = struct.unpack('<i', message_data[8:12])[0] / 1e7
                    lon = struct.unpack('<i', message_data[12:16])[0] / 1e7
                    alt = struct.unpack('<h', message_data[16:18])[0] / 2.0
                    lines.append(f"  Position: {lat:.6f}, {lon:.6f} @ {alt:.1f}m")

        return '\n'.join(lines)

    def generate_wireshark_style_output(self, drone: MockSniffleDrone, message_data: bytes, rssi: int) -> str:
        """Generate Wireshark-style decoded output."""
        timestamp = time.time()
        packet_num = self.packet_count

        lines = []
        lines.append(f"{packet_num:6d} {timestamp:.6f} {drone.mac_address} → Broadcast    BT-BLE  Remote-ID")

        if self.verbose:
            msg_type = message_data[0] if len(message_data) > 0 else 0
            msg_name = MESSAGE_TYPES.get(msg_type, f"Unknown")
            lines.append(f"        Bluetooth Low Energy Remote ID: {msg_name}")
            lines.append(f"        Data: {self.format_hex_dump(message_data)}")

        return '\n'.join(lines)

    def run_simulation(self, duration: int = None, output_format: str = 'sniffle'):
        """Run the Remote ID simulation."""
        print("Sniffle BLE 5.0 sniffer", file=sys.stderr)
        print("Drone Remote ID capture starting...", file=sys.stderr)
        if duration:
            print(f"Capture duration: {duration} seconds", file=sys.stderr)
        print("Press Ctrl+C to stop\n", file=sys.stderr)

        start_time = time.time()

        try:
            while True:
                current_time = time.time()

                # Check duration limit
                if duration and (current_time - start_time) >= duration:
                    break

                # Rotate through all drones
                drone = self.drones[self.packet_count % len(self.drones)]
                drone.update_position()

                # Generate message based on rotation
                msg_type = self.message_types[self.message_index % len(self.message_types)]

                if msg_type == 0x0:
                    message_data = drone.generate_basic_id_message()
                elif msg_type == 0x1:
                    message_data = drone.generate_location_message()
                elif msg_type == 0x3:
                    message_data = drone.generate_self_id_message()
                elif msg_type == 0x4:
                    message_data = drone.generate_system_message()
                elif msg_type == 0x5:
                    message_data = drone.generate_operator_id_message()
                else:
                    message_data = drone.generate_basic_id_message()

                # Generate RSSI based on distance simulation
                rssi = random.randint(-80, -30)

                # Format output
                if output_format == 'wireshark':
                    output = self.generate_wireshark_style_output(drone, message_data, rssi)
                else:  # sniffle format
                    output = self.generate_sniffle_packet_output(drone, message_data, rssi)

                print(output)
                print()  # Empty line between packets

                self.packet_count += 1
                self.message_index += 1

                # Realistic timing - Remote ID broadcasts every 200-300ms per message type
                time.sleep(random.uniform(0.2, 0.8))

        except KeyboardInterrupt:
            elapsed = time.time() - start_time
            print(f"\nCapture stopped. Packets captured: {self.packet_count} in {elapsed:.1f}s", file=sys.stderr)


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Mock Sniffle Remote ID capture for testing and demonstration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mock_sniffle_remote_id.py                    # Run indefinitely
  python mock_sniffle_remote_id.py -t 30              # Run for 30 seconds
  python mock_sniffle_remote_id.py -v                 # Verbose output
  python mock_sniffle_remote_id.py --format wireshark # Wireshark-style output
        """
    )

    parser.add_argument(
        "-t", "--time",
        type=int,
        help="Capture duration in seconds (default: infinite)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show verbose packet decoding"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file (not implemented in mock)"
    )
    parser.add_argument(
        "--format",
        choices=['sniffle', 'wireshark'],
        default='sniffle',
        help="Output format style (default: sniffle)"
    )

    args = parser.parse_args()

    if args.output:
        print("Note: Output file not implemented in mock version", file=sys.stderr)

    mock_sniffle = MockSniffle(verbose=args.verbose, output_file=args.output)

    try:
        mock_sniffle.run_simulation(duration=args.time, output_format=args.format)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())