# CLAUDE.md

This repository contains the current Steam Quick Export application for Windows. It discovers Steam recordings, previews selected recordings, and exports verified MP4 files with FFmpeg stream copy (`-c copy`).

The repository has one supported UI: `steam_quick_export.py` → `steam_exporter/simple_ui.py`. Do not add references to or revive the retired manual exporter UI; it lived on the `main-old` branch and is not part of this application.

## Commands

Use `uv` for all Python commands; do not use `pip`.

```powershell
uv run python .\steam_quick_export.py
uv run --group test coverage run -m unittest discover -s tests -v
uv run --group test coverage report --fail-under=80
.\build-quick.ps1
```

The app needs `ffmpeg.exe` and preferably `ffprobe.exe` beside the executable, on `PATH`, or through `FFMPEG_PATH`. The build script embeds binaries from `dist\ffmpeg.exe` and `dist\ffprobe.exe`.

## Architecture

- `steam_exporter/library.py` scans Steam libraries and caches recording metadata.
- `steam_exporter/simple_ui.py` is the current GUI. Scans and previews run in Qt jobs; export work is delegated to `ExportClient`.
- `steam_exporter/export_client.py` starts export in a spawned process and communicates over a pipe, keeping the GUI responsive and allowing cancellation.
- `steam_exporter/export_backend.py` is the Qt-free subprocess entry point.
- `scripts/export_game.py` probes sources, remuxes with FFmpeg, splits files at the strict decimal 64 GB cap when necessary, verifies duration and streams, and writes `verification.json`.
- `steam_exporter/media.py` provides FFmpeg discovery, Steam game-name resolution, recording discovery, previews, and shared media helpers.
- `steam_exporter/models.py` contains plain data models and conversion errors.

Source `.m4s` recordings are never deleted by the app. The separate `scripts/export_library_and_prune.py` command is destructive and requires the explicit `--delete-sources` flag; treat changes to it as high risk.

Coverage focuses on testable logic; Qt and subprocess wiring are checked separately by `scripts/check_export_ipc.py`. Use `subprocess.CREATE_NO_WINDOW` for FFmpeg calls, sanitize paths with `safe_name()`, and use `steam://open/screenshots` for the recordings manager.

Enable the pre-commit checks per clone:

```powershell
git config core.hooksPath .githooks
```
