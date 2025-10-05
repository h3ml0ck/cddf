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
    block_seconds: float = 2.0, #Increase block_seconds (e.g., 3–5 s) for smoother spectra; decrease for faster responsiveness.
    overlap: float = 0.5, #Set overlap=0.0 for speed, 0.5 for better frequency stability.
) -> bool:
    """Detect whether an audio file contains a drone-like sound.

    Streams audio in blocks to avoid loading entire files into memory.
    Accumulates band energy vs total energy across blocks.

    Args:
        audio_path: Path to the audio file (any format supported by soundfile).
        freq_range: Tuple of ``(low_freq, high_freq)`` for the expected drone band.
        threshold: Ratio of band energy to total energy required for detection.
        block_seconds: Approximate block length in seconds for FFT analysis
        overlap: Fractional overlap between consecutive blocks (0..<1).

    Returns:
        ``True`` if a drone sound is detected, ``False`` otherwise.
    """
    if not (0.0 <= overlap < 1.0):
        raise ValueError("overlap must be in [0.0, 1.0).")

    # Peek at file info (no load)
    info = sf.info(audio_path)
    sr = info.samplerate
    if sr <= 0 or info.frames == 0:
        return False

    low, high = freq_range
    if low <= 0 or high <= low or high >= sr / 2:
        raise ValueError("Invalid freq_range for this file's samplerate.")

    # Choose block size (in input samplerate frames)
    blocksize = max(1024, int(block_seconds * sr))
    # Convert fractional overlap to frames
    hop_overlap = int(blocksize * overlap) if overlap > 0 else 0

    total_energy = 0.0
    band_energy = 0.0

    # Streaming read
    with sf.SoundFile(audio_path, "r") as f:
        for block in sf.blocks(
            f, blocksize=blocksize, overlap=hop_overlap, always_2d=True
        ):
            # block shape: (frames, channels)
            x = block.astype(np.float32)
            if x.size == 0:
                continue
            # mono
            if x.ndim == 2 and x.shape[1] > 1:
                x = x.mean(axis=1)
            else:
                x = x.reshape(-1)

            if len(x) < 2:
                continue

            # Remove DC (helps with leakage)
            x = x - np.median(x)

            # Window to cut spectral leakage
            win = np.hanning(len(x))
            xw = x * win

            # FFT of this block
            S = np.fft.rfft(xw)
            mag2 = (np.abs(S) ** 2)

            # Convert to (approx) energy density normalization (optional)
            # We only need relative energies, so a consistent scale is fine.
            freqs = np.fft.rfftfreq(len(xw), d=1.0 / sr)

            # Accumulate energies
            total_energy += float(np.sum(mag2))
            band_mask = (freqs >= low) & (freqs <= high)
            if np.any(band_mask):
                band_energy += float(np.sum(mag2[band_mask]))

    if total_energy == 0.0:
        return False

    ratio = band_energy / total_energy
    return ratio >= threshold


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
