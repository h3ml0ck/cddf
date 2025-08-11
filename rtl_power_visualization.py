"""Plot rtl_power CSV output as a heatmap.

This utility reads the CSV-formatted output produced by ``rtl_power`` and
creates a frequency vs. capture index heatmap.  Each row in the input file
represents one capture from ``rtl_power`` and contains metadata followed by a
list of power measurements.  These measurements are converted to a 2D array and
visualized using ``matplotlib``.

Example usage::

    python rtl_power_visualization.py rtl_power.csv -o output.png

If ``--output``/``-o`` is not supplied the plot is shown in an interactive
window.
"""

from __future__ import annotations

import argparse
from typing import List, Tuple

import numpy as np
import matplotlib.pyplot as plt


def read_rtl_power_csv(path: str) -> Tuple[np.ndarray, List[str], np.ndarray]:
    """Parse ``rtl_power`` CSV output.

    Args:
        path: Path to a file containing the output of ``rtl_power``.

    Returns:
        Tuple of (frequencies, time strings, power matrix).
    """
    times: List[str] = []
    powers: List[List[float]] = []
    freqs: np.ndarray | None = None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(",")
                if len(parts) < 7:
                    continue
                date, tstamp = parts[0], parts[1]
                start_freq = float(parts[2])
                step_hz = float(parts[4])
                db_vals: List[float] = []
                for val in parts[6:]:
                    try:
                        db_vals.append(float(val))
                    except ValueError:
                        db_vals.append(float("nan"))
                if freqs is None:
                    freqs = start_freq + step_hz * np.arange(len(db_vals))
                powers.append(db_vals)
                times.append(f"{date} {tstamp}")
    except (IOError, OSError) as exc:
        raise RuntimeError(f"Failed to read file {path}: {exc}") from exc
    
    if freqs is None:
        return np.array([]), [], np.array([])
    return freqs, times, np.array(powers)


def plot_heatmap(
    freqs: np.ndarray, times: List[str], power: np.ndarray, output: str | None
) -> None:
    """Create a heatmap from ``rtl_power`` data."""
    plt.figure(figsize=(10, 4))
    extent = [freqs[0], freqs[-1], len(times), 0]
    plt.imshow(power, aspect="auto", extent=extent, cmap="viridis")
    plt.colorbar(label="Power (dB)")
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Capture index")
    if output:
        plt.savefig(output, bbox_inches="tight")
    else:
        plt.show()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plot rtl_power output as a heatmap"
    )
    parser.add_argument("file", help="rtl_power output file to visualize")
    parser.add_argument(
        "-o", "--output", help="Path to save the plot (default: display it)"
    )
    args = parser.parse_args(argv)
    freqs, times, power = read_rtl_power_csv(args.file)
    if freqs.size == 0:
        print("No rtl_power data found", flush=True)
        return 1
    plot_heatmap(freqs, times, power, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
