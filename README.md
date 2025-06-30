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
