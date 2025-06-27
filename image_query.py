import os
import sys
import openai


def query_image(prompt: str, n: int = 1, size: str = "1024x1024") -> list:
    """Query the OpenAI API to generate image URLs for a prompt.

    Args:
        prompt: Text prompt describing the desired image.
        n: Number of images to generate.
        size: Image resolution, e.g. "1024x1024".

    Returns:
        A list of URLs to the generated images.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY environment variable not set")

    openai.api_key = api_key

    response = openai.Image.create(prompt=prompt, n=n, size=size)
    return [data["url"] for data in response["data"]]


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print("Usage: python image_query.py <prompt>")
        return 1
    prompt = " ".join(argv)
    try:
        urls = query_image(prompt)
    except Exception as exc:
        print(f"Error querying image: {exc}", file=sys.stderr)
        return 1
    for url in urls:
        print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
