# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CDDF (Citizen Drone Defense Force) is a multi-modal drone detection and analysis toolkit with two main components:

1. **drone_tools** - Python package for detecting drones via audio, RF signals, WiFi Remote ID, and vision analysis
2. **kismet-queuer** - Standalone application that bridges Kismet WebSocket API to RabbitMQ for distributed sensor networks

## Development Commands

### Python Package (drone_tools)

Install in development mode:
```bash
pip install -e .
```

Install with dev dependencies:
```bash
pip install -e ".[dev]"
```

Run tests:
```bash
pytest
pytest tests/test_drone_audio_detection.py  # Run single test file
pytest -v                                    # Verbose output
pytest --cov=drone_tools                     # With coverage
```

Linting and type checking:
```bash
ruff check .                                 # Lint
ruff format .                                # Format
mypy drone_tools                             # Type check
```

Run tools as modules (without installation):
```bash
python -m drone_tools.drone_audio_detection path/to/audio.wav
python -m drone_tools.drone_wifi_remote_id wlan0
```

Run installed console scripts (after `pip install -e .`):
```bash
drone-audio-detect path/to/audio.wav        # File-based audio analysis
drone-audio-monitor                          # Real-time microphone monitoring
drone-wifi-remote-id wlan0                  # WiFi Remote ID capture
drone-rf-detect --freq 2.4e9               # HackRF RF detection
drone-rtl-power-detect                      # RTL-SDR scanning
drone-rtl-power-visualize                   # Frequency heatmap visualization
drone-image-query "a DJI drone"             # Generate image via DALL-E
drone-describe-image path/to/image.jpg      # Identify drone in image via Vision API
```

### Kismet Queuer

Run manually:
```bash
cd kismet-queuer
pip3 install -r src/requirements.txt
python3 src/kismet_to_queue.py config/config.ini
```

Install as systemd service:
```bash
cd kismet-queuer
sudo ./scripts/install_service.sh          # Install and start (auto-detects paths)
sudo systemctl status kismet_to_queue      # Check status
sudo journalctl -u kismet_to_queue -f      # View logs
sudo ./scripts/uninstall_service.sh        # Remove service
```

### Ansible Deployment

Deploy CDDF edge nodes (Watchtower stack with Kismet):
```bash
cd ansible
ansible-inventory -i inventory.ini --list                                    # List hosts
ansible all -i inventory.ini -m ping                                         # Test connectivity
ansible-playbook edge-node-watchtower-playbook.yml -i inventory.ini --ask-become-pass
ansible-playbook edge-node-watchtower-playbook.yml -i inventory.ini --limit cddf-watchtower-a.local --ask-become-pass
```

Deploy kismet-queuer service:
```bash
cd kismet-queuer/ansible
ansible-playbook playbook.yml -i inventory -u pi --become --ask-become-pass
```

## Architecture

### drone_tools Package

**Multi-modal detection system** with independent modules for different sensor types:

- **Audio Detection** (`drone_audio_detection.py`, `drone_audio_monitor.py`)
  - Frequency analysis in 100-700Hz band (drone motor/rotor noise)
  - File-based and real-time microphone monitoring
  - Uses numpy/soundfile/sounddevice for signal processing

- **RF Detection** (`drone_rf_detection.py`, `drone_rtl_power_detection.py`)
  - HackRF One integration for broadband scanning (2.4GHz, 5.8GHz control frequencies)
  - RTL-SDR integration via `rtl_power` utility
  - Monitors drone control signals separate from Remote ID

- **WiFi Remote ID** (`drone_wifi_remote_id.py`)
  - Captures ASTM F3411 compliant Remote ID broadcasts
  - Parses vendor-specific WiFi elements with OUI `0x903ae6`
  - Extracts drone ID, location, operator info from beacon frames
  - Uses scapy for packet sniffing (requires monitor mode)

- **Vision Analysis** (`image_query.py`, `drone_description.py`)
  - OpenAI DALL-E for image generation from text prompts
  - OpenAI Vision API for drone type identification in images
  - Requires `OPENAI_API_KEY` environment variable

- **Visualization** (`rtl_power_visualization.py`)
  - Creates frequency spectrum heatmaps from RTL-SDR output

- **Testing/Mock** (`mock_sniffle_remote_id.py`)
  - Simulates Sniffle BLE sniffer output for Remote ID testing
  - Generates realistic ASTM F3411 packets without hardware

All tools are registered as console scripts in `pyproject.toml` with `drone-*` prefix.

### Test Suite

Tests live in `tests/` and cover the core drone_tools modules:

- `test_drone_audio_detection.py`
- `test_drone_audio_monitor.py`
- `test_drone_description.py`
- `test_drone_rf_detection.py`
- `test_drone_rtl_power_detection.py`
- `test_drone_rtl_power_visualization.py`

### kismet-queuer Application

**Async message broker bridge** for distributed sensor networks:

- Connects to Kismet WebSocket API (default port 2501)
- Consumes device messages and alerts in real-time
- Publishes to RabbitMQ topic exchange with routing pattern: `kismet.{message_type}.{device_type}`
- Message format includes hostname, timestamp, device data, and raw Kismet payload
- Automatic reconnection handling with configurable retry logic
- Runs as systemd service with dedicated low-privilege `kismet-queuer` user
- Configuration via INI file (`config/config.ini`, based on `config/config.ini.example`)
- Uses `aio-pika` for fully async RabbitMQ publishing (dependencies: `websockets`, `aio-pika`, `configparser`)

### Edge Node Deployment

**Watchtower stack** for field deployment (Raspberry Pi targets):

- `install_edge_node.sh` - Bash script for manual provisioning
- `ansible/edge-node-watchtower-playbook.yml` - Automated Ansible provisioning
- Installs: Python dependencies, RTL-SDR/HackRF drivers, Kismet with data sources
- Target OS: Raspberry Pi OS (Debian-based)
- Default user: `pi` with sudo access

**kismet-queuer Ansible role** (`kismet-queuer/ansible/roles/kismet-queuer/`):

- `tasks/main.yml` - Deployment steps
- `templates/config.ini.j2` - Dynamic config generation
- `templates/kismet_to_queue.service.j2` - Systemd service template
- `defaults/main.yml` - Customizable variables
- `handlers/main.yml` - Service restart handlers
- `vars/credentials.yml.example` - Credentials template (use Ansible Vault in production)

## Hardware Dependencies

- **HackRF One**: For `drone_rf_detection.py` (requires `pyhackrf` and `libhackrf-dev`)
- **RTL-SDR**: For `drone_rtl_power_detection.py` (requires `rtl-sdr` package and `rtl_power` utility)
- **WiFi adapter with monitor mode**: For `drone_wifi_remote_id.py` (may need root privileges)
- **Microphone/audio device**: For `drone_audio_monitor.py`

## Key Configuration Files

- `pyproject.toml` - Python package metadata, dependencies, console scripts
- `requirements.txt` - Top-level dependencies for drone_tools
- `kismet-queuer/config/config.ini.example` - Kismet and RabbitMQ config template (copy to `config.ini`)
- `kismet-queuer/src/requirements.txt` - kismet-queuer dependencies (aio-pika, websockets)
- `ansible/inventory.ini` - Watchtower edge node hosts
- `kismet-queuer/ansible/inventory.example` - Kismet-queuer deployment targets template

## Remote ID Standards

This project implements **ASTM F3411** Remote ID standard:
- WiFi OUI: `0x903ae6`
- Message types: Basic ID (0), Location/Vector (1), Authentication (2), Self ID (3), System (4), Operator ID (5)
- Protocols: WiFi Nan beacons and BLE advertisements
- See `howto/` directory for hardware setup guides:
  - `nrf-drone-remote-id-setup.md` - nRF52 setup
  - `sniffle-drone-remote-id-setup.md` - Sniffle BLE sniffer setup
  - `sniffle-kismet-integration-setup.md` - Sniffle + Kismet integration
