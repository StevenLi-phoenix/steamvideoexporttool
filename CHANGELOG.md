# Changelog

All notable changes to Steam Quick Export are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/) and the project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-09-05

### Added

- **Export task queue**: while one game is exporting, other games can be
  queued with "Queue export"; tasks run automatically one by one. Queued or
  running recordings are locked (their checkboxes are disabled) so the same
  footage cannot be triggered twice; a queued game can be removed from the
  queue via right-click, and completed rows are unchecked automatically.
- **Chinese/English UI**: a language toggle in the header switches the whole
  interface (and the export pipeline's log messages) instantly; the choice is
  auto-detected from the system locale and persisted. CLI accepts `--lang`.
- Settings persistence: recordings folder, output folder, log-pane visibility,
  and window geometry are remembered between runs
  (`%LOCALAPPDATA%\SteamQuickExport\settings.json`).

### Changed

- Export progress is now parsed from pipeline messages and shown as a real
  percentage (previously an indeterminate spinner for the whole export).
- Sizes in the recording list use adaptive units (KB/MB/GB) instead of always
  GB.

### Fixed

- Background-job errors keep the traceback (shown in the error dialog's
  details) instead of a bare one-line message.
- Cancelling an export no longer pops a warning dialog; it reports in the
  status line and log.
- "Open output folder" creates the folder when it does not exist instead of
  failing silently.
- The idle status hint follows the selected language.
- The Logs toggle reflects the pane state; the scan-progress connection is
  made before the worker starts so early messages are not lost.

## [0.2.2] - 2026-09-05

### Added

- Tests for the shared export pipeline (`scripts/export_game.py`) and for the
  destructive batch script's safety gates; `scripts/` now counts toward the
  80% coverage threshold (total 87%).
- Ruff lint/format toolchain wired into CI and the pre-commit hook; type
  annotations for `steam_exporter/library.py`.
- `scripts/get-ffmpeg.ps1`: pinned, SHA-256-verified FFmpeg download for
  reproducible local and CI builds.
- Shared `.github/actions/build-app` composite action used by CI and release.
- LICENSE (MIT) and this changelog.

### Changed

- `scripts/export_game.py` is the single export pipeline; the legacy
  `SteamExporter` preflight/convert path, `models.py`, and other dead code
  were removed. `export_library_and_prune.py` reuses the pipeline and takes
  `--source`/`--output` (default `%USERPROFILE%\Videos\Steam`).
- FFmpeg subprocesses decode output as UTF-8 explicitly (zh-CN Windows
  robustness) and preview/probe failures surface FFmpeg's stderr.
- CI: concurrency cancellation, push builds restricted to `main`, build job
  uploads the bundle as an artifact; release verifies the tag matches
  `pyproject.toml` and re-runs idempotently.

### Fixed

- VDF game-name parsing no longer corrupts Chinese names via
  `unicode_escape`.
- Preview generation: readable errors on unreadable durations, timeouts, and
  cleanup of half-written frames.
- Export filename collisions fall back to `unique_path` instead of aborting.

## [0.2.1] - 2026-09-05

### Fixed

- CI/release: downloaded FFmpeg is placed under `dist\` before `build-quick.ps1` runs.
- CI build: resolve the `uv` path before restricting `PATH`.
- Quick Export build environment (`6ff336d`).
- CI/release exit-code check for the windowed exe; dropped deprecated screenshot (`1cc964a`).

## [0.2.0] - 2026-09-05

### Added

- Responsive single-window GUI (`steam_exporter/simple_ui.py`): game list,
  per-recording checkboxes with four-frame preview, background export with
  live logs and cancellation (`58f9b2d`).
- Application icon and screenshot.

### Changed

- The previous manual-export UI moved to the `main-old` branch and is retired.

## [0.1.1] - 2026-07-25

### Fixed

- Release workflow: FFmpeg binaries are bundled correctly.

## [0.1.0] - 2026-07-25

### Added

- Initial release: lossless remux of Steam Game Recording M4S/DASH sessions
  to MP4 via FFmpeg stream copy, with automatic Steam library discovery,
  game-name resolution, previews, a 64 GB per-file cap with keyframe-safe
  splitting, and PyInstaller packaging for Windows.
