# cddf

Citizen Drone Defense Force


This repository contains a comprehensive suite of drone detection and analysis utilities across multiple modalities. The toolkit includes:

## Overview

### Image Processing & Generation
- **`image_query.py`** - Generates drone-related images from text prompts using OpenAI's DALL-E API
- **`drone_description.py`** - Analyzes drone images using OpenAI's vision models to identify drone types and characteristics

### Audio Detection
- **`drone_audio_detection.py`** - Detects drone sounds in audio files using frequency analysis (100-700Hz range)
- **`drone_audio_monitor.py`** - Real-time monitoring for drone sounds using microphone input, designed for continuous surveillance

### RF Signal Detection
- **`drone_rf_detection.py`** - Detects drone RF control signals without remote ID beacons using HackRF One hardware
- **`drone_rtl_power_detection.py`** - Scans for drone RF activity using RTL-SDR dongles and the `rtl_power` utility
- **`drone_wifi_remote_id.py`** - Captures drone Remote ID information broadcast over WiFi according to ASTM F3411 standard
- **`mock_sniffle_remote_id.py`** - Mock Sniffle BLE sniffer for Remote ID simulation, generates realistic ASTM F3411 Remote ID packets for testing and development without requiring actual hardware

### Visualization & Analysis
- **`rtl_power_visualization.py`** - Creates frequency spectrum heatmaps from RTL-SDR data for visual analysis

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. For OpenAI features (image generation/analysis), set the `OPENAI_API_KEY` environment variable:
   ```bash
   export OPENAI_API_KEY="your_api_key_here"
   ```

3. For RF detection features, ensure you have the appropriate hardware:
   - **HackRF One**: For `drone_rf_detection.py`
   - **RTL-SDR dongle**: For `drone_rtl_power_detection.py` and visualization tools
   - Install `rtl_power` utility for RTL-SDR functionality

4. For WiFi Remote ID capture:
   - **WiFi adapter with monitor mode support**: For `drone_wifi_remote_id.py`
   - Install `scapy` package (included in requirements.txt)
   - May require root/administrator privileges for packet capture

5. For audio monitoring, ensure your microphone/audio device is properly configured

## Usage

### Image Processing

Generate drone-related images from text prompts:
```bash
python -m drone_tools.image_query "a futuristic drone flying over a city"
```

Analyze and identify drone types in images:
```bash
python -m drone_tools.drone_description path/to/drone_image.jpg
```

### Audio Detection

Detect drone sounds in audio files:
```bash
python -m drone_tools.drone_audio_detection path/to/recording.wav --low 100 --high 700 --threshold 0.2
```

Monitor microphone in real-time for drone sounds:
```bash
python -m drone_tools.drone_audio_monitor --device 0 --samplerate 16000
```

### RF Signal Detection

Scan for drone control signals without remote ID using HackRF One:
```bash
python -m drone_tools.drone_rf_detection --freq 2.4e9 --freq 5.8e9 --remote-id-freq 2.433e9
```

Detect drone RF activity using RTL-SDR:
```bash
python -m drone_tools.drone_rtl_power_detection --range 2400M:2483M:1M --threshold -30
```

Capture drone Remote ID broadcasts over WiFi:
```bash
python -m drone_tools.drone_wifi_remote_id wlan0
```

For WiFi adapters with filter issues:
```bash
python -m drone_tools.drone_wifi_remote_id wlan0 --no-filter
```

Simulate Remote ID broadcasts for testing (mock Sniffle output):
```bash
python -m drone_tools.mock_sniffle_remote_id            # Run indefinitely
python -m drone_tools.mock_sniffle_remote_id -t 30      # Run for 30 seconds
python -m drone_tools.mock_sniffle_remote_id -v         # Verbose output with decoded packets
```

### Visualization

Create frequency spectrum heatmaps from RTL-SDR data:
```bash
python -m drone_tools.rtl_power_visualization rtl_power_data.csv -o spectrum_plot.png
```

#### Additionally you can run
```bash
pip install -e .
```
And you will be able to run the commands directly after installing them.
```bash
#Examples Below:

drone-image-query "a futuristic drone flying over a city"
drone-describe-image path/to/drone_image.jpg
drone-audio-detect path/to/recording.wav --low 100 --high 700 --threshold 0.2
drone-audio-monitor --device 0 --samplerate 16000
drone-rf-detect --freq 2.4G --freq 5.8G --remote-id-freq 2.433G
drone-rtl-power-detect ...
drone-wifi-remote-id wlan0
drone-rtl-power-visualize rtl_power_data.csv -o spectrum_plot.png
```

## Detection Parameters

- **Audio Detection**: Focuses on 100-700Hz frequency band typical of drone motor/rotor sounds
- **RF Detection**: Monitors common drone control frequencies (2.4GHz, 5.8GHz) and remote ID beacons
- **WiFi Remote ID**: Captures ASTM F3411 compliant broadcasts containing drone identification, location, and operator data
- **Thresholds**: Adjustable sensitivity levels for each detection method

Use `--help` with any script to see all available options and parameters.
