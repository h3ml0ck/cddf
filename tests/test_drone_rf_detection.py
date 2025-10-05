import argparse
import math
import types
import numpy as np
import pytest

import drone_tools.drone_rf_detection as rf


# ---------------------------
# parse/limit helpers
# ---------------------------

@pytest.mark.parametrize(
    "s,expected",
    [
        ("2.4G", 2.4e9),
        ("2.4gHz", 2.4e9),
        ("915M", 915e6),
        ("915mhz", 915e6),
        ("500k", 500e3),
        ("500KHz", 500e3),
        ("123", 123.0),
        ("20e6", 20e6),
        ("1_000K", 1_000_000.0),
    ],
)
def test_parse_hz_valid(s, expected):
    assert rf.parse_hz(s) == pytest.approx(expected)


@pytest.mark.parametrize("s", ["", "abc", "12x", "1..0M"])
def test_parse_hz_invalid_raises(s):
    with pytest.raises(argparse.ArgumentTypeError):
        rf.parse_hz(s)


@pytest.mark.parametrize(
    "f,ok",
    [(1e5, False), (1e6, True), (6e9, True), (6.1e9, False)],
)
def test_within_hackrf_limits(f, ok):
    assert rf.within_hackrf_limits(f) is ok


@pytest.mark.parametrize(
    "r,ok",
    [(1e6, False), (2e6, True), (10e6, True), (20e6, True), (21e6, False)],
)
def test_within_rate_limits(r, ok):
    assert rf.within_rate_limits(r) is ok


# ---------------------------
# Mock HackRF
# ---------------------------

class MockHackRf:
    """
    Minimal context-managed mock of the HackRF API used by the module.
    - set_freq records the tuned frequency.
    - read_samples produces bytes for interleaved int8 I/Q.
    Behavior:
      * If tuned to any remote-ID frequency (in rid_set), returns near-zero power bytes.
      * Otherwise returns higher-power bytes.
    """
    def __init__(self, rid_set=None, raise_on_open=False):
        self.rid_set = set(rid_set or [])
        self.raise_on_open = raise_on_open
        self.cur_freq = None
        self.sample_rate = None
        self.lna = None
        self.vga = None
        self.settle_reads = 0
        self.measure_reads = 0

    # Context manager protocol
    def __enter__(self):
        if self.raise_on_open:
            raise RuntimeError("fail open")
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    # API used by code
    def set_sample_rate(self, rate):
        self.sample_rate = rate

    def set_lna_gain(self, g):
        self.lna = g

    def set_vga_gain(self, g):
        self.vga = g

    def set_freq(self, f):
        self.cur_freq = f

    def read_samples(self, n_samples):
        # Each "sample" is two int8 values (I then Q). The code treats the
        # buffer as int8 and then slices [::2] + 1j*[1::2]
        self._record_read(n_samples)
        if self.cur_freq in self.rid_set:
            # near-silence -> very low power
            i = np.zeros(n_samples, dtype=np.int8)
        else:
            # constant nonzero I/Q -> higher power
            i = np.full(n_samples, 10, dtype=np.int8)
        return i.tobytes()

    def _record_read(self, n_samples):
        # first reads after set_freq are settle reads (detected in tests by count)
        # tests don't need strict classification; they count total invocations.
        pass


# ---------------------------
# _measure_power tests
# ---------------------------

def test_measure_power_uses_settle_and_returns_dbfs(monkeypatch):
    # Create a mock where rid_set empty; tuned freq not in rid set => high power
    mock = MockHackRf(rid_set=[])
    # Monkeypatch rf.HackRf to return our mock when used as context
    monkeypatch.setattr(rf, "HackRf", lambda: mock)

    # Call internal measure function directly with positive settle_time
    # n_samples = sample_rate * duration = 2e6 * 0.01 = 20,000 (bytes length = 20,000)
    power = rf._measure_power(
        device=mock,
        center_freq=2.4e9,
        sample_rate=2e6,
        duration=0.01,
        settle_time=0.005,
    )
    # With I=Q=10 int8 -> |I+jQ|^2 = 200 mean -> 10*log10(200) ≈ 23.01 dBFS
    assert power == pytest.approx(10 * math.log10(200), rel=1e-3)


# ---------------------------
# detect_drone_without_remote_id tests
# ---------------------------

def test_detect_returns_true_when_power_high_and_no_rid(monkeypatch, capsys):
    # rid power will be very low (mock returns zeros on rid freq)
    rid_freqs = [2.433e9]
    scan_freqs = [2.4e9, 5.8e9]

    # HackRf context should be our mock with rid_set
    monkeypatch.setattr(rf, "HackRf", lambda: MockHackRf(rid_set=rid_freqs))

    found = rf.detect_drone_without_remote_id(
        freqs=scan_freqs,
        remote_id_freqs=rid_freqs,
        threshold_dbfs=-40.0,
        sample_rate=2e6,
        duration=0.002,
        settle_time=0.0,  # speed up
    )
    out = capsys.readouterr().out
    assert found is True
    assert "Possible drone signal at" in out


def test_detect_returns_false_when_below_threshold(monkeypatch, capsys):
    # Make "high power" become low: monkeypatch _measure_power to return -100 dBFS everywhere
    monkeypatch.setattr(rf, "_measure_power", lambda *a, **k: -100.0)
    # Provide a dummy HackRf so context opens
    monkeypatch.setattr(rf, "HackRf", lambda: MockHackRf(rid_set=[2.433e9]))

    found = rf.detect_drone_without_remote_id(
        freqs=[2.4e9],
        remote_id_freqs=[2.433e9],
        threshold_dbfs=-40.0,
        sample_rate=2e6,
        duration=0.001,
    )
    out = capsys.readouterr().out
    assert found is False
    assert "Possible drone signal" not in out


def test_detect_validation_errors_when_no_lib_or_bad_inputs(monkeypatch):
    # Case 1: library missing
    monkeypatch.setattr(rf, "HackRf", None)
    with pytest.raises(RuntimeError, match="pyhackrf"):
        rf.detect_drone_without_remote_id(freqs=[2.4e9], remote_id_freqs=[2.433e9])

    # Restore a dummy HackRf for the rest
    monkeypatch.setattr(rf, "HackRf", lambda: MockHackRf())

    # Case 2: no freqs
    with pytest.raises(ValueError, match="No scan frequencies"):
        rf.detect_drone_without_remote_id(freqs=[], remote_id_freqs=[2.433e9])

    # Case 3: no rid freqs
    with pytest.raises(ValueError, match="No remote ID frequencies"):
        rf.detect_drone_without_remote_id(freqs=[2.4e9], remote_id_freqs=[])

    # Case 4: bad sample rate
    with pytest.raises(ValueError, match="Sample rate out of range"):
        rf.detect_drone_without_remote_id(
            freqs=[2.4e9], remote_id_freqs=[2.433e9], sample_rate=1e6
        )

    # Case 5: frequency out of range
    with pytest.raises(ValueError, match="out of HackRF range"):
        rf.detect_drone_without_remote_id(
            freqs=[9e9], remote_id_freqs=[2.433e9], sample_rate=2e6
        )


# ---------------------------
# main() CLI tests
# ---------------------------

def test_main_list_devices_when_library_missing(monkeypatch, capsys):
    monkeypatch.setattr(rf, "HackRf", None)
    ret = rf.main(["--list-devices"])
    captured = capsys.readouterr()
    assert ret == 1
    assert "HackRF library not available" in captured.err or "HackRF library not available" in captured.out


def test_main_list_devices_success(monkeypatch, capsys):
    # Mock opens successfully
    monkeypatch.setattr(rf, "HackRf", lambda: MockHackRf())
    ret = rf.main(["--list-devices"])
    captured = capsys.readouterr()
    assert ret == 0
    assert "HackRF device opened successfully" in captured.out


def test_main_detection_success_true(monkeypatch, capsys):
    # Use real function but with mock HackRf that produces detection True
    rid = [2.433e9]
    monkeypatch.setattr(rf, "HackRf", lambda: MockHackRf(rid_set=rid))

    ret = rf.main([
        "--freq", "2.4G",
        "--remote-id-freq", "2.433G",
        "--threshold", "-40",
        "--sample-rate", "2M",
        "--duration", "0.001",
        "--settle-time", "0",
        "-q"
    ])
    captured = capsys.readouterr()
    assert ret == 0
    assert "Drone without remote ID detected" in captured.out


def test_main_detection_success_false(monkeypatch, capsys):
    # Force detect to return False
    monkeypatch.setattr(rf, "HackRf", lambda: MockHackRf(rid_set=[2.433e9]))
    monkeypatch.setattr(rf, "_measure_power", lambda *a, **k: -100.0)

    ret = rf.main([
        "--freq", "2.4G",
        "--remote-id-freq", "2.433G",
        "--sample-rate", "2M",
        "--duration", "0.001",
        "-q"
    ])
    captured = capsys.readouterr()
    assert ret == 0
    assert "No drone without remote ID detected" in captured.out


def test_main_detection_handles_exception(monkeypatch, capsys):
    # Make detect raise
    monkeypatch.setattr(rf, "detect_drone_without_remote_id", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    ret = rf.main(["--freq", "2.4G", "--remote-id-freq", "2.433G"])
    captured = capsys.readouterr()
    assert ret == 1
    assert "Error during detection: boom" in captured.err