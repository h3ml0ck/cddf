"""Utility to detect drone sounds in audio files."""

import argparse
import sys
from typing import Tuple

import numpy as np
import soundfile as sf


def detect_drone_sound(
    audio_path: str,
    freq_range: Tuple[float, float] = (100.0, 700.0),
    threshold: float = 0.2,
) -> bool:
    """Detect whether an audio file contains a drone-like sound.

    The function performs a simple frequency analysis and checks if the
    proportion of energy within ``freq_range`` exceeds ``threshold``.

    Args:
        audio_path: Path to the audio file (any format supported by soundfile).
        freq_range: Tuple of ``(low_freq, high_freq)`` for the expected drone band.
        threshold: Ratio of band energy to total energy required for detection.

    Returns:
        ``True`` if a drone sound is detected, ``False`` otherwise.
    """
    data, samplerate = sf.read(audio_path)
    if data.ndim > 1:
        data = data.mean(axis=1)

    spectrum = np.abs(np.fft.rfft(data))
    freqs = np.fft.rfftfreq(len(data), 1.0 / samplerate)

    total_energy = np.sum(spectrum ** 2)
    if total_energy == 0:
        return False

    low, high = freq_range
    band_mask = (freqs >= low) & (freqs <= high)
    band_energy = np.sum(spectrum[band_mask] ** 2)

    return (band_energy / total_energy) >= threshold


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    parser = argparse.ArgumentParser(description="Detect drone sounds in audio files.")
    parser.add_argument("audio_path", help="Path to the audio file")
    parser.add_argument(
        "--low",
        type=float,
        default=100.0,
        help="Lower frequency bound for drone detection (Hz)",
    )
    parser.add_argument(
        "--high",
        type=float,
        default=700.0,
        help="Upper frequency bound for drone detection (Hz)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.2,
        help="Energy ratio threshold for positive detection",
    )
    args = parser.parse_args(argv)

    try:
        detected = detect_drone_sound(
            args.audio_path, (args.low, args.high), args.threshold
        )
    except Exception as exc:
        print(f"Error processing audio: {exc}", file=sys.stderr)
        return 1

    if detected:
        print("Drone sound detected")
    else:
        print("No drone sound detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
