# How to Setup Sniffle-to-Kismet Integration for Drone Detection

## Overview

Kismet is a powerful wireless network and device detector that can be extended with custom data sources. By integrating Sniffle (BLE sniffer) with Kismet, you can create a unified platform for detecting drones via Remote ID broadcasts alongside traditional WiFi-based detection. This integration provides centralized logging, web interface, and enhanced analysis capabilities.

## Prerequisites

### Hardware
- **TI CC2652R or CC1352R development board** with Sniffle firmware flashed
- **Computer** running Linux (recommended) or macOS
- **USB cable** for connecting the board

### Software Requirements
- **Kismet 2022.02.R1** or later
- **Python 3.7+** with development headers
- **Sniffle** already installed and working
- **Git** for repository cloning

## Installation Steps

### 1. Install Kismet

#### Ubuntu/Debian
```bash
# Add Kismet repository
wget -O - https://www.kismetwireless.net/repos/kismet-release.gpg.key | sudo apt-key add -
echo 'deb https://www.kismetwireless.net/repos/apt/release/jammy jammy main' | sudo tee /etc/apt/sources.list.d/kismet.list

# Update and install
sudo apt update
sudo apt install kismet
```

#### CentOS/RHEL/Fedora
```bash
# Install from source or use kismet-wireless repo
sudo dnf install kismet
```

#### macOS
```bash
# Using Homebrew
brew install kismet
```

### 2. Configure Kismet for External Data Sources

Edit Kismet configuration:
```bash
sudo nano /etc/kismet/kismet.conf
```

Add or modify these settings:
```
# Enable external helper binaries
helper_binary_path=/usr/local/bin:/usr/bin:/bin

# Allow external data sources
alloweduser=kismet
alloweduser=$USER

# Enable remote capture
remote_capture_listen=127.0.0.1
remote_capture_port=3501

# Log configuration
log_types=kismet,pcapng,alert
log_template=/tmp/kismet-%n-%d-%t-%i.%l
```

### 3. Create Sniffle-to-Kismet Bridge

Create the integration script:

```bash
mkdir -p ~/cddf-kismet-integration
cd ~/cddf-kismet-integration
```

#### Main Bridge Script

Create `sniffle_kismet_bridge.py`:

```python
#!/usr/bin/env python3
"""
Sniffle to Kismet Bridge for Remote ID Detection
Converts Sniffle BLE captures to Kismet-compatible format
"""

import json
import time
import socket
import struct
import threading
import subprocess
import argparse
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SniffleKismetBridge:
    def __init__(self, kismet_host='127.0.0.1', kismet_port=3501, sniffle_device='/dev/ttyACM0'):
        self.kismet_host = kismet_host
        self.kismet_port = kismet_port
        self.sniffle_device = sniffle_device
        self.kismet_socket = None
        self.sniffle_process = None
        self.running = False
        
        # Remote ID message types
        self.remote_id_types = {
            0x0: "Basic ID",
            0x1: "Location",
            0x2: "Authentication", 
            0x3: "Self ID",
            0x4: "System",
            0x5: "Operator ID"
        }
    
    def connect_to_kismet(self):
        """Establish connection to Kismet server"""
        try:
            self.kismet_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.kismet_socket.connect((self.kismet_host, self.kismet_port))
            
            # Send Kismet data source announcement
            announce_msg = {
                "cmd": "KDSSOURCE",
                "source": "sniffle_remote_id",
                "uuid": "sniffle-remote-id-001",
                "type": "ble_remote_id",
                "definition": "sniffle_remote_id:device={}".format(self.sniffle_device),
                "capture": True
            }
            
            self.send_kismet_message(announce_msg)
            logger.info("Connected to Kismet server")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Kismet: {e}")
            return False
    
    def send_kismet_message(self, message):
        """Send formatted message to Kismet"""
        if self.kismet_socket:
            try:
                msg_json = json.dumps(message) + "\n"
                self.kismet_socket.send(msg_json.encode())
            except Exception as e:
                logger.error(f"Failed to send message to Kismet: {e}")
    
    def start_sniffle_capture(self):
        """Start Sniffle capture process"""
        try:
            # Start Sniffle with JSON output for easier parsing
            cmd = [
                'python3', 'sniffle_hw.py',
                '-s', '0xFFFA',  # Remote ID service UUID
                '-a',            # Advertisement only
                '-l',            # Live output
                '-j'             # JSON output (if supported)
            ]
            
            self.sniffle_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd='/path/to/sniffle'  # Update with actual Sniffle path
            )
            
            logger.info("Started Sniffle capture process")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start Sniffle: {e}")
            return False
    
    def parse_sniffle_output(self, line):
        """Parse Sniffle output and extract Remote ID data"""
        try:
            # Parse Sniffle output format
            # Format may vary - adapt based on your Sniffle version
            if "Remote ID" in line or "FFFA" in line:
                # Extract relevant data
                timestamp = time.time()
                
                # Create device record for Kismet
                device_data = {
                    "cmd": "DEVICE",
                    "data": {
                        "kismet.device.base.macaddr": self.extract_mac_address(line),
                        "kismet.device.base.type": "Drone Remote ID",
                        "kismet.device.base.first_time": timestamp,
                        "kismet.device.base.last_time": timestamp,
                        "kismet.device.base.signal": self.extract_rssi(line),
                        "kismet.device.base.channel": "BLE",
                        "kismet.device.base.frequency": 2400000000,  # 2.4GHz
                        "drone.remote_id.detected": True,
                        "drone.remote_id.message": self.parse_remote_id_message(line),
                        "drone.remote_id.raw_data": line.strip()
                    }
                }
                
                return device_data
                
        except Exception as e:
            logger.error(f"Error parsing Sniffle output: {e}")
        
        return None
    
    def extract_mac_address(self, line):
        """Extract MAC address from Sniffle output"""
        # Implementation depends on Sniffle output format
        # This is a placeholder - adapt to actual format
        import re
        mac_pattern = r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})'
        match = re.search(mac_pattern, line)
        return match.group() if match else "00:00:00:00:00:00"
    
    def extract_rssi(self, line):
        """Extract RSSI value from Sniffle output"""
        import re
        rssi_pattern = r'RSSI:\s*(-?\d+)'
        match = re.search(rssi_pattern, line)
        return int(match.group(1)) if match else -100
    
    def parse_remote_id_message(self, line):
        """Parse Remote ID message content"""
        # Simplified parser - enhance based on actual data format
        message_info = {
            "detected": True,
            "timestamp": datetime.now().isoformat(),
            "raw_line": line.strip()
        }
        
        # Add more sophisticated parsing here
        for msg_type, msg_name in self.remote_id_types.items():
            if msg_name.lower().replace(' ', '_') in line.lower():
                message_info["type"] = msg_name
                message_info["type_id"] = msg_type
                break
        
        return message_info
    
    def process_sniffle_output(self):
        """Process Sniffle output in separate thread"""
        if not self.sniffle_process:
            return
            
        try:
            for line in iter(self.sniffle_process.stdout.readline, ''):
                if not self.running:
                    break
                    
                # Parse and forward to Kismet
                device_data = self.parse_sniffle_output(line)
                if device_data:
                    self.send_kismet_message(device_data)
                    logger.info(f"Sent Remote ID detection to Kismet: {line.strip()}")
                    
        except Exception as e:
            logger.error(f"Error processing Sniffle output: {e}")
    
    def run(self):
        """Main execution loop"""
        logger.info("Starting Sniffle-to-Kismet bridge")
        
        # Connect to Kismet
        if not self.connect_to_kismet():
            return False
        
        # Start Sniffle capture
        if not self.start_sniffle_capture():
            return False
        
        self.running = True
        
        # Start output processing thread
        output_thread = threading.Thread(target=self.process_sniffle_output)
        output_thread.daemon = True
        output_thread.start()
        
        try:
            logger.info("Bridge running - Press Ctrl+C to stop")
            while self.running:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Stopping bridge...")
            self.stop()
    
    def stop(self):
        """Stop the bridge"""
        self.running = False
        
        if self.sniffle_process:
            self.sniffle_process.terminate()
            self.sniffle_process.wait()
        
        if self.kismet_socket:
            self.kismet_socket.close()
        
        logger.info("Bridge stopped")

def main():
    parser = argparse.ArgumentParser(description='Sniffle to Kismet Bridge')
    parser.add_argument('--kismet-host', default='127.0.0.1', help='Kismet server host')
    parser.add_argument('--kismet-port', type=int, default=3501, help='Kismet server port')
    parser.add_argument('--sniffle-device', default='/dev/ttyACM0', help='Sniffle device path')
    
    args = parser.parse_args()
    
    bridge = SniffleKismetBridge(
        kismet_host=args.kismet_host,
        kismet_port=args.kismet_port,
        sniffle_device=args.sniffle_device
    )
    
    bridge.run()

if __name__ == "__main__":
    main()
```

### 4. Create Kismet Data Source Plugin

Create `kismet_sniffle_datasource.py`:

```python
#!/usr/bin/env python3
"""
Kismet data source for Sniffle Remote ID detection
"""

import json
import sys
import time
from kismetexternal import DatasourceSubprocess

class SniffleRemoteIDDatasource(DatasourceSubprocess):
    def __init__(self):
        super().__init__()
        
        self.set_int_datasource_timeout(5)
        self.set_int_datasource_retry(True)
        
    def run_datasource(self):
        """Main data source execution"""
        self.send_datasource_open_report()
        
        # Integration with existing Sniffle process
        from sniffle_kismet_bridge import SniffleKismetBridge
        
        bridge = SniffleKismetBridge()
        
        try:
            while not self.should_exit():
                # Process data and send to Kismet
                time.sleep(0.1)
                
        except Exception as e:
            self.send_datasource_error_report(f"Sniffle datasource error: {e}")
        
        self.send_datasource_close_report()

if __name__ == "__main__":
    datasource = SniffleRemoteIDDatasource()
    datasource.run()
```

### 5. Configure Service Files

Create systemd service for automatic startup:

```bash
sudo nano /etc/systemd/system/sniffle-kismet.service
```

```ini
[Unit]
Description=Sniffle to Kismet Bridge for Drone Remote ID Detection
After=network.target
Requires=kismet.service

[Service]
Type=simple
User=kismet
Group=kismet
ExecStart=/usr/bin/python3 /home/kismet/cddf-kismet-integration/sniffle_kismet_bridge.py
Restart=always
RestartSec=10
Environment=PYTHONPATH=/home/kismet/cddf-kismet-integration

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable sniffle-kismet.service
sudo systemctl start sniffle-kismet.service
```

## Integration with CDDF

### Create CDDF-Kismet Monitor

```python
#!/usr/bin/env python3
"""
CDDF integration with Kismet for comprehensive drone detection
"""

import requests
import json
import time
import sys
from datetime import datetime

class CDDFKismetIntegration:
    def __init__(self, kismet_url="http://localhost:2501"):
        self.kismet_url = kismet_url
        self.session = requests.Session()
        
    def get_kismet_devices(self):
        """Retrieve devices from Kismet"""
        try:
            response = self.session.get(f"{self.kismet_url}/devices/views/all/devices.json")
            return response.json() if response.status_code == 200 else []
        except Exception as e:
            print(f"Error connecting to Kismet: {e}", file=sys.stderr)
            return []
    
    def filter_drone_devices(self, devices):
        """Filter for drone-related devices"""
        drone_devices = []
        
        for device in devices:
            # Check for Remote ID indicators
            if any([
                device.get('kismet.device.base.type', '').lower().find('drone') != -1,
                device.get('kismet.device.base.type', '').lower().find('remote id') != -1,
                device.get('drone.remote_id.detected', False)
            ]):
                drone_devices.append(device)
        
        return drone_devices
    
    def generate_cddf_alert(self, device):
        """Generate CDDF-compatible alert"""
        alert = {
            'timestamp': datetime.now().isoformat(),
            'source': 'kismet_remote_id',
            'device_mac': device.get('kismet.device.base.macaddr', 'unknown'),
            'device_type': device.get('kismet.device.base.type', 'unknown'),
            'signal_strength': device.get('kismet.device.base.signal', 0),
            'first_seen': device.get('kismet.device.base.first_time', 0),
            'last_seen': device.get('kismet.device.base.last_time', 0),
            'remote_id_data': device.get('drone.remote_id.message', {})
        }
        
        return alert
    
    def monitor(self):
        """Main monitoring loop"""
        print("Starting CDDF-Kismet integration monitor", file=sys.stderr)
        
        try:
            while True:
                devices = self.get_kismet_devices()
                drone_devices = self.filter_drone_devices(devices)
                
                for device in drone_devices:
                    alert = self.generate_cddf_alert(device)
                    
                    # Output to stdout for integration
                    print(json.dumps(alert))
                    
                    # Log to stderr
                    print(f"Drone detected via Kismet: {device.get('kismet.device.base.macaddr')}", 
                          file=sys.stderr)
                
                time.sleep(5)  # Check every 5 seconds
                
        except KeyboardInterrupt:
            print("CDDF-Kismet monitor stopped", file=sys.stderr)

if __name__ == "__main__":
    monitor = CDDFKismetIntegration()
    monitor.monitor()
```

## Usage and Testing

### 1. Start Kismet Server

```bash
sudo kismet
```

Access web interface at: `http://localhost:2501`

### 2. Start Sniffle-Kismet Bridge

```bash
cd ~/cddf-kismet-integration
python3 sniffle_kismet_bridge.py
```

### 3. Verify Integration

Check Kismet web interface for:
- New data source: "sniffle_remote_id"
- Device detections with type "Drone Remote ID"
- Remote ID message data in device details

### 4. Test with CDDF

```bash
# Run integrated detection
python3 cddf_kismet_integration.py &
python3 drone_audio_monitor.py &
python3 drone_rf_detection.py &
```

## Advanced Configuration

### Kismet Alerting

Add custom alerts in `kismet.conf`:
```
alert=DRONEDETECTED,5/min,Remote ID drone detected
alert=DRONELOCATION,1/min,Drone location broadcast detected
```

### Database Integration

Configure Kismet database logging:
```
db_log_devices=true
db_log_alerts=true
db_file=/var/log/kismet/kismet.db
```

### Web Interface Customization

Custom drone detection panel for Kismet web UI:
```javascript
// kismet_drone_panel.js
kismet.load_css('drone_detection.css');

kismet.add_gauge_component({
    id: 'drone_detection_gauge',
    title: 'Drone Detections',
    type: 'number',
    value: function() {
        return kismet_ui.last_devicelist.length;
    }
});
```

## Troubleshooting

### Common Issues

1. **Connection refused to Kismet**
   ```bash
   # Check if Kismet is running
   sudo systemctl status kismet
   
   # Check port binding
   netstat -tlnp | grep 2501
   ```

2. **Sniffle device not found**
   ```bash
   # List USB devices
   lsusb | grep -i texas
   
   # Check device permissions
   ls -la /dev/ttyACM*
   sudo usermod -a -G dialout $USER
   ```

3. **No data appearing in Kismet**
   ```bash
   # Check bridge logs
   journalctl -u sniffle-kismet -f
   
   # Test Sniffle independently
   python3 sniffle_hw.py -a -s 0xFFFA
   ```

### Debug Mode

Run bridge with verbose logging:
```bash
python3 sniffle_kismet_bridge.py --debug --kismet-host 127.0.0.1
```

## Security Considerations

- Configure Kismet authentication for web interface
- Limit network access to Kismet ports
- Regularly update both Kismet and Sniffle
- Monitor log files for suspicious activity
- Ensure compliance with local surveillance regulations

## Performance Optimization

### System Resources
- Allocate sufficient RAM for device tracking
- Use SSD storage for better database performance
- Monitor CPU usage during active scanning

### Network Configuration
- Use wired connection for Kismet server
- Configure appropriate buffer sizes
- Implement log rotation to prevent disk fill

## References

- [Kismet Documentation](https://kismetwireless.net/docs/)
- [Kismet External Data Sources](https://kismetwireless.net/docs/dev/datasource_external/)
- [Sniffle GitHub Repository](https://github.com/nccgroup/Sniffle)
- [Remote ID Standards](https://www.faa.gov/uas/getting_started/remote_id/)