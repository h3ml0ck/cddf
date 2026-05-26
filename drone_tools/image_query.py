import argparse
import os
import sys

import openai

# Named explicitly so an OpenAI default change can't silently swap the model.
DEFAULT_MODEL = "dall-e-3"


def query_image(prompt: str, n: int = 1, size: str = "1024x1024", model: str = DEFAULT_MODEL) -> list:
    """Query the OpenAI API to generate image URLs for a prompt.

    Args:
        prompt: Text prompt describing the desired image.
        n: Number of images to generate.
        size: Image resolution, e.g. "1024x1024".
        model: Image model to use (e.g. "dall-e-3", "dall-e-2").

    Returns:
        A list of URLs to the generated images.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise OSError("OPENAI_API_KEY environment variable not set")

    client = openai.OpenAI(api_key=api_key)
    response = client.images.generate(model=model, prompt=prompt, n=n, size=size)
    # response.data is Optional; the API omits it on an empty/failed result.
    return [image.url for image in (response.data or [])]


def main(argv=None):
    argv = argv or sys.argv[1:]
    parser = argparse.ArgumentParser(description="Generate drone images from a text prompt via the OpenAI API.")
    parser.add_argument("prompt", nargs="*", help="Text prompt describing the image")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Image model (default: {DEFAULT_MODEL})")
    parser.add_argument("--size", default="1024x1024", help="Image resolution, e.g. 1024x1024")
    parser.add_argument("--n", type=int, default=1, help="Number of images to generate")
    args = parser.parse_args(argv)

    if not args.prompt:
        print("Usage: drone-image-query [--model M] [--size WxH] [--n N] <prompt>")
        return 1

    prompt = " ".join(args.prompt)
    try:
        urls = query_image(prompt, n=args.n, size=args.size, model=args.model)
    except Exception as exc:
        print(f"Error querying image: {exc}", file=sys.stderr)
        return 1
    for url in urls:
        print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
