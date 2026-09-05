# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Windows-only tool that losslessly remuxes Steam Game Recording `.m4s` DASH fragments into MP4/MOV/FLV using FFmpeg stream copy (`-c copy`) — no re-encoding. The repo actually contains **two separate PySide6 GUI applications** that share a common core:

1. **Steam Video Exporter** (English UI) — entry point [steam_video_exporter.py](steam_video_exporter.py) → [steam_exporter/ui.py](steam_exporter/ui.py). Manual workflow: user points at an input folder (a single recording or a library root) and an output folder, runs preflight, picks recordings from a checklist, converts. Conversion runs in a `QThread` ([steam_exporter/worker.py](steam_exporter/worker.py)) inside the same process.
2. **Steam Quick Export / "Steam 录制"** (Chinese UI) — entry point [steam_quick_export.py](steam_quick_export.py) → [steam_exporter/simple_ui.py](steam_exporter/simple_ui.py). Auto-discovers the Steam library, lists games and their recordings, no AppID entry needed. Conversion runs in a **spawned subprocess**, not a QThread — see Architecture below.

Both apps share [steam_exporter/media.py](steam_exporter/media.py) (FFmpeg/FFprobe discovery, game-name resolution, `.m4s` discovery/grouping, first-frame preview, filename rendering, the `SteamExporter` service used by app 1) and [steam_exporter/models.py](steam_exporter/models.py) (`RecordingInput`, `PreflightResult`, `ConversionError`).

## Commands

Run everything through `uv` (no `pip` calls anywhere in this repo).

```powershell
# Run the English "Steam Video Exporter" GUI from source
uv run python .\steam_video_exporter.py

# Run the Chinese "Steam Quick Export" GUI from source
uv run python .\steam_quick_export.py

# Full test suite with coverage (same as CI and the pre-commit hook)
uv run --group test coverage run -m unittest discover -s tests -v
uv run --group test coverage report --fail-under=80

# Single test file / case / method
uv run python -m unittest tests.test_media -v
uv run python -m unittest tests.test_media.ConversionTests -v
uv run python -m unittest tests.test_media.ConversionTests.test_convert_stream_copies_a_recording_into_the_output_folder -v

# Package the English exporter as a onefile EXE (copies ffmpeg/ffprobe into dist/)
.\build.ps1

# Package the Quick Export UI as a onedir EXE (isolates PATH to avoid stray Qt/ICU DLLs)
.\build-quick.ps1
```

Both apps require `ffmpeg.exe` (and preferably `ffprobe.exe`) next to the script/EXE, on `PATH`, or via the `FFMPEG_PATH` env var — see `_ffmpeg_candidates()` in [steam_exporter/media.py](steam_exporter/media.py).

### Coverage scope

`pyproject.toml` restricts coverage to `steam_exporter` and omits `ui.py` and `worker.py` (Qt wiring, covered by manual/integration checks instead) with an 80% floor on the rest — mainly `media.py`, `models.py`, and `library.py`. New testable logic belongs in a plain module the coverage gate can see, not directly in a `QMainWindow`/`QThread`.

### Pre-commit hook

`.githooks/pre-commit` runs the full coverage-gated test suite before every commit. It's opt-in per clone:

```powershell
git config core.hooksPath .githooks
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the same two commands on `windows-latest`.

## Architecture

### Shared core (`steam_exporter/media.py`, `models.py`)

- **Discovery**: `discover_m4s` walks a folder for `.m4s` chunks (skipping `init-stream*`); `discover_recordings` groups them by Steam's `bg_<appid>_<timestamp>` directory convention so unrelated recording sessions are never concatenated together.
- **Game name resolution** (`resolve_game_name`): tries, in order, local `*.json` metadata in the recording/parent folder, then a local `appmanifest_<appid>.acf` (searched under the recording folder and known Steam library roots from `libraryfolders.vdf`), then the Steam store `appdetails` API (cached in-process in `_GAME_NAME_CACHE`), then falls back to the folder name.
- **Remuxing**: when a recording has a `session.mpd` DASH manifest, FFmpeg reads it directly; otherwise a concat-demuxer list file is built from the `.m4s` chunks. Either way `-c copy` is used — video/audio are never re-encoded, only remuxed/segmented.
- Segment sizing in `SteamExporter.convert` is estimated from bitrate and iteratively shortened (up to 3 attempts) if the largest produced segment exceeds the byte limit.

### App 1: Steam Video Exporter (manual, in-process)

`ui.py` builds the window and owns all Qt widgets; `worker.py`'s `TaskThread` runs `SteamExporter.preflight()`/`.convert()`/`extract_first_frame()` off the UI thread and reports back via Qt signals (`log_signal`, `progress_signal`, `preflight_signal`, `error_signal`, `done_signal`). This app supports arbitrary input roots, custom segment-size limits, and a user-editable filename token pattern (`{game} {source} {date} {time} {index} {ext}`, default in `DEFAULT_PATTERN`).

### App 2: Steam Quick Export (auto-discovery, out-of-process)

This app is layered differently because conversion runs in a **separate spawned process**, not a thread, so a hung/crashed FFmpeg export can't take the GUI down and can be hard-killed:

- [steam_exporter/library.py](steam_exporter/library.py) — `scan_library` discovers `bg_*` recordings per-game with a persistent JSON cache under `%LOCALAPPDATA%/SteamQuickExport/`. Directory `.m4s` sizes/mtimes are fingerprinted per-recording; a `ProcessPoolExecutor` (spawn context, capped workers) only re-inspects folders whose fingerprint changed. Game names are cached separately with a longer TTL (7 days, or 60s when resolution fell back to the raw folder name) and resolved concurrently via a `ThreadPoolExecutor`.
- [steam_exporter/simple_ui.py](steam_exporter/simple_ui.py) — the Chinese GUI itself. Library scans and first-frame previews run on local `QThread`s (`Job`); the actual export does not.
- [steam_exporter/export_client.py](steam_exporter/export_client.py) — `ExportClient`, a `QObject` that spawns the export as a `multiprocessing` (spawn context) `Process`, communicates over a one-way `Pipe`, and polls it with a `QTimer` (bounded per tick so a noisy backend can't starve the Qt event loop). Cancellation uses `taskkill /T /F` on the process tree, since the backend owns a live FFmpeg child.
- [steam_exporter/export_backend.py](steam_exporter/export_backend.py) — the function run inside that subprocess (`run_export`). Must stay free of Qt imports since it runs in a plain spawned interpreter. It redirects output that already exists (or has a `.pending` staging dir) into a timestamped subfolder rather than overwriting, then delegates to `scripts/export_game.main`.
- [scripts/export_game.py](scripts/export_game.py) — the actual export logic for this app: probes streams with ffprobe, remuxes each recording (`session.mpd`) to MP4 via stream copy into a `.pending` staging directory, and enforces a **strict decimal 64 GB cap** (`LIMIT = 64_000_000_000`, not GiB) by recursively bisecting oversized outputs at keyframe boundaries with `-f segment`. Verifies duration (within tolerance) and stream codec list match the source before accepting output, writes `verification.json`, and only then renames into the final output folder with `<game>_<timestamp>_<i>_of_<n>.mp4` naming. Source `.m4s` files are never deleted by this path.

### Standalone migration script

[scripts/export_library_and_prune.py](scripts/export_library_and_prune.py) is a separate, destructive one-off: it reuses `SteamExporter` from `media.py` (the App 1 core, GiB-style 64 GB limit) to migrate a whole library sequentially — one `bg_*` folder at a time — verifying output duration before `shutil.rmtree`-ing the source. It only runs with an explicit `--delete-sources` flag and hardcodes `D:\Videos\Steam` as the source root; treat any change here as high-risk since it deletes user data.

### Diagnostic scripts (not part of the test suite)

- [scripts/check_export_ipc.py](scripts/check_export_ipc.py) exercises `ExportClient` end-to-end (success and failure paths) against a real local Steam library and asserts the Qt event loop kept ticking during the subprocess export — a manual/local check, not run in CI.
- [scripts/benchmark_scan.py](scripts/benchmark_scan.py) times `scan_library` cold vs. cached against a real local library.

## Conventions worth knowing

- Both GUIs use `subprocess.CREATE_NO_WINDOW` on all FFmpeg/ffprobe calls to avoid flashing console windows.
- Filenames and folder names are sanitized with `safe_name()` (strips Windows-invalid characters) everywhere a game name or pattern is turned into a path component.
- The two apps intentionally use different segment-size conventions: App 1's GB radio buttons are binary (`1 GB = 1024**3`), App 2's cap is a strict decimal 64,000,000,000 bytes. Don't assume they're interchangeable when touching size-limit logic.
