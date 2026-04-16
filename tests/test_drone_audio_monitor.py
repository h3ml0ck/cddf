import math

import numpy as np
import pytest

# Import the module under test (new structure)
import drone_tools.drone_audio_monitor as mon

# ---------- helpers ----------


def _ensure_sd(monkeypatch):
    """
    Ensure mon.sd is a stub with InputStream, sleep, and query_devices.
    Works whether the real module failed to import (mon.sd is None)
    or it imported a stub already.
    """
    if getattr(mon, "sd", None) is not None:
        return  # already present (real or stub)

    class _SDStub:
        class InputStream:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        @staticmethod
        def sleep(ms):
            pass

        @staticmethod
        def query_devices():
            return "FAKE_DEVICES"

    monkeypatch.setattr(mon, "sd", _SDStub())


def _sine_block(freq, sr, nframes, amp=0.9, channels=1, dtype=np.float32):
    t = np.arange(nframes, dtype=np.float64) / float(sr)
    mono = (amp * np.sin(2.0 * math.pi * freq * t)).astype(dtype)
    if channels > 1:
        return np.stack([mono] + [np.zeros_like(mono) for _ in range(channels - 1)], axis=1)
    # sounddevice callback provides (frames, channels); our code slices first channel
    return mono.reshape(-1, 1)


class _TimeSeq:
    """Return successive timestamps from a sequence."""

    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def __call__(self):
        if self.i < len(self.seq):
            v = self.seq[self.i]
            self.i += 1
            return v
        return self.seq[-1]


class MockInputStream:
    """
    Minimal mock for sounddevice.InputStream.
    Calls the provided callback a couple of times on __enter__.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.blocksize = kwargs["blocksize"]
        self.channels = kwargs["channels"]
        self.samplerate = kwargs["samplerate"]

    def __enter__(self):
        # simulate two incoming in-band blocks immediately upon opening
        indata = _sine_block(
            freq=300.0,  # in-band for defaults (100..700 Hz)
            sr=self.samplerate,
            nframes=self.blocksize,
            channels=self.channels,
        )
        self.callback(indata, self.blocksize, None, None)
        self.callback(indata, self.blocksize, None, None)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class MockInputStreamOutOfBand(MockInputStream):
    def __enter__(self):
        indata = _sine_block(
            freq=2000.0,  # out-of-band for defaults
            sr=self.samplerate,
            nframes=self.blocksize,
            channels=self.channels,
        )
        self.callback(indata, self.blocksize, None, None)
        self.callback(indata, self.blocksize, None, None)
        return self


# ---------- unit tests for helpers ----------


@pytest.mark.parametrize(
    "n,expected",
    [
        (0, 1),
        (1, 1),
        (2, 2),
        (3, 4),
        (7, 8),
        (16, 16),
        (17, 16),  # nearest (via round) -> 16
    ],
)
def test_nearest_pow2(n, expected):
    assert mon._nearest_pow2(n) == expected


def test_detect_block_numpy_fft_true_and_false(monkeypatch):
    # Force numpy FFT path (no SciPy)
    monkeypatch.setattr(mon, "sfft", None)

    sr = 16000
    n = 2048
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    low, high = 100.0, 700.0
    band_mask = (freqs >= low) & (freqs <= high)

    # In-band should detect
    block_in = _sine_block(300.0, sr, n, channels=1)[:, 0]
    assert mon._detect_drone_block(
        block=block_in,
        threshold=0.2,
        freqs=freqs,
        band_mask=band_mask,
        use_scipy_workers=True,
    )

    # Out-of-band should not detect
    block_out = _sine_block(2000.0, sr, n, channels=1)[:, 0]
    assert not mon._detect_drone_block(
        block=block_out,
        threshold=0.2,
        freqs=freqs,
        band_mask=band_mask,
        use_scipy_workers=True,
    )

    # Near-silence should not detect
    block_silence = np.zeros(n, dtype=np.float32)
    assert not mon._detect_drone_block(
        block=block_silence,
        threshold=0.2,
        freqs=freqs,
        band_mask=band_mask,
        use_scipy_workers=False,
    )


# ---------- monitor_audio loop tests (mocking sounddevice & time) ----------


def test_monitor_audio_triggers_detection_and_rate_limits(monkeypatch, capsys):
    """
    - Validates that a detection message prints.
    - Ensures rate limiting suppresses immediate repeats.
    - Ensures the loop exits via KeyboardInterrupt from sd.sleep.
    """
    _ensure_sd(monkeypatch)  # ensure mon.sd exists
    # Mock InputStream to feed in-band audio blocks
    monkeypatch.setattr(mon.sd, "InputStream", MockInputStream)

    # IMPORTANT: start time at >= 1.0 so first detection passes rate-limit from last_print_ts=0.0
    # Second callback at +0.1s gets suppressed; third time value is for any later checks.
    tseq = _TimeSeq([1.0, 1.1, 3.0])
    monkeypatch.setattr(mon.time, "time", tseq)

    # Raise KeyboardInterrupt on first sleep to exit the while loop
    def fake_sleep(ms):
        raise KeyboardInterrupt

    monkeypatch.setattr(mon.sd, "sleep", fake_sleep)

    # Run monitor
    mon.monitor_audio(
        device=None,
        samplerate=16000,
        block_duration=0.1,
        freq_range=(100.0, 700.0),
        threshold=0.2,
        channels=1,
        latency=None,
        blocksize_cli=None,
        min_interval=1.0,
    )

    out = capsys.readouterr().out
    assert "Listening for drone sounds" in out
    # Should only appear once due to rate limiting
    assert out.count("Drone sound detected") == 1
    assert "Stopping." in out


def test_monitor_audio_no_detection(monkeypatch, capsys):
    """
    Out-of-band audio should not print 'Drone sound detected'.
    """
    _ensure_sd(monkeypatch)  # ensure mon.sd exists
    monkeypatch.setattr(mon.sd, "InputStream", MockInputStreamOutOfBand)

    def fake_sleep(ms):
        raise KeyboardInterrupt

    monkeypatch.setattr(mon.sd, "sleep", fake_sleep)

    # time is irrelevant for negative case but keep deterministic
    monkeypatch.setattr(mon.time, "time", _TimeSeq([1.0, 2.0]))

    mon.monitor_audio(
        device=None,
        samplerate=16000,
        block_duration=0.1,
        freq_range=(100.0, 700.0),
        threshold=0.2,
        channels=1,
        latency=None,
        blocksize_cli=None,
        min_interval=1.0,
    )

    out = capsys.readouterr().out
    assert "Listening for drone sounds" in out
    assert "Drone sound detected" not in out
    assert "Stopping." in out


# ---------- CLI tests ----------


def test_main_lists_devices(monkeypatch, capsys):
    _ensure_sd(monkeypatch)  # ensure mon.sd exists
    monkeypatch.setattr(mon.sd, "query_devices", lambda: "DEVICES")
    ret = mon.main(["--list-devices"])
    captured = capsys.readouterr()
    assert ret == 0
    assert "DEVICES" in captured.out


def test_main_parses_args_and_calls_monitor(monkeypatch):
    _ensure_sd(monkeypatch)  # ensure mon.sd exists
    called = {"val": False, "args": None}

    def fake_monitor(**kwargs):
        called["val"] = True
        called["args"] = kwargs
        return None

    monkeypatch.setattr(mon, "monitor_audio", fake_monitor)
    argv = [
        "--device",
        "mic0",
        "--samplerate",
        "22050",
        "--channels",
        "2",
        "--latency",
        "0.05",
        "--blocksize",
        "2048",
        "--min-interval",
        "0.5",
        "--block-duration",
        "0.2",
        "--low",
        "120",
        "--high",
        "650",
        "--threshold",
        "0.3",
    ]
    ret = mon.main(argv)
    assert ret == 0
    assert called["val"] is True
    args = called["args"]
    # spot-check a few parsed values
    assert args["device"] == "mic0"
    assert args["samplerate"] == 22050
    assert args["channels"] == 2
    assert args["latency"] == 0.05
    assert args["blocksize_cli"] == 2048
    assert args["min_interval"] == 0.5
    assert args["block_duration"] == 0.2
    assert args["freq_range"] == (120.0, 650.0)
    assert args["threshold"] == 0.3
