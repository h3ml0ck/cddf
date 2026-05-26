from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import openai

from drone_tools.detection_emit import add_emit_args, open_emitter
from drone_tools.drone_lora import DetectionEvent, DetectorType

# Named explicitly so an OpenAI default change can't silently swap the model.
DEFAULT_MODEL = "gpt-4o-mini"

_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

_EXTENSION_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_CLASSIFY_PROMPT = (
    "Identify the drone in this image. Respond with ONLY a JSON object with the keys "
    '"manufacturer", "model", "drone_type", and "confidence" (a number from 0 to 1). '
    "Use null for any field you cannot determine. Do not include any other text."
)


def _validate_image_path(image_path: str) -> None:
    """Raise ValueError if *image_path* is not a readable image file."""
    p = Path(image_path).resolve()
    if not p.is_file():
        raise ValueError(f"Image path is not a regular file: {image_path!r}")
    if p.suffix.lower() not in _ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError(
            f"Unsupported image extension {p.suffix!r}. Allowed: {', '.join(sorted(_ALLOWED_IMAGE_EXTENSIONS))}"
        )


def _chat_with_image(prompt: str, image_path: str, *, model: str, max_tokens: int) -> str:
    """Send a prompt + image to the OpenAI chat API and return the text reply."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise OSError("OPENAI_API_KEY environment variable not set")

    ext = Path(image_path).suffix.lower()
    mime_type = _EXTENSION_TO_MIME.get(ext, "image/jpeg")

    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")

    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                ],
            }
        ],
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content
    return content.strip() if content else ""


def describe_drone(
    image_path: str,
    prompt: str = "What type of drone is in this image?",
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 100,
) -> str:
    """Describe the type of drone in an image using the OpenAI API.

    Args:
        image_path: Path to the image file.
        prompt: Prompt to send to the model describing the task.
        model: Vision-capable chat model to use.
        max_tokens: Maximum response tokens.

    Returns:
        Text description of the drone type.
    """
    return _chat_with_image(prompt, image_path, model=model, max_tokens=max_tokens)


def _parse_classification(content: str) -> dict:
    """Parse the model's JSON reply, tolerating code fences and stray text."""
    text = content.strip()
    if text.startswith("```"):
        # Drop a leading ```/```json fence and the trailing fence.
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    result = {"manufacturer": None, "model": None, "drone_type": None, "confidence": None, "raw": content}
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return result
    if isinstance(data, dict):
        for key in ("manufacturer", "model", "drone_type", "confidence"):
            if data.get(key) not in (None, ""):
                result[key] = data[key]
    return result


def classify_drone(image_path: str, *, model: str = DEFAULT_MODEL, max_tokens: int = 200) -> dict:
    """Identify a drone in an image as structured fields.

    Returns a dict with ``manufacturer``, ``model``, ``drone_type``,
    ``confidence``, and the ``raw`` model reply. Fields the model can't
    determine are ``None``.
    """
    content = _chat_with_image(_CLASSIFY_PROMPT, image_path, model=model, max_tokens=max_tokens)
    return _parse_classification(content)


def main(argv=None):
    argv = argv or sys.argv[1:]
    parser = argparse.ArgumentParser(description="Identify the type of drone in an image via the OpenAI Vision API.")
    parser.add_argument("image_path", nargs="?", help="Path to the image file")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Vision model (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-tokens", type=int, default=100, help="Maximum response tokens")
    add_emit_args(parser)
    args = parser.parse_args(argv)

    if not args.image_path:
        print("Usage: python drone_description.py <image_path>")
        return 1

    try:
        emitter = open_emitter(args)
    except Exception as exc:
        print(f"Error: could not set up emitter: {exc}", file=sys.stderr)
        return 1

    try:
        _validate_image_path(args.image_path)
        if emitter is not None:
            # Structured path: classify, print a summary, and emit a VISION event.
            result = classify_drone(args.image_path, model=args.model)
            print(json.dumps({k: result[k] for k in ("manufacturer", "model", "drone_type", "confidence")}))
            emitter.emit(
                DetectionEvent(
                    detector=DetectorType.VISION,
                    manufacturer=result.get("manufacturer"),
                    model=result.get("model"),
                )
            )
        else:
            description = describe_drone(args.image_path, model=args.model, max_tokens=args.max_tokens)
            print(description)
    except Exception as exc:
        print(f"Error describing drone: {exc}", file=sys.stderr)
        return 1
    finally:
        if emitter is not None:
            emitter.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
