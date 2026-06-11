# Changelog

## [Unreleased]
### Added
- Drone reference DB: `drone-db seed` (bundled `known_drones.json` catalog), `drone-db import` (JSON/CSV), and `drone-db identify` to match a Remote ID serial to a catalog entry. New `classify()` API plus a `manufacturer_code` (CTA-2063-A) column with automatic migration of existing databases.
- Detection enrichment: detectors can attach manufacturer/model from the reference DB before publishing, enabled per node via `[emit] classify`/`classify_db`. `DetectionEvent` gained local-only `manufacturer`/`model` fields (not put on the LoRa wire).
- Vision tools: `drone-describe-image` adds `--model`, `--max-tokens`, structured `classify_drone()`, and `--emit-config` to publish a `VISION` detection; `drone-image-query` adds `--model`/`--size`/`--n` with an explicit default model. New `VISION` detector type.
- Coverage floor enforced in CI (`pytest --cov-fail-under=65`).
- CI workflow (`.github/workflows/ci.yml`) running ruff, ruff format check, mypy, and pytest on Python 3.10–3.12.
- Tool configuration in `pyproject.toml`: `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`.
- Unit tests for `drone_ble_remote_id` (16 tests) and `mock_sniffle_remote_id` (17 tests).
- `ansible/inventory.ini.example` template; real `inventory.ini` is now gitignored.
- SQLite drone reference database (`drone_tools/drone_db.py`) with `drone-db` CLI and tests.
- Post-install next-steps doc written to `~/CDDF_NEXT_STEPS.md` by the edge-node installer.
- BLE Remote ID capture module (`drone_tools/drone_ble_remote_id.py`) with `drone-ble-remote-id` CLI.
- `-o/--output` file support in `mock_sniffle_remote_id`.

### Changed
- RabbitMQ publishing consolidated into a shared `drone_tools/amqp.py` (`AmqpPublisher`, `build_amqp_url`) reused by `RabbitMQSink` and the LoRa→RabbitMQ bridge. The standalone `kismet-queuer` app keeps its own copy by design.
- `MockSniffle` arguments now use explicit `Optional` types (PEP 484).
- Whole repo reformatted with `ruff format`; unused imports removed.

### Fixed
- `dev` extra now includes `aio-pika`, so the `AmqpPublisher` tests run in CI instead of silently skipping.
- `drone_description` no longer crashes on empty Vision API responses.
- `drone_rf_detection` re-raises `argparse.ArgumentTypeError` with `from` chaining.

## [1.2.0] - 2025-09-11
### Changed
- Broad project restructure and dependency cleanup.
- Added pytest coverage for the core parsing modules (audio detection/monitor, RF detection, RTL-power detection/visualization, description).

## [1.1.0] - 2025-09-11
### Changed
- Implemented **streaming change**:
  - Prevents out-of-memory errors on long audio files
  - Improves processing speed and scalability
  - Prepares code for real-world drone detection use cases (long recordings, continuous monitoring)

## [1.0.0] - 2025-06-27
### Added
- Initial release of the project by the original author