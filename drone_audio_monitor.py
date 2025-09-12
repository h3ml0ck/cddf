"""Continuous monitoring for drone sounds using a microphone.

This script listens to an audio input device (e.g., a ReSpeaker microphone
array on a Raspberry Pi) and reports when a drone-like sound is detected in
real time. Detection is based on a simple frequency energy ratio, similar to
``drone_audio_detection.py`` but applied to live audio chunks.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Tuple

import numpy as np
import sounddevice as sd

try:
    # Optional speed-up
    import scipy.fft as sfft
except Exception:  # optional dependency
    sfft = None


def _nearest_pow2(n: int) -> int:
    if n <= 1:
        return 1
    return 1 << (int(round(np.log2(n))))


def _detect_drone_block(
    block: np.ndarray,
    threshold: float,
    freqs: np.ndarray,
    band_mask: np.ndarray,
    use_scipy_workers: bool,
) -> bool:
    """Return True if the audio ``block`` contains a drone-like sound.

    Performance-oriented: reuses precomputed `freqs` and `band_mask`;
    optionally uses SciPy FFT with thread workers if available.
    """
    # Ensure 1-D mono view without allocating unnecessarily
    if block.ndim > 1:
        block = block[:, 0]

    # FFT
    if sfft is not None:
        spec = sfft.rfft(block, workers=(0 if not use_scipy_workers else None), overwrite_x=False)
    else:
        spec = np.fft.rfft(block)

    # Energy computations
    # spectrum magnitude squared = |spec|^2
    power = (spec.real * spec.real) + (spec.imag * spec.imag)

    total_energy = np.sum(power)
    if total_energy <= 1e-12:
        return False

    band_energy = np.sum(power[band_mask])
    return (band_energy / total_energy) >= threshold


def monitor_audio(
    device: str | int | None,
    samplerate: int,
    block_duration: float,
    freq_range: Tuple[float, float],
    threshold: float,
    channels: int,
    latency: float | None,
    blocksize_cli: int | None,
    min_interval: float,
) -> None:
    """Continuously monitor the selected device for drone sounds."""

    # Determine blocksize: CLI override > derived from duration; nudge to power-of-two for FFT perf
    if blocksize_cli and blocksize_cli > 0:
        blocksize = blocksize_cli
    else:
        blocksize = int(block_duration * samplerate)
        blocksize = _nearest_pow2(max(1, blocksize))

    # Precompute frequency vector and mask once per stream configuration
    freqs = np.fft.rfftfreq(blocksize, 1.0 / samplerate)
    low, high = freq_range
    # clamp within valid range, but keep behavior simple (no validation changes beyond CLI/UX scope)
    nyquist = samplerate / 2.0
    low_c = max(0.0, min(low, nyquist))
    high_c = max(0.0, min(high, nyquist))
    band_mask = (freqs >= low_c) & (freqs <= high_c)

    last_print_ts = 0.0

    def callback(indata, frames, time_info, status):  # noqa: ANN001 - sounddevice signature
        nonlocal last_print_ts
        if status:
            print(status, file=sys.stderr)

        if _detect_drone_block(
            indata,  # pass full frame; function uses first channel view without copying
            threshold=threshold,
            freqs=freqs,
            band_mask=band_mask,
            use_scipy_workers=True,
        ):
            now = time.time()
            if (now - last_print_ts) >= min_interval:
                print("Drone sound detected", flush=True)
                last_print_ts = now

    stream_kwargs = dict(
        device=device,
        channels=channels,
        callback=callback,
        samplerate=samplerate,
        blocksize=blocksize,
    )
    if latency is not None:
        stream_kwargs["latency"] = latency  # type: ignore[assignment]

    with sd.InputStream(**stream_kwargs):
        print(
            f"Listening for drone sounds (sr={samplerate} Hz, blocksize={blocksize}, "
            f"channels={channels})... Press Ctrl+C to stop."
        )
        try:
            while True:
                sd.sleep(1000)
        except KeyboardInterrupt:
            print("Stopping.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real-time drone sound monitor")
    parser.add_argument("--device", help="Input device ID or name", default=None)
    parser.add_argument("--samplerate", type=int, default=16000, help="Sampling rate")

    # CLI/UX improvements
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    parser.add_argument("--channels", type=int, default=1, help="Number of input channels")
    parser.add_argument(
        "--latency",
        type=float,
        default=None,
        help="Desired stream latency in seconds (driver may choose nearest possible)",
    )
    parser.add_argument(
        "--blocksize",
        type=int,
        default=None,
        help="Explicit block size in frames (overrides --block-duration).",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=1.0,
        help="Minimum seconds between repeated 'detected' messages (rate limit).",
    )

    parser.add_argument(
        "--block-duration",
        type=float,
        default=1.0,
        help="Length of audio blocks to analyze (seconds) (ignored if --blocksize is provided).",
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

    if args.list_devices:
        print(sd.query_devices())
        return 0

    freq_range = (args.low, args.high)
    monitor_audio(
        device=args.device,
        samplerate=args.samplerate,
        block_duration=args.block_duration,
        freq_range=freq_range,
        threshold=args.threshold,
        channels=args.channels,
        latency=args.latency,
        blocksize_cli=args.blocksize,
        min_interval=args.min_interval,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
