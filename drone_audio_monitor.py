"""Continuous monitoring for drone sounds using a microphone.

This script listens to an audio input device (e.g., a ReSpeaker microphone
array on a Raspberry Pi) and reports when a drone-like sound is detected in
real time. Detection is based on a simple frequency energy ratio, similar to
``drone_audio_detection.py`` but applied to live audio chunks.
"""

from __future__ import annotations

import argparse
import sys
from typing import Tuple

import numpy as np
import sounddevice as sd


# Default values for detection
def _detect_drone_block(
    block: np.ndarray,
    samplerate: int,
    freq_range: Tuple[float, float],
    threshold: float,
) -> bool:
    """Return True if the audio ``block`` contains a drone-like sound."""
    if block.ndim > 1:
        block = block.mean(axis=1)

    spectrum = np.abs(np.fft.rfft(block))
    freqs = np.fft.rfftfreq(len(block), 1.0 / samplerate)

    total_energy = np.sum(spectrum ** 2)
    if total_energy == 0:
        return False

    low, high = freq_range
    band_mask = (freqs >= low) & (freqs <= high)
    band_energy = np.sum(spectrum[band_mask] ** 2)
    return (band_energy / total_energy) >= threshold


def monitor_audio(
    device: str | int | None,
    samplerate: int,
    block_duration: float,
    freq_range: Tuple[float, float],
    threshold: float,
) -> None:
    """Continuously monitor the selected device for drone sounds."""

    blocksize = int(block_duration * samplerate)

    def callback(indata, frames, time, status):  # noqa: ANN001 - sounddevice signature
        if status:
            print(status, file=sys.stderr)
        if _detect_drone_block(indata[:, 0], samplerate, freq_range, threshold):
            print("Drone sound detected", flush=True)

    with sd.InputStream(
        device=device,
        channels=1,
        callback=callback,
        samplerate=samplerate,
        blocksize=blocksize,
    ):
        print("Listening for drone sounds... Press Ctrl+C to stop.")
        try:
            while True:
                sd.sleep(1000)
        except KeyboardInterrupt:
            print("Stopping.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real-time drone sound monitor")
    parser.add_argument("--device", help="Input device ID or name", default=None)
    parser.add_argument("--samplerate", type=int, default=16000, help="Sampling rate")
    parser.add_argument(
        "--block-duration",
        type=float,
        default=1.0,
        help="Length of audio blocks to analyze (seconds)",
    )
    parser.add_argument("--low", type=float, default=100.0, help="Lower freq bound (Hz)")
    parser.add_argument("--high", type=float, default=700.0, help="Upper freq bound (Hz)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.2,
        help="Energy ratio threshold for positive detection",
    )
    args = parser.parse_args(argv)

    freq_range = (args.low, args.high)
    monitor_audio(
        device=args.device,
        samplerate=args.samplerate,
        block_duration=args.block_duration,
        freq_range=freq_range,
        threshold=args.threshold,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
