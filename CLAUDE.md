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

Optional HackRF support (drone-rf-detect; needs libhackrf-dev):
```bash
pip install -e ".[hackrf]"
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

- **LoRa Mesh Relay** (`drone_lora.py`)
  - Broadcasts/receives compact drone detection events between nodes over a Meshtastic radio (USB-serial or TCP)
  - Meshtastic handles mesh routing, encryption, addressing, and sender node ID; this module adds a bit-packed binary codec (fits Meshtastic's ~237-byte payload) and a thin link layer
  - Detection frames ride a private Meshtastic port number (`PRIVATE_APP`) so they stay off the text channel
  - `DetectionThrottle` rate-limits broadcasts (default: one per drone_id, else per detector type, per interval) so duty-cycle limits aren't blown; pass it to `MeshLink(throttle=...)` and `broadcast()` returns False when suppressed
  - Codec (`DetectionEvent`/`encode_event`/`decode_event`) and `DetectionThrottle` have no hardware dependency; radio layer (`MeshLink`) needs the optional `lora` extra (`pip install -e ".[lora]"`)

- **LoRa → RabbitMQ Bridge** (`lora_to_queue.py`)
  - Gateway node: receives detection events over the Meshtastic mesh and republishes them to the same RabbitMQ exchange as kismet-queuer, so off-grid detections reach the central pipeline once any node has connectivity
  - Reuses the kismet-queuer INI format (`[rabbitmq]`/`[logging]` sections) — point both at one shared config
  - Routing key `cddf.detection.{detector}` (separate namespace from kismet's `kismet.*`); message envelope mirrors `kismet_to_queue.py` with link metadata under a `lora` key
  - Marries Meshtastic's threaded callbacks to async aio-pika via a bounded `asyncio.Queue`; needs the optional `lora-bridge` extra (`pip install -e ".[lora-bridge]"`)

- **Detection Emit / Sinks** (`detection_emit.py`)
  - Decouples detectors from transport: a detector calls `emitter.emit(DetectionEvent(...))` and a `DetectionEmitter` fans it out to the sinks a node is configured for
  - `RabbitMQSink` publishes directly to the central broker over AMQP (runs aio-pika on a background loop so its `emit()` is synchronous and non-blocking for sync detectors); `LoRaSink` broadcasts over the mesh (off-grid); `StdoutSink` prints locally
  - Per-sink failures are isolated — a dead broker or unplugged radio never stops the other sinks or the detector
  - Topology is pure config: `build_emitter`/`load_emitter` read an `[emit] sinks = ...` INI section (see `emit.ini.example`). Hybrid nodes set `sinks = rabbitmq, lora` to publish directly *and* relay over LoRa
  - Owns the canonical `format_detection_message`/`routing_key`/`event_to_dict` (lora_to_queue imports them); `drone-emit-test` sends one sample event through a node's configured emitter to verify setup
  - `RabbitMQSink` needs the `amqp` extra, `LoRaSink` the `lora` extra; a hybrid node installs `pip install -e ".[amqp,lora]"`
  - **Every detector accepts `--emit-config PATH`** (added via `add_emit_args`/`open_emitter`): without it detections only print; with it they're also emitted to the configured sinks. Continuous detectors (audio monitor, Wi-Fi, BLE) emit per detection; one-shot detectors (audio file, RF, RTL) emit once if a drone is found. The Wi-Fi path combines Basic ID + Location/Vector from one beacon into a single event; `RabbitMQSink.close()` drains pending events so one-shot emits aren't lost

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
