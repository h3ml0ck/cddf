import os
import sys
import base64
import openai


def describe_drone(image_path: str, prompt: str = "What type of drone is in this image?") -> str:
    """Describe the type of drone in an image using the OpenAI API.

    Args:
        image_path: Path to the image file.
        prompt: Prompt to send to the model describing the task.

    Returns:
        Text description of the drone type.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY environment variable not set")

    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")

    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini", 
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                ],
            }
        ],
        max_tokens=100,
    )
    return response.choices[0].message.content.strip()


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print("Usage: python drone_description.py <image_path>")
        return 1
    image_path = argv[0]
    try:
        description = describe_drone(image_path)
    except Exception as exc:
        print(f"Error describing drone: {exc}", file=sys.stderr)
        return 1
    print(description)
    return 0


if __name__ == "__main__":
    sys.exit(main())
