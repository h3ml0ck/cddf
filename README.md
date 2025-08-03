# cddf

Citizen Drone Defense Force


This repository includes small utilities that interact with the OpenAI API.
The script `image_query.py` sends a text prompt to the API and prints URLs for
generated images. The newer script `drone_description.py` accepts an image and
returns a description of the type of drone shown.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set the `OPENAI_API_KEY` environment variable with your API key.

## Usage

Run the script with a text prompt describing the desired image:

```bash
python image_query.py "a futuristic drone flying over a city"
```

The script will output one or more URLs where you can download the generated
images.

The script automatically detects whether the newer `openai.OpenAI` client is
available and uses it when possible.

To identify the type of drone in an image run:

```bash
python drone_description.py path/to/drone_image.jpg
```

To detect drone sounds in an audio recording run:

```bash
python drone_audio_detection.py path/to/recording.wav
```

To monitor a microphone in real time (e.g., a ReSpeaker array on a Raspberry
Pi) and report when a drone-like sound is heard, run:

```bash
python drone_audio_monitor.py --device 0
```

Specify the appropriate `--device` index or name for your hardware. Use
`--help` to see additional options for tuning the detection algorithm.

To scan for potential drone RF signals that are not broadcasting a remote ID
beacon using a HackRF One, run:

```bash
python drone_rf_detection.py
```

Use `--freq` options to specify control channel frequencies to monitor and
`--remote-id-freq` to list expected remote ID beacon channels. The script will
report when strong RF activity is detected on a control channel without a
corresponding remote ID signal.
