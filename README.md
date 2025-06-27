# cddf

Citizen Drone Defense Force

This repository includes a simple script to query the OpenAI API for image
generation. The script `image_query.py` sends a prompt to the API and prints
URLs for generated images.

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
