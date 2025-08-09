"""Utility to detect drone RF signals using rtl_power (RTL-SDR)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import List


def _parse_rtl_power_output(output: str, threshold_db: float) -> bool:
    """Return True if any bin in rtl_power ``output`` exceeds ``threshold_db``.

    Args:
        output: The stdout text from an ``rtl_power`` invocation.
        threshold_db: Power threshold in dB for positive detection.

    Returns:
        ``True`` if any power bin exceeds ``threshold_db``.
    """
    for line in output.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if len(parts) < 7:
            continue
        for db_str in parts[6:]:
            try:
                if float(db_str) > threshold_db:
                    return True
            except ValueError:  # pragma: no cover - unexpected non-float
                continue
    return False


def detect_rtl_power(
    freq_range: str, threshold_db: float = -30.0, integration: float = 1.0
) -> bool:
    """Run ``rtl_power`` over ``freq_range`` and check for strong signals.

    Args:
        freq_range: Frequency specification passed to ``rtl_power`` ``-f`` option,
            e.g. ``"2400M:2483M:1M"``.
        threshold_db: Power threshold in dB for positive detection.
        integration: Integration interval in seconds passed to ``rtl_power`` ``-i``.

    Returns:
        ``True`` if a bin exceeds ``threshold_db``.
    """
    cmd = ["rtl_power", "-f", freq_range, "-i", str(integration), "-1"]
    try:
        res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except Exception as exc:  # pragma: no cover - depends on external tool
        raise RuntimeError(f"rtl_power execution failed: {exc}") from exc
    return _parse_rtl_power_output(res.stdout, threshold_db)


def main(argv: List[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="Detect drone RF signals using rtl_power and an RTL-SDR dongle"
    )
    parser.add_argument(
        "--range",
        default="2400M:2483M:1M",
        help="Frequency range for rtl_power (start:stop:bin)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=-30.0,
        help="Power threshold in dB for positive detection",
    )
    parser.add_argument(
        "--integration",
        type=float,
        default=1.0,
        help="Integration interval in seconds for rtl_power",
    )
    args = parser.parse_args(argv)

    try:
        found = detect_rtl_power(args.range, args.threshold, args.integration)
    except Exception as exc:  # pragma: no cover - depends on external tool
        print(f"Error during detection: {exc}", file=sys.stderr)
        return 1
    if found:
        print("Potential drone RF signal detected")
    else:
        print("No drone RF signal detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
