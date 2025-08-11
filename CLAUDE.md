# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the Citizen Drone Defense Force (cddf) repository, containing Python utilities for drone detection and analysis across multiple modalities: image generation/analysis (OpenAI API), audio detection, and RF signal detection.

## Key Components

### Image Processing
- **image_query.py**: Generates images from text prompts using OpenAI's image generation API. Handles both legacy and modern OpenAI API versions gracefully.
- **drone_description.py**: Analyzes drone images using OpenAI's vision models to identify drone types. Uses base64 encoding for image uploads.

### Audio Detection
- **drone_audio_detection.py**: Detects drone sounds in audio files using frequency analysis (100-700Hz band energy ratio).
- **drone_audio_monitor.py**: Real-time monitoring for drone sounds using microphone input with sounddevice. Designed for continuous monitoring on devices like ReSpeaker arrays.

### RF Signal Detection  
- **drone_rf_detection.py**: Detects drone RF signals without remote ID beacons using HackRF One hardware. Compares control channel power against remote ID beacon frequencies.
- **drone_rtl_power_detection.py**: Uses RTL-SDR dongles via `rtl_power` command to scan frequency ranges for drone RF activity.
- **rtl_power_visualization.py**: Utility for visualizing RTL-SDR spectrum data.

## Dependencies and Setup

- **Core dependencies**: numpy, soundfile, sounddevice for audio processing
- **OpenAI integration**: openai>=1.0.0 with OPENAI_API_KEY environment variable
- **RF hardware**: pyhackrf for HackRF One, external rtl_power tool for RTL-SDR
- **Visualization**: matplotlib for spectrum plotting
- **Installation**: `pip install -r requirements.txt`

## Common Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Image processing
python image_query.py "a futuristic drone flying over a city"
python drone_description.py path/to/drone_image.jpg

# Audio detection
python drone_audio_detection.py path/to/recording.wav
python drone_audio_monitor.py --device 0

# RF detection  
python drone_rf_detection.py
python drone_rtl_power_detection.py --range 2400M:2483M:1M
```

## Architecture Notes

- **Consistent error handling**: All utilities use stderr for errors and proper exit codes
- **Hardware abstraction**: RF detection scripts gracefully handle missing hardware/dependencies  
- **Frequency analysis**: Audio detection uses FFT-based energy ratio analysis in the 100-700Hz band
- **Multi-modal approach**: Combines visual, audio, and RF detection for comprehensive drone monitoring
- **Real-time capabilities**: Audio monitor supports continuous streaming analysis for live detection
- **OpenAI compatibility**: Image tools maintain backward compatibility across OpenAI API versions