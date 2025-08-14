"""Capture drone remote ID information over WiFi.

This script scans for WiFi beacons containing drone remote ID information
according to the ASTM F3411 standard. Remote ID broadcasts drone identification,
location, and operational data over WiFi Nan (Neighbor Aware Networking) or
standard WiFi beacons.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from typing import Dict, Optional

try:
    from scapy.all import sniff, Dot11, Dot11Beacon, Dot11Elt, RadioTap
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False


# ASTM F3411 Remote ID message types
REMOTE_ID_MESSAGE_TYPES = {
    0: "Basic ID",
    1: "Location/Vector",
    2: "Authentication",
    3: "Self ID", 
    4: "System",
    5: "Operator ID"
}

# Remote ID WiFi Vendor Specific OUI (ASTM F3411)
REMOTE_ID_OUI = b'\x90\x3a\xe6'  # ASTM assigned OUI for Remote ID


def parse_remote_id_element(element_data: bytes) -> Optional[Dict]:
    """Parse a Remote ID vendor specific element.
    
    Args:
        element_data: Raw bytes from the vendor specific element
        
    Returns:
        Dictionary containing parsed Remote ID data, or None if not Remote ID
    """
    if len(element_data) < 4:
        return None
        
    # Check for Remote ID OUI
    if element_data[:3] != REMOTE_ID_OUI:
        return None
        
    # Remote ID message format: OUI(3) + Type(1) + Data(variable)
    msg_type = element_data[3]
    msg_data = element_data[4:] if len(element_data) > 4 else b''
    
    result = {
        'message_type': REMOTE_ID_MESSAGE_TYPES.get(msg_type, f"Unknown({msg_type})"),
        'raw_type': msg_type,
        'data_length': len(msg_data)
    }
    
    # Parse specific message types
    if msg_type == 0 and len(msg_data) >= 20:  # Basic ID
        result.update(parse_basic_id(msg_data))
    elif msg_type == 1 and len(msg_data) >= 25:  # Location/Vector
        result.update(parse_location_vector(msg_data))
    elif msg_type == 3 and len(msg_data) >= 1:  # Self ID
        result.update(parse_self_id(msg_data))
    elif msg_type == 5 and len(msg_data) >= 20:  # Operator ID
        result.update(parse_operator_id(msg_data))
    else:
        result['raw_data'] = msg_data.hex()
        
    return result


def parse_basic_id(data: bytes) -> Dict:
    """Parse Basic ID message."""
    try:
        ua_type = data[0]
        id_type = data[1]
        uas_id = data[2:22].rstrip(b'\x00').decode('utf-8', errors='ignore')
        
        ua_types = {0: "None", 1: "Aeroplane", 2: "Helicopter", 3: "Gyroplane", 
                   4: "VTOL", 5: "Ornithopter", 6: "Glider", 7: "Kite", 
                   8: "Free Balloon", 9: "Captive Balloon", 10: "Airship", 
                   11: "Free Fall/Parachute", 12: "Rocket", 13: "Tethered", 
                   14: "Ground Obstacle", 15: "Other"}
        
        id_types = {0: "None", 1: "Serial Number", 2: "CAA Registration", 
                   3: "UTM Assigned", 4: "Specific Session"}
        
        return {
            'ua_type': ua_types.get(ua_type, f"Unknown({ua_type})"),
            'id_type': id_types.get(id_type, f"Unknown({id_type})"),
            'uas_id': uas_id
        }
    except Exception:
        return {'parse_error': 'Failed to parse Basic ID'}


def parse_location_vector(data: bytes) -> Dict:
    """Parse Location/Vector message."""
    try:
        status = data[0]
        direction = struct.unpack('<H', data[1:3])[0] / 100.0  # degrees
        speed_h = struct.unpack('<H', data[3:5])[0] / 100.0    # m/s
        speed_v = struct.unpack('<h', data[5:7])[0] / 100.0    # m/s
        latitude = struct.unpack('<i', data[7:11])[0] / 1e7    # degrees
        longitude = struct.unpack('<i', data[11:15])[0] / 1e7  # degrees
        altitude = struct.unpack('<h', data[15:17])[0] / 2.0   # meters
        height = struct.unpack('<h', data[17:19])[0] / 2.0     # meters
        
        return {
            'status': status,
            'direction': direction,
            'speed_horizontal': speed_h,
            'speed_vertical': speed_v,
            'latitude': latitude,
            'longitude': longitude,
            'altitude': altitude,
            'height': height
        }
    except Exception:
        return {'parse_error': 'Failed to parse Location/Vector'}


def parse_self_id(data: bytes) -> Dict:
    """Parse Self ID message."""
    try:
        desc_type = data[0]
        description = data[1:].rstrip(b'\x00').decode('utf-8', errors='ignore')
        
        desc_types = {0: "Text", 1: "Emergency", 2: "Extended Status"}
        
        return {
            'description_type': desc_types.get(desc_type, f"Unknown({desc_type})"),
            'description': description
        }
    except Exception:
        return {'parse_error': 'Failed to parse Self ID'}


def parse_operator_id(data: bytes) -> Dict:
    """Parse Operator ID message."""
    try:
        op_id_type = data[0]
        operator_id = data[1:21].rstrip(b'\x00').decode('utf-8', errors='ignore')
        
        return {
            'operator_id_type': op_id_type,
            'operator_id': operator_id
        }
    except Exception:
        return {'parse_error': 'Failed to parse Operator ID'}


def process_packet(packet) -> None:
    """Process a captured WiFi packet for Remote ID information."""
    if not packet.haslayer(Dot11Beacon):
        return
        
    beacon = packet[Dot11Beacon]
    bssid = packet[Dot11].addr2
    
    # Look for vendor specific elements
    element = beacon.payload
    while element:
        if hasattr(element, 'ID') and element.ID == 221:  # Vendor Specific
            remote_id_data = parse_remote_id_element(bytes(element.info))
            if remote_id_data:
                timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                print(f"\n[{timestamp}] Remote ID detected from {bssid}")
                print(f"Message Type: {remote_id_data['message_type']}")
                
                # Print specific data based on message type
                for key, value in remote_id_data.items():
                    if key not in ['message_type', 'raw_type', 'data_length']:
                        print(f"  {key}: {value}")
                        
        element = element.payload if hasattr(element, 'payload') else None


def capture_remote_id(interface: str, timeout: Optional[float] = None, use_filter: bool = True) -> None:
    """Capture drone remote ID broadcasts over WiFi.
    
    Args:
        interface: WiFi interface name (e.g., 'wlan0', 'en0')
        timeout: Capture timeout in seconds, None for infinite
        use_filter: Whether to use BPF filter (may not work on all interfaces)
    """
    if not SCAPY_AVAILABLE:
        raise RuntimeError("scapy is required but not installed. Install with: pip install scapy")
    
    print(f"Starting Remote ID capture on interface {interface}")
    print("Listening for drone Remote ID WiFi beacons...")
    print("Press Ctrl+C to stop\n")
    
    def filtered_process_packet(packet):
        """Process packet with additional filtering if BPF filter failed."""
        if packet.haslayer(Dot11Beacon):
            process_packet(packet)
    
    try:
        if use_filter:
            # Try with BPF filter first (works in monitor mode)
            try:
                sniff(
                    iface=interface,
                    prn=process_packet,
                    filter="type mgt subtype beacon",
                    timeout=timeout,
                    store=False
                )
            except Exception as filter_exc:
                print(f"BPF filter failed ({filter_exc}), trying without filter...")
                # Fallback to no filter with manual filtering
                sniff(
                    iface=interface,
                    prn=filtered_process_packet,
                    timeout=timeout,
                    store=False
                )
        else:
            # Manual filtering approach
            sniff(
                iface=interface,
                prn=filtered_process_packet,
                timeout=timeout,
                store=False
            )
    except KeyboardInterrupt:
        print("\nCapture stopped by user")
    except Exception as exc:
        print(f"Capture failed: {exc}", file=sys.stderr)
        raise


def main(argv: list[str] | None = None) -> int:
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Capture drone Remote ID information over WiFi"
    )
    parser.add_argument(
        "interface", 
        help="WiFi interface name (e.g., wlan0, en0, wlp2s0)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="Capture timeout in seconds (default: run indefinitely)"
    )
    parser.add_argument(
        "--monitor-mode",
        action="store_true",
        help="Assume interface is already in monitor mode"
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Skip BPF filter (use if getting filter errors)"
    )
    
    args = parser.parse_args(argv)
    
    if not args.monitor_mode:
        print("Note: This script works best with a WiFi interface in monitor mode.")
        print("You may need to configure monitor mode manually:")
        print(f"  sudo iwconfig {args.interface} mode monitor")
        print(f"  sudo ifconfig {args.interface} up")
        print()
        print("If you get filter errors, try running with --no-filter")
        print()
    
    try:
        capture_remote_id(args.interface, args.timeout, use_filter=not args.no_filter)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())