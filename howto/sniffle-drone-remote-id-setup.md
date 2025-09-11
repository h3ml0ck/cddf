# How to Setup Sniffle for Drone Remote ID Detection

## Overview

Sniffle is a Bluetooth Low Energy (BLE) sniffer designed for the TI CC2652R and CC1352R development boards. It can be used to capture drone Remote ID broadcasts, which are transmitted via Bluetooth beacons according to ASTM F3411 and ASD-STAN prEN 4709-002 standards.

## Hardware Requirements

- **TI CC2652R or CC1352R development board** (recommended: CC2652R LaunchPad)
- **USB cable** for connecting the board to your computer
- **Computer** running Linux, macOS, or Windows with Python support

## Software Prerequisites

- Python 3.6 or later
- Git
- TI Code Composer Studio (for firmware flashing)
- Serial terminal software (optional, for debugging)

## Installation Steps

### 1. Clone Sniffle Repository

```bash
git clone https://github.com/nccgroup/Sniffle.git
cd Sniffle
```

### 2. Install Python Dependencies

```bash
pip3 install -r requirements.txt
```

### 3. Flash Sniffle Firmware

#### Option A: Pre-built Firmware (Recommended)
1. Download the latest firmware from the Sniffle releases page
2. Flash using TI UniFlash or Code Composer Studio
3. Select the appropriate firmware for your board (CC2652R vs CC1352R)

#### Option B: Build from Source
1. Install TI Code Composer Studio
2. Import the Sniffle project
3. Build the firmware for your specific board
4. Flash the compiled firmware

### 4. Verify Installation

Connect your flashed board and run:
```bash
python3 sniffle_hw.py -h
```

## Configuration for Remote ID Detection

### 1. Basic Remote ID Capture

Start capturing Remote ID broadcasts:
```bash
python3 sniffle_hw.py -o remote_id_capture.pcap -a
```

### 2. Filter for Remote ID Advertisements

Remote ID uses specific advertisement types. Use these filters:
```bash
# Capture only advertisement packets
python3 sniffle_hw.py -o remote_id.pcap -a -A

# Filter for specific Remote ID service UUID (0xFFFA)
python3 sniffle_hw.py -o remote_id.pcap -a -s 0xFFFA
```

### 3. Real-time Monitoring

For live monitoring of Remote ID broadcasts:
```bash
python3 sniffle_hw.py -l -a -s 0xFFFA
```

## Remote ID Message Format

Remote ID messages contain:
- **Basic ID**: Serial number, drone type
- **Location**: GPS coordinates, altitude, speed
- **Auth**: Authentication data
- **Self ID**: Operator description
- **System**: Operator location, classification
- **Operator ID**: Operator registration number

## Analysis Tools

### 1. Wireshark Analysis
Open captured `.pcap` files in Wireshark:
```bash
wireshark remote_id_capture.pcap
```

Filter for Remote ID packets:
```
bluetooth.uuid == 0xfffa
```

### 2. Python Analysis Script

Create a simple parser for Remote ID data:
```python
#!/usr/bin/env python3
import struct
from scapy.all import *

def parse_remote_id(packet_data):
    # Parse Remote ID message structure
    # Implementation depends on specific message type
    pass

# Load and analyze capture file
packets = rdpcap("remote_id_capture.pcap")
for packet in packets:
    if hasattr(packet, 'payload'):
        parse_remote_id(packet.payload)
```

## Integration with CDDF

To integrate with the Citizen Drone Defense Force utilities:

### 1. Create Remote ID Monitor Script

```python
#!/usr/bin/env python3
import subprocess
import json
import sys

def monitor_remote_id():
    """Monitor for drone Remote ID broadcasts using Sniffle"""
    try:
        # Start Sniffle capture
        process = subprocess.Popen([
            'python3', 'sniffle_hw.py', '-l', '-a', '-s', '0xFFFA'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        for line in process.stdout:
            # Parse and process Remote ID data
            if "Remote ID" in line:
                print(f"Drone detected: {line.strip()}", file=sys.stderr)
                
    except KeyboardInterrupt:
        process.terminate()
        print("Remote ID monitoring stopped", file=sys.stderr)

if __name__ == "__main__":
    monitor_remote_id()
```

### 2. Add to Detection Pipeline

Integrate with existing CDDF audio and RF detection:
```bash
# Run multiple detection methods simultaneously
python3 drone_audio_monitor.py &
python3 drone_rf_detection.py &
python3 remote_id_monitor.py &
```

## Troubleshooting

### Common Issues

1. **Board not detected**: Check USB connection and drivers
2. **Permission errors**: Run with `sudo` on Linux or add user to dialout group
3. **No packets captured**: Verify firmware is flashed correctly
4. **Python errors**: Ensure all dependencies are installed

### Debugging Commands

```bash
# Check board connection
ls /dev/tty* | grep -E "(USB|ACM)"

# Test serial communication
python3 -c "import serial; print(serial.Serial('/dev/ttyACM0', 921600))"

# Verbose Sniffle output
python3 sniffle_hw.py -o test.pcap -a -v
```

## Legal Considerations

- Remote ID detection for defensive purposes is generally legal
- Ensure compliance with local privacy and surveillance laws
- Do not interfere with legitimate drone operations
- Use captured data responsibly and in accordance with applicable regulations

## References

- [Sniffle GitHub Repository](https://github.com/nccgroup/Sniffle)
- [ASTM F3411 Remote ID Standard](https://www.astm.org/f3411-22a.html)
- [TI CC2652R LaunchPad](https://www.ti.com/tool/LAUNCHXL-CC26X2R1)
- [Bluetooth Remote ID Specification](https://www.faa.gov/uas/getting_started/remote_id/)