# CLAUDE.md

This repository contains the current Steam Quick Export application for Windows. It discovers Steam recordings, previews selected recordings, and exports verified MP4 files with FFmpeg stream copy (`-c copy`).

The repository has one supported UI: `steam_quick_export.py` → `steam_exporter/simple_ui.py`. Do not add references to or revive the retired manual exporter UI; it lived on the `main-old` branch and is not part of this application.

## Commands

Use `uv` for all Python commands; do not use `pip`.

```powershell
uv run python .\steam_quick_export.py
uv run --group test coverage run -m unittest discover -s tests -v
uv run --group test coverage report --fail-under=80
.\scripts\get-ffmpeg.ps1
.\build-quick.ps1
```

The app needs `ffmpeg.exe` and preferably `ffprobe.exe` beside the executable, on `PATH`, or through `FFMPEG_PATH`. `scripts\get-ffmpeg.ps1` downloads the pinned, SHA-256-verified FFmpeg into `dist\`, and `build-quick.ps1` embeds those binaries; both CI and release workflows share the same `.github/actions/build-app` composite action.

## Architecture

- `steam_exporter/library.py` scans Steam libraries and caches recording metadata.
- `steam_exporter/taskqueue.py` is the testable FIFO export queue: one export runs at a time, recordings stay locked while queued/running, and the GUI renders its state (badges, locked rows, queue strip).
- `steam_exporter/simple_ui.py` is the current GUI. Scans and previews run in Qt jobs; export work is delegated to `ExportClient`.
- `steam_exporter/export_client.py` starts export in a spawned process and communicates over a pipe, keeping the GUI responsive and allowing cancellation.
- `steam_exporter/export_backend.py` is the Qt-free subprocess entry point.
- `scripts/export_game.py` is the single export pipeline shared by the GUI and the batch script: it probes sources, remuxes with FFmpeg, splits files at the strict decimal 64 GB cap when necessary, verifies duration and streams, writes `verification.json`, and exposes `process_recording`/`publish`/`discard_staging` for reuse.
- `steam_exporter/media.py` provides FFmpeg discovery, Steam library roots and game-name resolution, previews, and shared media helpers (`safe_name`, `recording_timestamp`, `unique_path`, `format_bytes`, `ConversionError`).
- `steam_exporter/i18n.py` holds the zh-cn/English UI strings; every user-visible string (GUI and pipeline messages) goes through `tr()`, and both locales must define the same keys. `steam_exporter/settings.py` persists language/folders/window state to `%LOCALAPPDATA%\SteamQuickExport\settings.json` — JSON rather than QSettings so the Qt-free export backend can read the language.

Source `.m4s` recordings are never deleted by the app. The separate `scripts/export_library_and_prune.py` command is destructive and requires the explicit `--delete-sources` flag; it reuses the `export_game.py` pipeline one recording at a time and treats changes as high risk.

Coverage focuses on testable logic; Qt and subprocess wiring are checked separately by `scripts/check_export_ipc.py`. Use `subprocess.CREATE_NO_WINDOW` for FFmpeg calls, sanitize paths with `safe_name()`, and use `steam://open/screenshots` for the recordings manager.

Enable the pre-commit checks per clone:

```powershell
git config core.hooksPath .githooks
```
