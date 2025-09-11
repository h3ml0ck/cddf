# How to Setup NRF-Based Devices for Drone Remote ID Sniffing

## Overview

Nordic Semiconductor's NRF chips (NRF52840, NRF52832, NRF51822) are popular choices for Bluetooth Low Energy (BLE) applications and can be configured for drone Remote ID detection. This guide covers setup and configuration of NRF-based development boards and dongles for capturing Remote ID broadcasts.

## Hardware Options

### Development Boards
- **NRF52840 DK** (recommended) - Full featured with onboard debugger
- **NRF52832 DK** - Good alternative with most features
- **Arduino Nano 33 BLE** - NRF52840 based, affordable option
- **Adafruit Feather NRF52840** - Compact with built-in USB

### USB Dongles
- **Nordic NRF52840 Dongle** - Compact USB stick format
- **Makerdiary NRF52840 MDK USB Dongle** - Alternative USB option

### Required Accessories
- USB cable (USB-C or Micro-USB depending on board)
- Computer with USB port
- Optional: External antenna for better range

## Software Prerequisites

- **Python 3.7+** with pip
- **Git** for repository cloning
- **Nordic nRF Connect SDK** or **Arduino IDE** (depending on approach)
- **J-Link Software** (for Nordic DKs with onboard debugger)

## Setup Methods

## Method 1: Using Nordic nRF Connect SDK (Recommended)

### 1. Install nRF Connect SDK

```bash
# Install nRF Connect for Desktop
# Download from: https://www.nordicsemi.com/Products/Development-tools/nrf-connect-for-desktop

# Install nRF Connect SDK via Toolchain Manager
# Or manual installation:
pip install west
west init nrf-sdk
cd nrf-sdk
west update
```

### 2. Build BLE Scanner Firmware

Create a custom Remote ID scanner application:

```c
// main.c - Basic Remote ID scanner
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/gap.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(remote_id_scanner);

// Remote ID Service UUID: 0xFFFA
#define REMOTE_ID_UUID BT_UUID_16_ENCODE(0xFFFA)

static void scan_cb(const bt_addr_le_t *addr, int8_t rssi,
                   uint8_t type, struct net_buf_simple *buf)
{
    char addr_str[BT_ADDR_LE_STR_LEN];
    
    bt_addr_le_to_str(addr, addr_str, sizeof(addr_str));
    
    // Check for Remote ID service UUID
    while (buf->len > 1) {
        uint8_t len = net_buf_simple_pull_u8(buf);
        uint8_t ad_type = net_buf_simple_pull_u8(buf);
        
        if (ad_type == BT_DATA_UUID16_ALL || ad_type == BT_DATA_UUID16_SOME) {
            uint16_t uuid = net_buf_simple_pull_le16(buf);
            if (uuid == 0xFFFA) {
                LOG_INF("Remote ID detected: %s (RSSI: %d)", addr_str, rssi);
                // Parse Remote ID data here
            }
        }
        
        net_buf_simple_pull(buf, len - 1);
    }
}

int main(void)
{
    int err;
    
    LOG_INF("Starting Remote ID Scanner");
    
    err = bt_enable(NULL);
    if (err) {
        LOG_ERR("Bluetooth init failed (err %d)", err);
        return err;
    }
    
    struct bt_scan_param scan_param = {
        .type = BT_SCAN_TYPE_PASSIVE,
        .options = BT_SCAN_OPT_NONE,
        .interval = BT_GAP_SCAN_FAST_INTERVAL,
        .window = BT_GAP_SCAN_FAST_WINDOW,
    };
    
    err = bt_scan_start(&scan_param, scan_cb);
    if (err) {
        LOG_ERR("Scanning failed to start (err %d)", err);
        return err;
    }
    
    LOG_INF("Scanning for Remote ID broadcasts...");
    
    while (1) {
        k_sleep(K_SECONDS(1));
    }
    
    return 0;
}
```

### 3. Build and Flash

```bash
# Navigate to your project directory
cd remote_id_scanner

# Build for your target board
west build -b nrf52840dk_nrf52840
# or for USB dongle: west build -b nrf52840dongle_nrf52840

# Flash the firmware
west flash
```

## Method 2: Using Arduino IDE

### 1. Install Arduino NRF52 Support

```bash
# Add to Arduino IDE Board Manager URLs:
https://adafruit.github.io/arduino-board-index/package_adafruit_index.json

# Install "Adafruit nRF52" boards package
```

### 2. Arduino Remote ID Scanner Code

```cpp
// remote_id_scanner.ino
#include <bluefruit.h>

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);
  
  Serial.println("NRF52 Remote ID Scanner");
  
  // Initialize Bluefruit
  Bluefruit.begin();
  Bluefruit.setTxPower(4);
  
  // Set up scanning
  Bluefruit.Scanner.setRxCallback(scan_callback);
  Bluefruit.Scanner.restartOnDisconnect(true);
  Bluefruit.Scanner.setInterval(160, 80); // in unit of 0.625 ms
  Bluefruit.Scanner.useActiveScan(false);
  
  // Start scanning
  Bluefruit.Scanner.start(0);
  Serial.println("Scanning for Remote ID broadcasts...");
}

void scan_callback(ble_gap_evt_adv_report_t* report) {
  uint8_t buffer[32];
  memset(buffer, 0, sizeof(buffer));
  
  // Check if this is a Remote ID advertisement
  if (Bluefruit.Scanner.parseReportByType(report, BLE_GAP_AD_TYPE_16BIT_SERVICE_UUID_MORE_AVAILABLE, buffer, sizeof(buffer))) {
    uint16_t uuid = (buffer[1] << 8) | buffer[0];
    
    if (uuid == 0xFFFA) { // Remote ID Service UUID
      Serial.print("Remote ID detected - RSSI: ");
      Serial.print(report->rssi);
      Serial.print(", Address: ");
      Serial.printBuffer(report->peer_addr.addr, 6, ':');
      Serial.println();
      
      // Parse service data for Remote ID payload
      if (Bluefruit.Scanner.parseReportByType(report, BLE_GAP_AD_TYPE_SERVICE_DATA, buffer, sizeof(buffer))) {
        parse_remote_id_data(buffer, report->data_len);
      }
    }
  }
}

void parse_remote_id_data(uint8_t* data, uint8_t len) {
  if (len < 3) return;
  
  uint8_t message_type = data[0];
  
  switch(message_type) {
    case 0x0: // Basic ID
      Serial.println("  Type: Basic ID");
      break;
    case 0x1: // Location
      Serial.println("  Type: Location");
      break;
    case 0x2: // Auth
      Serial.println("  Type: Authentication");
      break;
    case 0x3: // Self ID
      Serial.println("  Type: Self ID");
      break;
    case 0x4: // System
      Serial.println("  Type: System");
      break;
    case 0x5: // Operator ID
      Serial.println("  Type: Operator ID");
      break;
    default:
      Serial.print("  Type: Unknown (");
      Serial.print(message_type);
      Serial.println(")");
  }
  
  Serial.print("  Data: ");
  for (int i = 0; i < len; i++) {
    Serial.print(data[i], HEX);
    Serial.print(" ");
  }
  Serial.println();
}

void loop() {
  // Scanner runs in background
  delay(1000);
}
```

### 3. Upload to Board

1. Select your NRF52 board in Arduino IDE
2. Select correct port
3. Upload the sketch

## Method 3: Using Python with NRF52 Dongle

### 1. Install Python Dependencies

```bash
pip install pynrfjprog
pip install nrfutil
pip install bleak  # For BLE communication
```

### 2. Python Remote ID Scanner

```python
#!/usr/bin/env python3
import asyncio
import struct
from bleak import BleakScanner
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REMOTE_ID_SERVICE_UUID = "0000FFFA-0000-1000-8000-00805F9B34FB"

def parse_remote_id_message(data):
    """Parse Remote ID message data"""
    if len(data) < 1:
        return
    
    message_type = data[0]
    message_types = {
        0x0: "Basic ID",
        0x1: "Location", 
        0x2: "Authentication",
        0x3: "Self ID",
        0x4: "System",
        0x5: "Operator ID"
    }
    
    msg_type_name = message_types.get(message_type, f"Unknown ({message_type})")
    logger.info(f"  Message Type: {msg_type_name}")
    logger.info(f"  Raw Data: {data.hex()}")
    
    if message_type == 0x1 and len(data) >= 20:  # Location message
        # Parse location data (simplified)
        lat = struct.unpack('<i', data[4:8])[0] * 1e-7
        lon = struct.unpack('<i', data[8:12])[0] * 1e-7
        alt = struct.unpack('<h', data[12:14])[0] * 0.5
        logger.info(f"  Location: {lat:.6f}, {lon:.6f}, Alt: {alt}m")

def detection_callback(device, advertisement_data):
    """Callback for BLE advertisements"""
    service_uuids = advertisement_data.service_uuids
    
    if REMOTE_ID_SERVICE_UUID in service_uuids:
        logger.info(f"Remote ID detected: {device.address} (RSSI: {device.rssi})")
        
        # Check service data
        service_data = advertisement_data.service_data
        for uuid, data in service_data.items():
            if uuid == REMOTE_ID_SERVICE_UUID:
                parse_remote_id_message(data)

async def main():
    """Main scanning loop"""
    logger.info("Starting NRF52 Remote ID Scanner")
    logger.info("Scanning for drone Remote ID broadcasts...")
    
    scanner = BleakScanner(detection_callback)
    
    try:
        await scanner.start()
        
        # Scan continuously
        while True:
            await asyncio.sleep(1.0)
            
    except KeyboardInterrupt:
        logger.info("Stopping scanner...")
    finally:
        await scanner.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

## Integration with CDDF

### Create NRF Remote ID Monitor

```python
#!/usr/bin/env python3
"""
NRF-based Remote ID monitor for CDDF
"""
import subprocess
import sys
import json
from datetime import datetime

class NRFRemoteIDMonitor:
    def __init__(self, device_path="/dev/ttyACM0"):
        self.device_path = device_path
        self.detections = []
    
    def start_monitoring(self):
        """Start monitoring for Remote ID broadcasts"""
        try:
            # Start the NRF scanner process
            process = subprocess.Popen([
                'python3', 'nrf_remote_id_scanner.py'
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            print("NRF Remote ID monitoring started", file=sys.stderr)
            
            for line in process.stdout:
                if "Remote ID detected" in line:
                    self.handle_detection(line.strip())
                    
        except KeyboardInterrupt:
            process.terminate()
            print("NRF Remote ID monitoring stopped", file=sys.stderr)
    
    def handle_detection(self, detection_line):
        """Handle a Remote ID detection"""
        timestamp = datetime.now().isoformat()
        detection = {
            'timestamp': timestamp,
            'source': 'nrf_remote_id',
            'data': detection_line
        }
        
        self.detections.append(detection)
        print(f"Drone Remote ID detected: {detection_line}", file=sys.stderr)
        
        # Output to stdout for integration with other tools
        print(json.dumps(detection))

if __name__ == "__main__":
    monitor = NRFRemoteIDMonitor()
    monitor.start_monitoring()
```

## Troubleshooting

### Common Issues

1. **Device not detected**
   - Check USB connection
   - Verify drivers are installed
   - Try different USB port

2. **Build errors**
   - Ensure SDK is properly installed
   - Check board configuration
   - Verify toolchain installation

3. **No Remote ID detections**
   - Confirm drones in area broadcast Remote ID
   - Check antenna connection
   - Verify frequency settings

4. **Permission errors**
   ```bash
   sudo usermod -a -G dialout $USER
   # Log out and back in
   ```

### Debug Commands

```bash
# List connected NRF devices
nrfjprog --ids

# Check device info
nrfjprog --deviceinfo

# Reset device
nrfjprog --reset

# Check serial connection
ls -la /dev/tty* | grep -E "(USB|ACM)"
```

## Performance Optimization

### Antenna Improvements
- Use external 2.4GHz antenna for better range
- Position antenna away from interference sources
- Consider directional antenna for focused scanning

### Power Management
- For battery-powered deployments, implement sleep modes
- Use interval-based scanning to conserve power
- Monitor battery voltage in firmware

### Data Processing
- Implement on-device filtering to reduce data transmission
- Use efficient data structures for storage
- Consider real-time vs. batch processing needs

## Legal and Safety Considerations

- Ensure compliance with local regulations
- Remote ID detection is generally legal for defensive purposes
- Do not interfere with legitimate drone operations
- Respect privacy and data protection laws
- Use captured data responsibly

## References

- [Nordic nRF52840 Product Page](https://www.nordicsemi.com/products/nrf52840)
- [nRF Connect SDK Documentation](https://docs.nordicsemi.com/bundle/ncs-latest/page/nrf/index.html)
- [Remote ID Bluetooth Specification](https://www.faa.gov/uas/getting_started/remote_id/)
- [ASTM F3411 Standard](https://www.astm.org/f3411-22a.html)