import os
import io
import numpy as np
import pytest

# Use a non-interactive backend before importing the module that uses pyplot so we dont need a display
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import drone_tools.rtl_power_visualization as viz


def _write_csv(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def test_read_rtl_power_csv_parses_basic_file(tmp_path):
    """
    Validates:
      - comment lines ignored
      - short lines ignored (len(parts) < 7)
      - time strings combined as 'date time'
      - frequencies computed as start + step * arange(N)
      - power matrix shape
    """
    p = tmp_path / "rtl.csv"
    lines = [
        "# comment",
        "2025-10-01,12:00:00,2400000000,2483000000,1000000,10,-30,-29,-28",
        "2025-10-01,12:00:01,2400000000,2483000000,1000000,10,-31,-30,-29",
        "bad,too,short",  # ignored
    ]
    _write_csv(p, lines)

    freqs, times, power = viz.read_rtl_power_csv(str(p))

    assert isinstance(freqs, np.ndarray)
    assert isinstance(power, np.ndarray)
    assert times == ["2025-10-01 12:00:00", "2025-10-01 12:00:01"]

    # 3 bins: start + step * arange(3)
    expected_freqs = 2400000000.0 + 1000000.0 * np.arange(3)
    np.testing.assert_allclose(freqs, expected_freqs)

    assert power.shape == (2, 3)
    np.testing.assert_allclose(power[0], np.array([-30.0, -29.0, -28.0]))
    np.testing.assert_allclose(power[1], np.array([-31.0, -30.0, -29.0]))


def test_read_rtl_power_csv_handles_nan_and_empties(tmp_path):
    """
    Non-float dB values become NaN; empty/invalid files produce empty arrays.
    """
    p = tmp_path / "rtl_nan.csv"
    lines = [
        "2025-10-01,12:00:00,100,200,10,10,-10,NA,-8,foo,-6",
    ]
    _write_csv(p, lines)
    freqs, times, power = viz.read_rtl_power_csv(str(p))

    assert len(times) == 1
    # parts[6:] contains 5 entries: -10, NA, -8, foo, -6
    assert power.shape == (1, 5)
    assert power[0][0] == -10
    assert np.isnan(power[0][1])  # "NA"
    assert power[0][2] == -8
    assert np.isnan(power[0][3])  # "foo"
    assert power[0][4] == -6

    # Empty file -> empty arrays
    p2 = tmp_path / "empty.csv"
    _write_csv(p2, [])
    freqs2, times2, power2 = viz.read_rtl_power_csv(str(p2))
    assert freqs2.size == 0 and power2.size == 0 and times2 == []


def test_read_rtl_power_csv_raises_on_io_error(tmp_path):
    with pytest.raises(RuntimeError, match="Failed to read file"):
        viz.read_rtl_power_csv(str(tmp_path / "missing.csv"))


def test_plot_heatmap_saves_file(tmp_path, monkeypatch):
    """
    When output is provided, it should save without calling plt.show().
    """
    # Create tiny, valid inputs
    freqs = np.array([100.0, 200.0, 300.0], dtype=float)
    times = ["t0", "t1"]
    power = np.array([[-10, -9, -8], [-11, -10, -9]], dtype=float)

    # Spy on plt.show and plt.savefig
    show_called = {"val": False}
    save_called = {"val": False}

    def fake_show():
        show_called["val"] = True

    def fake_savefig(path, **kwargs):
        save_called["val"] = True
        # actually write an empty file to simulate save
        with open(path, "wb") as f:
            f.write(b"")

    monkeypatch.setattr(plt, "show", fake_show)
    monkeypatch.setattr(plt, "savefig", fake_savefig)

    out = tmp_path / "out.png"
    viz.plot_heatmap(freqs, times, power, str(out))

    assert save_called["val"] is True
    assert show_called["val"] is False
    assert out.exists()


def test_plot_heatmap_shows_when_no_output(monkeypatch):
    """
    When output is None, expect plt.show() to be called.
    """
    freqs = np.array([100.0, 200.0], dtype=float)
    times = ["t0"]
    power = np.array([[-10, -9]], dtype=float)

    show_called = {"val": False}

    def fake_show():
        show_called["val"] = True

    # Avoid creating files in this test
    def fake_savefig(*args, **kwargs):
        raise AssertionError("savefig should not be called when output is None")

    monkeypatch.setattr(plt, "show", fake_show)
    monkeypatch.setattr(plt, "savefig", fake_savefig)

    viz.plot_heatmap(freqs, times, power, output=None)
    assert show_called["val"] is True


def test_main_success_writes_png(tmp_path):
    """
    End-to-end: read -> plot -> save -> return 0
    """
    csv = tmp_path / "rtl.csv"
    png = tmp_path / "plot.png"
    lines = [
        "2025-10-01,12:00:00,2400000000,2483000000,1000000,10,-30,-29,-28,-27",
        "2025-10-01,12:00:01,2400000000,2483000000,1000000,10,-31,-30,-29,-28",
    ]
    _write_csv(csv, lines)

    ret = viz.main([str(csv), "-o", str(png)])
    assert ret == 0
    assert png.exists()


def test_main_empty_file_returns_one(tmp_path, capsys):
    csv = tmp_path / "empty.csv"
    _write_csv(csv, [])
    ret = viz.main([str(csv)])
    captured = capsys.readouterr()
    assert ret == 1
    assert "No rtl_power data found" in captured.out