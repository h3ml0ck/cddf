import types
import subprocess
import pytest

import drone_tools.drone_rtl_power_detection as rtl


# ---------------------------
# _parse_rtl_power_output
# ---------------------------

def test_parse_detects_bin_above_threshold():
    # Header, then a valid rtl_power CSV line: fields 0..5 are metadata, 6+ are power bins
    out = "\n".join([
        "# rtl_power output",
        "2025-10-01,12:00:00,2400000000,2483000000,1000000,10,-35,-32,-20,-40",
    ])
    assert rtl._parse_rtl_power_output(out, threshold_db=-30.0) is True  # -20 > -30


def test_parse_ignores_comments_and_short_lines_returns_false():
    out = "\n".join([
        "# comment line",
        "too,short",                           # ignored (len(parts) < 7)
        "2025,12:00,1,1,1,1",                  # still too short
        "2025,12:00,1,1,1,1, -50, -55, -60",   # all below threshold
    ])
    assert rtl._parse_rtl_power_output(out, threshold_db=-30.0) is False


def test_parse_handles_nonfloat_values_gracefully():
    out = "2025,12:00,1,1,1,1,-40,foo,-20,NaN"
    # Should return True because -20 > -30 even if "foo" raises ValueError and "NaN" is skipped
    assert rtl._parse_rtl_power_output(out, threshold_db=-30.0) is True


# ---------------------------
# detect_rtl_power (mock subprocess)
# ---------------------------

def test_detect_rtl_power_true(monkeypatch):
    def fake_run(cmd, check, capture_output, text, timeout):
        # Ensure we're calling rtl_power as expected
        assert cmd[:2] == ["rtl_power", "-f"]
        stdout = "2025,12:00,1,1,1,1,-40,-25,-50"  # -25 > -30
        return types.SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(rtl.subprocess, "run", fake_run)
    assert rtl.detect_rtl_power("2400M:2483M:1M", threshold_db=-30.0, integration=1.0) is True


def test_detect_rtl_power_false(monkeypatch):
    def fake_run(cmd, check, capture_output, text, timeout):
        stdout = "2025,12:00,1,1,1,1,-50,-45,-55"
        return types.SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(rtl.subprocess, "run", fake_run)
    assert rtl.detect_rtl_power("2400M:2483M:1M", threshold_db=-30.0, integration=2.0) is False


@pytest.mark.parametrize("exc", [
    subprocess.CalledProcessError(returncode=1, cmd=["rtl_power"]),
    subprocess.TimeoutExpired(cmd=["rtl_power"], timeout=10),
    FileNotFoundError("rtl_power not found"),
])
def test_detect_rtl_power_raises_on_errors(monkeypatch, exc):
    def fake_run(*a, **k):
        raise exc
    monkeypatch.setattr(rtl.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="rtl_power execution failed"):
        rtl.detect_rtl_power("2400M:2483M:1M")


# ---------------------------
# main() CLI
# ---------------------------

def test_main_success_true(monkeypatch, capsys):
    monkeypatch.setattr(rtl, "detect_rtl_power", lambda *a, **k: True)
    ret = rtl.main(["--range", "2400M:2483M:1M", "--threshold", "-30", "--integration", "1.0"])
    out = capsys.readouterr().out
    assert ret == 0
    assert "Potential drone RF signal detected" in out


def test_main_success_false(monkeypatch, capsys):
    monkeypatch.setattr(rtl, "detect_rtl_power", lambda *a, **k: False)
    ret = rtl.main(["--range", "2400M:2483M:1M"])
    out = capsys.readouterr().out
    assert ret == 0
    assert "No drone RF signal detected" in out


def test_main_handles_exception(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(rtl, "detect_rtl_power", boom)
    ret = rtl.main(["--range", "2400M:2483M:1M"])
    captured = capsys.readouterr()
    assert ret == 1
    assert "Error during detection: boom" in captured.err
