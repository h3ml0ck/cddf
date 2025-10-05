import math
import numpy as np
import pytest
from types import SimpleNamespace

# Import after we prepare monkeypatches in each test
import drone_tools.drone_audio_detection as audio_detection


SR = 8000
DUR = 1.0
BAND = (100.0, 700.0)
IN_BAND_FREQ = 300.0
OUT_BAND_FREQ = 1500.0


def _sine(freq, sr=SR, dur=DUR, amp=0.9):
    t = np.arange(int(sr * dur)) / sr
    return (amp * np.sin(2 * math.pi * freq * t)).astype(np.float32)


class FakeSoundFileModule:
    """
    Minimal in-memory stub for soundfile used by audio_detection:
      - info(path) -> object with samplerate, frames
      - SoundFile(path, mode) -> ctx manager yielding a handle
      - blocks(handle, blocksize, overlap, always_2d) -> generator of blocks
    """
    def __init__(self, registry, samplerate):
        self._registry = registry           # {path: np.ndarray or 2D array}
        self._sr = samplerate

    # ---- API used by code under test
    def info(self, path):
        data = self._registry.get(path)
        if data is None:
            return SimpleNamespace(samplerate=0, frames=0)
        frames = data.shape[0]
        return SimpleNamespace(samplerate=self._sr, frames=frames)

    class _Handle:
        def __init__(self, path):
            self.path = path
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False

    def SoundFile(self, path, mode):
        return self._Handle(path)

    def blocks(self, handle, blocksize, overlap=0, always_2d=False):
        data = self._registry[handle.path]
        # Normalize to (frames, channels)
        if data.ndim == 1:
            data2d = data.reshape(-1, 1)
        else:
            data2d = data
        hop = blocksize - (overlap or 0)
        if hop <= 0:
            hop = blocksize
        i = 0
        n = data2d.shape[0]
        while i < n:
            blk = data2d[i : i + blocksize]
            if blk.shape[0] == 0:
                break
            yield blk.astype(np.float32)
            i += hop


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """
    Provides an in-memory 'filesystem' mapping path->np.array;
    installs a fake soundfile module for the duration of the test.
    """
    reg = {}
    fake_sf = FakeSoundFileModule(registry=reg, samplerate=SR)
    # Patch the soundfile module inside the target module's namespace
    monkeypatch.setattr(audio_detection, "sf", fake_sf)
    return reg


@pytest.fixture
def in_band_file(registry, tmp_path):
    p = str(tmp_path / "in_band.wav")
    registry[p] = _sine(IN_BAND_FREQ)  # mono
    return p


@pytest.fixture
def out_band_file(registry, tmp_path):
    p = str(tmp_path / "out_band.wav")
    registry[p] = _sine(OUT_BAND_FREQ)  # mono
    return p


@pytest.fixture
def silence_file(registry, tmp_path):
    p = str(tmp_path / "silence.wav")
    registry[p] = np.zeros(int(SR * DUR), dtype=np.float32)
    return p


@pytest.fixture
def stereo_in_left_only_file(registry, tmp_path):
    p = str(tmp_path / "stereo_left_inband.wav")
    left = _sine(IN_BAND_FREQ)
    right = np.zeros_like(left)
    registry[p] = np.stack([left, right], axis=1)  # (frames, 2)
    return p


@pytest.mark.parametrize("overlap", [0.0, 0.5])
def test_detects_in_band_tone(in_band_file, overlap):
    ok = audio_detection.detect_drone_sound(
        in_band_file,
        freq_range=BAND,
        threshold=0.2,
        block_seconds=0.1,
        overlap=overlap,
    )
    assert ok is True


@pytest.mark.parametrize("overlap", [0.0, 0.5])
def test_rejects_out_of_band_tone(out_band_file, overlap):
    ok = audio_detection.detect_drone_sound(
        out_band_file,
        freq_range=BAND,
        threshold=0.2,
        block_seconds=0.1,
        overlap=overlap,
    )
    assert ok is False


def test_silence_returns_false(silence_file):
    ok = audio_detection.detect_drone_sound(
        silence_file,
        freq_range=BAND,
        threshold=0.2,
        block_seconds=0.1,
        overlap=0.0,
    )
    assert ok is False


def test_stereo_mono_averaging_detects(stereo_in_left_only_file):
    ok = audio_detection.detect_drone_sound(
        stereo_in_left_only_file,
        freq_range=BAND,
        threshold=0.2,
        block_seconds=0.1,
        overlap=0.5,
    )
    assert ok is True


def test_invalid_overlap_raises(in_band_file):
    with pytest.raises(ValueError, match="overlap must be in \\[0.0, 1.0\\)"):
        audio_detection.detect_drone_sound(
            in_band_file,
            freq_range=BAND,
            threshold=0.2,
            block_seconds=0.1,
            overlap=1.0,
        )


def test_invalid_freq_range_high_over_nyquist_raises(in_band_file, monkeypatch):
    # Patch sf.info to report a lower samplerate so Nyquist is small
    fake_info = SimpleNamespace(samplerate=1000, frames=SR)  # Nyquist=500
    orig_info = audio_detection.sf.info

    def info_patch(path):
        return fake_info

    monkeypatch.setattr(audio_detection.sf, "info", info_patch)
    with pytest.raises(ValueError, match="Invalid freq_range"):
        audio_detection.detect_drone_sound(
            in_band_file,
            freq_range=(100.0, 700.0),  # > Nyquist (500)
            threshold=0.2,
            block_seconds=0.1,
            overlap=0.0,
        )
    # restore (pytest will undo monkeypatch at test end)


def test_main_detects_in_band_prints_and_returns_zero(in_band_file, capsys):
    argv = [in_band_file, "--low", "100", "--high", "700", "--threshold", "0.2"]
    ret = audio_detection.main(argv)
    captured = capsys.readouterr()
    assert ret == 0
    assert "Drone sound detected" in captured.out


def test_main_no_detect_prints_and_returns_zero(out_band_file, capsys):
    ret = audio_detection.main([out_band_file, "--low", "100", "--high", "700", "--threshold", "0.2"])
    captured = capsys.readouterr()
    assert ret == 0
    assert "No drone sound detected" in captured.out


def test_main_error_nonexistent_file_returns_one(capsys, monkeypatch):
    # Make sf.info throw an OSError to simulate missing file
    def err(_):
        raise OSError("missing")
    monkeypatch.setattr(audio_detection.sf, "info", err)

    ret = audio_detection.main(["/no/such/file.wav"])
    captured = capsys.readouterr()
    assert ret == 1
    assert "Error processing audio:" in captured.err


def test_streaming_blocks_multiple_chunks(in_band_file):
    ok = audio_detection.detect_drone_sound(
        in_band_file,
        freq_range=BAND,
        threshold=0.2,
        block_seconds=0.02,  # more chunks
        overlap=0.25,
    )
    assert ok is True
