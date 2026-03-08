# Contributing to CDDF

## Development setup

```bash
git clone https://github.com/h3ml0ck/cddf.git
cd cddf
pip install -e ".[dev]"
```

`pyproject.toml` is the single source of truth for dependencies. `requirements.txt` is just a convenience alias (`-e .`) — do not add pins there.

## Branching and pull requests

- Branch from `main` and open a PR when your change is ready for review.
- Keep PRs focused; one logical change per PR.
- Squash fixup commits before requesting review.
- PR titles should be imperative and descriptive, e.g. `Add BLE Remote ID capture module`.

## Code style

This project uses **ruff** for linting/formatting and **mypy** for type checking.

```bash
ruff check .          # lint
ruff format .         # format
mypy drone_tools      # type check
```

All three must pass cleanly before opening a PR. CI will enforce this.

New modules should follow the conventions of existing ones:

- Guard optional hardware imports in a `try/except ImportError` block and set a `FOO_AVAILABLE` flag.
- Expose a `main(argv=None) -> int` entry point registered in `[project.scripts]`.
- Use `from __future__ import annotations` for forward-reference compatibility.

## Testing

Run the full suite:

```bash
pytest -v
pytest --cov=drone_tools    # with coverage
```

### Hardware vs. mocked testing strategy

Most `drone_tools` modules depend on physical hardware (HackRF, RTL-SDR, a WiFi adapter in monitor mode, a Bluetooth adapter, or a microphone). The test suite is designed to run in a standard CI environment — **no hardware required**.

| Module | Real hardware | How tests work without it |
|--------|--------------|--------------------------|
| `drone_audio_detection` | Microphone / `.wav` file | Synthetic numpy arrays passed directly |
| `drone_audio_monitor` | Microphone (`sounddevice`) | `sounddevice` import mocked via `unittest.mock` |
| `drone_rf_detection` | HackRF One (`hackrf`) | `hackrf` import mocked; signal arrays generated in-process |
| `drone_rtl_power_detection` | RTL-SDR (`rtl_power` binary) | `subprocess.run` mocked to return fixture CSV data |
| `drone_wifi_remote_id` | Monitor-mode WiFi (`scapy`) | `scapy.all.sniff` mocked; raw beacon bytes fed directly to parser |
| `drone_ble_remote_id` | Bluetooth adapter (`bleak`) | `BleakScanner` mocked; synthetic advertisement objects fed to callback |
| `drone_description` / `image_query` | OpenAI API | `openai.OpenAI` mocked; fixture responses returned |

**Rule of thumb:**

- If a module calls out to hardware or a network API, mock it at the import boundary — never in the middle of a function.
- Use `pytest.importorskip("bleak")` / `pytest.importorskip("scapy")` only when the library itself cannot be installed in CI. Prefer mocking the library so the logic is still exercised.
- For end-to-end BLE/WiFi testing without hardware, use `drone-mock-sniffle` to generate realistic ASTM F3411 packet streams and pipe them into the capture modules.

### Adding a new module

1. Add unit tests in `tests/test_<module_name>.py`.
2. Mock hardware/API boundaries; keep tests fast and offline.
3. Add a row to the table above in this file.
4. Register the CLI entry point in `pyproject.toml` `[project.scripts]`.

## Commit messages

Use the imperative mood in the subject line (`Add`, `Fix`, `Remove`, not `Added`). Keep the subject under 72 characters. Reference related issues or PRs in the body where relevant.
