# Kismet to RabbitMQ Queuer

A Python application that connects to Kismet's WebSocket API, consumes device messages and alerts, and publishes them to RabbitMQ with appropriate topic routing.

## Features

- Connects to Kismet WebSocket API (default: localhost:2501)
- Consumes all device messages and alerts
- Formats messages with hostname, timestamp, and device data
- Publishes to RabbitMQ with topic-based routing
- Automatic reconnection handling
- Configurable via INI file
- Multiple deployment options (manual scripts or Ansible)

## Project Structure

```
kismet-queuer/
├── src/                    # Application source code
│   ├── kismet_to_queue.py  # Main application
│   └── requirements.txt    # Python dependencies
├── config/                 # Configuration files
│   └── config.ini.example  # Example configuration
├── systemd/                # Systemd service files
│   └── kismet_to_queue.service
├── scripts/                # Installation scripts
│   ├── install_service.sh
│   └── uninstall_service.sh
├── ansible/                # Ansible deployment
│   ├── playbook.yml
│   ├── inventory.example
│   └── roles/kismet-queuer/
└── README.md
```

## Installation

### Option 1: Quick Start (Manual Installation)

1. Clone the repository:
```bash
git clone <repository-url>
cd kismet-queuer
```

2. Install dependencies:
```bash
pip3 install -r src/requirements.txt
```

3. Configure the application:
```bash
cp config/config.ini.example config/config.ini
nano config/config.ini  # Edit with your settings
```

4. Run the application:
```bash
python3 src/kismet_to_queue.py config/config.ini
```

### Option 2: Systemd Service (Automated Installation)

Run the installation script:
```bash
sudo ./scripts/install_service.sh
```

This will install dependencies, configure the service, and start it automatically.

### Option 3: Ansible Deployment

For automated deployment to multiple servers, see [ansible/README.md](ansible/README.md).

## Configuration

1. Copy the example configuration file (if not already done):
```bash
cp config/config.ini.example config/config.ini
```

2. Edit `config/config.ini` with your settings:

```ini
[kismet]
host = localhost
port = 2501
username = 
password = 
api_key = 

[rabbitmq]
host = localhost
port = 5672
username = guest
password = guest
virtual_host = /
exchange = kismet_events
exchange_type = topic

[logging]
level = INFO
format = %(asctime)s - %(name)s - %(levelname)s - %(message)s

[general]
reconnect_delay = 5
max_reconnect_attempts = 10
```

### Configuration Options

- **Kismet Settings**:
  - `host`: Kismet server hostname
  - `port`: Kismet WebSocket port (default: 2501)
  - `username/password`: Optional HTTP basic auth
  - `api_key`: Optional API key authentication

- **RabbitMQ Settings**:
  - `host/port`: RabbitMQ server connection details
  - `username/password`: RabbitMQ credentials
  - `virtual_host`: RabbitMQ virtual host
  - `exchange`: Exchange name for publishing messages
  - `exchange_type`: Exchange type (recommended: topic)

## Usage

Run the application with the default config location:

```bash
python3 src/kismet_to_queue.py config/config.ini
```

Or specify a custom configuration file:

```bash
python3 src/kismet_to_queue.py /path/to/config.ini
```

## Message Format

Messages are published to RabbitMQ in JSON format:

```json
{
  "hostname": "system_hostname",
  "timestamp": "2025-10-25T12:34:56Z",
  "source": "kismet",
  "message_type": "device|alert|message|unknown",
  "device_data": {
    // Kismet device/alert data
  },
  "raw_data": {
    // Complete raw Kismet message
  }
}
```

## Topic Routing

Messages are routed using the pattern: `kismet.{message_type}.{device_type}`

Examples:
- `kismet.device.wifi` - WiFi device updates
- `kismet.device.bluetooth` - Bluetooth device updates  
- `kismet.alert.proximity` - Proximity alerts
- `kismet.message.system` - System messages

## Requirements

- Python 3.7+
- Kismet server with WebSocket API enabled
- RabbitMQ server
- Dependencies listed in `requirements.txt`

## Dependencies

- `websockets` - Async WebSocket client for Kismet API
- `aio-pika` - Async RabbitMQ client library
- `configparser` - Configuration file parsing (built-in)

All dependencies can be installed with:
```bash
pip3 install -r src/requirements.txt
```

## Logging

The application logs to stdout with configurable levels:
- DEBUG: Detailed debugging information
- INFO: General operational information
- WARNING: Warning messages
- ERROR: Error messages

## Troubleshooting

1. **Connection issues**: Verify Kismet and RabbitMQ are running and accessible
2. **Authentication**: Check credentials in config.ini
3. **WebSocket errors**: Ensure Kismet WebSocket API is enabled on port 2501
4. **RabbitMQ errors**: Verify exchange permissions and network connectivity

## Systemd Service

A systemd service file is provided in `systemd/` for easy deployment and management.

### Installation

1. Run the installation script from the project root (requires sudo):
```bash
sudo ./scripts/install_service.sh
```

This script will:
- Create a dedicated `kismet-queuer` system user
- Install Python dependencies from `src/requirements.txt`
- Create `config/config.ini` from the example if it doesn't exist
- Copy the service file to `/etc/systemd/system/` with correct paths
- Enable and start the service

### Service Management

```bash
# Check service status
sudo systemctl status kismet_to_queue

# View logs
sudo journalctl -u kismet_to_queue -f

# Restart service
sudo systemctl restart kismet_to_queue

# Stop service
sudo systemctl stop kismet_to_queue

# Disable service (prevent auto-start)
sudo systemctl disable kismet_to_queue
```

### Uninstallation

To remove the systemd service:
```bash
sudo ./scripts/uninstall_service.sh
```

### Service Configuration

The service file (`systemd/kismet_to_queue.service`) includes:
- Runs as dedicated low-privilege user (kismet-queuer)
- Auto-restart on failure (5 attempts within 5 minutes)
- Security hardening (NoNewPrivileges, PrivateTmp, ProtectSystem, ProtectHome)
- Journal logging with syslog identifier
- Network dependency management

## License

[Add your license information here]