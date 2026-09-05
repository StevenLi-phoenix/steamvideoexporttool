# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Windows-only tool that losslessly remuxes Steam Game Recording `.m4s` DASH fragments into MP4/MOV/FLV using FFmpeg stream copy (`-c copy`) — no re-encoding. The repo actually contains **two separate PySide6 GUI applications** that share a common core:

1. **Steam Video Exporter** (English UI) — entry point [steam_video_exporter.py](steam_video_exporter.py) → [steam_exporter/ui.py](steam_exporter/ui.py). Manual workflow: user points at an input folder (a single recording or a library root) and an output folder, runs preflight, picks recordings from a checklist, converts. Conversion runs in a `QThread` ([steam_exporter/worker.py](steam_exporter/worker.py)) inside the same process.
2. **Steam Quick Export / "Steam 录制"** (Chinese UI) — entry point [steam_quick_export.py](steam_quick_export.py) → [steam_exporter/simple_ui.py](steam_exporter/simple_ui.py). Auto-discovers the Steam library, lists games and their recordings, no AppID entry needed. Conversion runs in a **spawned subprocess**, not a QThread — see Architecture below.

Both apps share [steam_exporter/media.py](steam_exporter/media.py) (FFmpeg/FFprobe discovery, game-name resolution, `.m4s` discovery/grouping, first-frame preview, filename rendering, the `SteamExporter` service used by app 1) and [steam_exporter/models.py](steam_exporter/models.py) (`RecordingInput`, `PreflightResult` with an `.ok` property, `ConversionError`).

Package metadata: `pyproject.toml` pins `PySide6>=6.7,<7`, requires Python `>=3.10`, and only declares one runtime dependency — everything else (PyInstaller, coverage) is a `uv` dependency group, never installed via `pip`.

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
uv run python -m unittest tests.test_library -v

# Package the English exporter as a onefile EXE (copies ffmpeg/ffprobe into dist/)
.\build.ps1

# Package the Quick Export UI as a onedir EXE (isolates PATH, embeds ffmpeg/ffprobe from dist/)
.\build-quick.ps1
```

Both apps require `ffmpeg.exe` (and preferably `ffprobe.exe`) next to the script/EXE, on `PATH`, or via the `FFMPEG_PATH` env var — see `_ffmpeg_candidates()` in [steam_exporter/media.py](steam_exporter/media.py). `build-quick.ps1` expects `dist\ffmpeg.exe`/`dist\ffprobe.exe` to already exist (run `build.ps1` first, or drop them there yourself) since it embeds them via `--add-binary` rather than resolving them itself.

Packaged Quick Export builds support a smoke-test mode invoked as `SteamQuickExport.exe --self-test` (verifies bundled ffmpeg/ffprobe run, then exits without showing a real scan) and `--self-test --scan-self-test` (also forces one real `scan_library` pass) — see `main()` in [steam_exporter/simple_ui.py](steam_exporter/simple_ui.py).

### Coverage scope

`pyproject.toml` restricts coverage to `steam_exporter` and omits the Qt-facing/subprocess-wiring modules of both apps: App 1's `ui.py` and `worker.py`, and App 2's `simple_ui.py`, `export_client.py`, and `export_backend.py` (all covered by manual/integration checks instead — [scripts/check_export_ipc.py](scripts/check_export_ipc.py) for the export pipeline). The 80% floor applies to what's left — mainly `media.py`, `models.py`, and `library.py` — exercised by [tests/test_media.py](tests/test_media.py) and [tests/test_library.py](tests/test_library.py). New testable logic belongs in one of those plain modules the coverage gate can see, not directly in a `QMainWindow`/`QThread`/spawned-process entry point; if you do add real logic to an omitted module, add tests for it rather than relying on the omit to hide the gap.

### Pre-commit hook

`.githooks/pre-commit` runs the full coverage-gated test suite before every commit (with `uv`/WinGet-uv/`.venv`/bare-`python` fallbacks, in that order). It's opt-in per clone:

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

- [steam_exporter/library.py](steam_exporter/library.py) — `scan_library` discovers `bg_*` recordings per-game with a persistent JSON cache at `%LOCALAPPDATA%/SteamQuickExport/library-<sha256-of-resolved-path>.json` (`cache_path`). Each recording is fingerprinted by `inspect_folder`: total `.m4s` bytes, the mtime of every directory under it, and `session.mpd`'s `(mtime_ns, size)`; `valid()` reuses a cache entry only if all of those still match *and* the entry is under `CACHE_TTL` (300s) old — otherwise a `ProcessPoolExecutor` (spawn context, `min(workers, pending)` capped at 4 by default) re-inspects it. Game names live in a separate `names` map with a much longer TTL (7 days, or 60s if resolution fell back to the raw folder name) and are resolved concurrently via a `ThreadPoolExecutor`. The cache file is written atomically (temp file + `os.replace`) so a crash or overlapping instance never sees a half-written JSON. Passing `force=True` (Shift-click Refresh in the UI) bypasses cache validity but still writes results back into it.
- [steam_exporter/simple_ui.py](steam_exporter/simple_ui.py) — the Chinese GUI itself (`SimpleApp`). Library scans and first-frame previews run on local `QThread`s (`Job`, a thin wrapper that calls `action(log_callback)` and emits `result`/`failed`); the actual export does not — it goes through `ExportClient`. `open_steam_recordings()` opens `steam://open/screenshots`, i.e. Steam's "View > Screenshots and Recordings" manager — **not** `steam://open/settings`, which is the wrong destination and was a bug fixed once already; don't regress it if this button is touched again.
- [steam_exporter/export_client.py](steam_exporter/export_client.py) — `ExportClient`, a `QObject` that spawns the export as a `multiprocessing` (spawn context) `Process` running `export_backend.run_export`, communicates over a one-way `Pipe`, and polls it with a 100ms `QTimer` (bounded to 50 pipe reads per tick so a noisy backend can't starve the Qt event loop). Cancellation shells out to `taskkill /PID <pid> /T /F`, since the backend owns a live FFmpeg child that Python-level termination wouldn't reach.
- [steam_exporter/export_backend.py](steam_exporter/export_backend.py) — `run_export(arguments, sender)`, the function run inside that subprocess. Must stay free of Qt imports since it runs in a plain spawned interpreter. Before delegating to `scripts/export_game.main`, it redirects the `--output` argument into a `export_%Y%m%d_%H%M%S_%f`-stamped subfolder if the target already has `.mp4` files or a `.pending` staging dir, so a rerun never overwrites a previous export. Reports progress as `("log", str)` messages over the pipe, then a terminal `("done", output_path)` or `("error", "ExcType: message")`.
- [scripts/export_game.py](scripts/export_game.py) — the actual export logic for this app, invoked as a CLI (`--source`, `--output`, `--appid`, `--game`, repeatable `--recording`). Probes every `session.mpd` with ffprobe first and rejects anything without a video stream; checks `shutil.disk_usage(output).free >= total_source_bytes * 1.15 + LIMIT` before starting. Remuxes each recording via stream copy into a `.pending` staging directory (refuses to run if `.pending` already exists — "must be inspected before another run"); enforces a **strict decimal 64 GB cap** (`LIMIT = 64_000_000_000`, not GiB) by recursively bisecting any output at or above the cap in half at keyframe boundaries with `-f segment -segment_time <duration/2>`, giving up if a candidate segment would need to be under 1 second. After splitting, verifies total duration against the source (tolerance `max(2, parts * 0.5)` seconds) and that every part's `(codec_type, codec_name)` stream list exactly matches the source before accepting it. Only then renames parts out of staging into `<game>_<timestamp>_<i>_of_<n>.mp4` and writes a `verification.json` array of `{file, bytes, source, duration, stream_copy: true}` per output. Source `.m4s` files are never touched by this path.

### Standalone migration script

[scripts/export_library_and_prune.py](scripts/export_library_and_prune.py) is a separate, destructive one-off: it reuses `SteamExporter` from `media.py` (the App 1 core, GiB-style 64 GB limit) to migrate a whole library sequentially — one `bg_*` folder at a time — verifying output duration before `shutil.rmtree`-ing the source. It only runs with an explicit `--delete-sources` flag and hardcodes `D:\Videos\Steam` as the source root; treat any change here as high-risk since it deletes user data.

### Diagnostic scripts (not part of the test suite)

- [scripts/check_export_ipc.py](scripts/check_export_ipc.py) exercises `ExportClient` end-to-end (success and failure paths) against a real local Steam library and asserts the Qt event loop kept ticking during the subprocess export — a manual/local check, not run in CI.
- [scripts/benchmark_scan.py](scripts/benchmark_scan.py) times `scan_library` cold vs. cached against a real local library.

## Conventions worth knowing

- Both GUIs use `subprocess.CREATE_NO_WINDOW` on all FFmpeg/ffprobe calls to avoid flashing console windows.
- Filenames and folder names are sanitized with `safe_name()` (strips Windows-invalid characters) everywhere a game name or pattern is turned into a path component.
- The two apps intentionally use different segment-size conventions: App 1's GB radio buttons are binary (`1 GB = 1024**3`), App 2's cap is a strict decimal 64,000,000,000 bytes. Don't assume they're interchangeable when touching size-limit logic.
- Steam's `steam://` URI scheme is easy to get subtly wrong — `steam://open/settings` opens general Settings, not the recordings manager; the correct target for "let the user delete recordings" is `steam://open/screenshots`.
- [assets/app-screenshot-quick.png](assets/app-screenshot-quick.png) (Steam Quick Export) is the only current, accurate screenshot in the repo and is what README.md embeds. A prior `assets/app-screenshot.png` (Steam Video Exporter) was removed as stale/deprecated — don't reintroduce it without confirming it still matches the current UI.
- In CI/release workflows, `& SteamQuickExport.exe args...; $LASTEXITCODE` does **not** reliably capture the exit code for this windowed exe on `windows-latest` runners (observed empty/`$null`, which makes `-ne 0` checks throw even on success). Use `Start-Process -FilePath ... -ArgumentList ... -PassThru -Wait` and check `$process.ExitCode` instead — see the smoke-test steps in [ci.yml](.github/workflows/ci.yml) / [release.yml](.github/workflows/release.yml).
