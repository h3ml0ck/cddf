"""Utility to detect drone RF signals without remote ID using a HackRF One."""

import argparse
import sys
from typing import Iterable, List

import numpy as np

try:
    from hackrf import HackRf
except Exception:  # pragma: no cover - library may not be installed during tests
    HackRf = None  # type: ignore


def _measure_power(device: "HackRf", center_freq: float, sample_rate: float, duration: float) -> float:
    """Measure average power at ``center_freq`` using ``device``.

    Args:
        device: An opened :class:`HackRf` instance.
        center_freq: Frequency in Hz to tune the receiver.
        sample_rate: Sample rate in samples/second.
        duration: Capture duration in seconds.

    Returns:
        Power in dBFS of the captured samples.
    """
    num_samples = int(sample_rate * duration)
    device.set_freq(center_freq)
    device.set_sample_rate(sample_rate)
    device.set_lna_gain(32)
    device.set_vga_gain(20)
    samples = device.read_samples(num_samples)
    # ``read_samples`` returns interleaved I/Q int8 values.
    iq = np.frombuffer(samples, dtype=np.int8).astype(np.float32)
    iq = iq[::2] + 1j * iq[1::2]
    power = 10 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-12)
    return float(power)


def detect_drone_without_remote_id(
    freqs: Iterable[float],
    remote_id_freqs: Iterable[float],
    threshold_dbfs: float = -40.0,
    sample_rate: float = 20e6,
    duration: float = 0.1,
) -> bool:
    """Scan ``freqs`` and report drone-like activity lacking remote ID beacons.

    The function measures power on ``freqs`` and compares it against the average
    power on the frequencies listed in ``remote_id_freqs``. If strong RF energy is
    detected on any drone control channel without a corresponding remote ID
    beacon, the function returns ``True``.
    """
    if HackRf is None:
        raise RuntimeError("pyhackrf is not installed or HackRF device not available")

    with HackRf() as device:  # type: ignore[misc]
        rid_power = max(
            _measure_power(device, f, sample_rate, duration) for f in remote_id_freqs
        )
        for f in freqs:
            power = _measure_power(device, f, sample_rate, duration)
            if power > threshold_dbfs and rid_power < threshold_dbfs:
                print(
                    f"Possible drone signal at {f/1e6:.1f} MHz without remote ID (power {power:.1f} dBFS)"
                )
                return True
    return False


def main(argv: List[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="Detect drone RF signals lacking remote ID using HackRF One"
    )
    parser.add_argument(
        "--freq",
        action="append",
        type=float,
        dest="freqs",
        help="Center frequency to scan in Hz (can be given multiple times)",
    )
    parser.add_argument(
        "--remote-id-freq",
        action="append",
        type=float,
        dest="rid_freqs",
        help="Expected remote ID beacon frequency in Hz (can be given multiple times)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=-40.0,
        help="Power threshold in dBFS for positive detection",
    )
    parser.add_argument("--sample-rate", type=float, default=20e6, help="Sample rate in Hz")
    parser.add_argument("--duration", type=float, default=0.1, help="Capture time in seconds")
    args = parser.parse_args(argv)

    freqs = args.freqs or [2.4e9, 5.8e9]
    rid_freqs = args.rid_freqs or [2.433e9]

    try:
        found = detect_drone_without_remote_id(
            freqs,
            rid_freqs,
            threshold_dbfs=args.threshold,
            sample_rate=args.sample_rate,
            duration=args.duration,
        )
    except Exception as exc:  # pragma: no cover - depends on hardware
        print(f"Error during detection: {exc}", file=sys.stderr)
        return 1
    if found:
        print("Drone without remote ID detected")
    else:
        print("No drone without remote ID detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
