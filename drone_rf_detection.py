"""Utility to detect drone RF signals without remote ID using a HackRF One."""

import argparse
import logging
import sys
from typing import Iterable, List, Optional

import numpy as np

try:
    from hackrf import HackRf
except ImportError:  # Library may not be installed during tests
    HackRf = None  


# -----------------------------
# CLI/UX helpers
# -----------------------------
def parse_hz(value: str) -> float:
    """
    Parse human-friendly frequency/sample-rate like '2.4G', '915M', '500k', '20e6'.
    Returns float Hertz.
    """
    s = value.strip().replace("_", "").lower()
    mult = 1.0
    if s.endswith("ghz") or s.endswith("g"):
        mult = 1e9
        s = s[:-3] if s.endswith("ghz") else s[:-1]
    elif s.endswith("mhz") or s.endswith("m"):
        mult = 1e6
        s = s[:-3] if s.endswith("mhz") else s[:-1]
    elif s.endswith("khz") or s.endswith("k"):
        mult = 1e3
        s = s[:-3] if s.endswith("khz") else s[:-1]
    # allow plain 'hz' suffix
    elif s.endswith("hz"):
        s = s[:-2]
    try:
        return float(s) * mult
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid frequency/rate: {value!r}")


def within_hackrf_limits(freq_hz: float) -> bool:
    # Typical HackRF receive range ~ 1 MHz to 6 GHz (depends on hardware/filters)
    return 1e6 <= freq_hz <= 6e9


def within_rate_limits(rate_hz: float) -> bool:
    # Common stable rates for HackRF are roughly 2e6 .. 20e6
    return 2e6 <= rate_hz <= 20e6


# -----------------------------
# Measurement
# -----------------------------
def _measure_power(
    device: "HackRf",
    center_freq: float,
    sample_rate: float,
    duration: float,
    settle_time: float = 0.005,  # ~5 ms default for PLL/AGC settling
) -> float:
    """Measure average power at ``center_freq`` using ``device``.

    Args:
        device: An opened :class:`HackRf` instance.
        center_freq: Frequency in Hz to tune the receiver.
        sample_rate: Sample rate in samples/second.
        duration: Capture duration in seconds.
        settle_time: Time to discard after tuning (seconds).

    Returns:
        Power in dBFS of the captured samples.
    """
    # - Only retune frequency here
    device.set_freq(center_freq)

    # Discard a short settling window after tuning
    settle_samples = int(sample_rate * max(0.0, settle_time))
    if settle_samples > 0:
        try:
            _ = device.read_samples(settle_samples)
        except Exception as e:  # Depends on hardware
            logging.debug("Settle discard failed: %s", e)

    num_samples = int(sample_rate * duration)
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
    lna_gain: Optional[int] = 32,
    vga_gain: Optional[int] = 20,
    settle_time: float = 0.005,
) -> bool:
    """Scan ``freqs`` and report drone-like activity lacking remote ID beacons."""
    if HackRf is None:
        raise RuntimeError("pyhackrf is not installed or HackRF device not available")

    # Basic input validation
    freqs = list(freqs)
    remote_id_freqs = list(remote_id_freqs)

    if not freqs:
        raise ValueError("No scan frequencies provided (--freq).")
    if not remote_id_freqs:
        raise ValueError("No remote ID frequencies provided (--remote-id-freq).")
    if not within_rate_limits(sample_rate):
        raise ValueError(f"Sample rate out of range for HackRF: {sample_rate} Hz.")
    for f in (*freqs, *remote_id_freqs):
        if not within_hackrf_limits(f):
            raise ValueError(f"Frequency {f} Hz out of HackRF range.")

    total_sweep_time = duration * (len(freqs) + len(remote_id_freqs))
    if total_sweep_time > 30 and logging.getLogger().isEnabledFor(logging.WARNING):
        logging.warning(
            "Sweep may take ~%.1f s (freqs=%d, rid=%d, duration=%.3fs each).",
            total_sweep_time, len(freqs), len(remote_id_freqs), duration
        )

    with HackRf() as device:
        # Set rate & gains once
        device.set_sample_rate(sample_rate)
        if lna_gain is not None:
            device.set_lna_gain(int(lna_gain))
        if vga_gain is not None:
            device.set_vga_gain(int(vga_gain))

        # Measure RID baseline first (max)
        rid_power = max(
            _measure_power(device, f, sample_rate, duration, settle_time=settle_time)
            for f in remote_id_freqs
        )

        for f in freqs:
            power = _measure_power(device, f, sample_rate, duration, settle_time=settle_time)
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

    # CLI/UX improvements
    parser.add_argument(
        "--freq",
        action="append",
        type=parse_hz,
        dest="freqs",
        help="Center frequency to scan (e.g., 2.4G, 915M). Can be provided multiple times.",
    )
    parser.add_argument(
        "--remote-id-freq",
        action="append",
        type=parse_hz,
        dest="rid_freqs",
        help="Remote ID beacon frequency (e.g., 2.433G). Can be provided multiple times.",
    )
    parser.add_argument("--threshold", type=float, default=-40.0, help="Power threshold in dBFS")
    parser.add_argument("--sample-rate", type=parse_hz, default=20e6, help="Sample rate (e.g., 20M)")
    parser.add_argument("--duration", type=float, default=0.1, help="Capture time in seconds")
    parser.add_argument("--settle-time", type=float, default=0.005, help="Post-tune discard seconds")
    parser.add_argument("--lna-gain", type=int, default=32, help="LNA gain (dB)")
    parser.add_argument("--vga-gain", type=int, default=20, help="VGA gain (dB)")

    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Attempt to open and print basic HackRF device info, then exit.",
    )

    # Verbosity controls
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode (errors only)")

    args = parser.parse_args(argv)

    # Configure logging per CLI/UX
    if args.quiet:
        level = logging.ERROR
    else:
        level = logging.WARNING if args.verbose == 0 else (logging.INFO if args.verbose == 1 else logging.DEBUG)
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    # --list-devices (best-effort; pyhackrf may not expose multiple devices list)
    if args.list_devices:
        if HackRf is None:
            print("HackRF library not available.", file=sys.stderr)
            return 1
        try:
            with HackRf() as dev:
                # Print minimal info available
                print("HackRF device opened successfully.")
                print(f"Default sample rate may vary; requested via --sample-rate.")
                print("Tip: ensure udev/driver permissions are configured.")
            return 0
        except Exception as e:  # Hardware dependent
            print(f"Failed to open HackRF device: {e}", file=sys.stderr)
            return 1

    # Defaults if not provided
    freqs = args.freqs or [2.4e9, 5.8e9]
    rid_freqs = args.rid_freqs or [2.433e9]

    try:
        found = detect_drone_without_remote_id(
            freqs=freqs,
            remote_id_freqs=rid_freqs,
            threshold_dbfs=args.threshold,
            sample_rate=float(args.sample_rate),
            duration=args.duration,
            lna_gain=args.lna_gain,
            vga_gain=args.vga_gain,
            settle_time=args.settle_time,
        )
    except Exception as exc:  # Depends on hardware
        print(f"Error during detection: {exc}", file=sys.stderr)
        return 1

    if found:
        print("Drone without remote ID detected")
    else:
        print("No drone without remote ID detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
