# AGENTS.md

Windows and macOS desktop tool (PySide6 + FFmpeg stream copy) that losslessly remuxes
Steam Game Recording M4S/DASH sessions into MP4. All Python commands go through
**uv** — never use pip directly.

## Commands

```powershell
uv run python .\steam_quick_export.py                        # run the app
uv run --group test coverage run -m unittest discover -s tests -v
uv run --group test coverage report                          # fail_under=80
uv run --group lint ruff check .                             # E/F/W/I/B/UP, line-length 140
uv run --group lint ruff format .
.\scripts\get-ffmpeg.ps1                                     # pinned FFmpeg 7.1.1 -> dist\ (SHA-256 verified)
.\build-quick.ps1                                            # PyInstaller -> dist-simple\SteamQuickExport\ (local: no bundled FFmpeg, uses PATH; -BundleFFmpeg embeds dist\ binaries like CI)
uv run python steam_quick_export.py --self-test --scan-self-test   # smoke test
```

CI (`.github/workflows/ci.yml`) runs tests + ruff on Windows and macOS, plus native builds.
On macOS, use `bash build-macos.sh` to build `dist-macos/SteamQuickExport.app`.
The Mac app needs separately installed FFmpeg (`brew install ffmpeg-full`). Its smoke test is
`dist-macos/SteamQuickExport.app/Contents/MacOS/SteamQuickExport --self-test --scan-self-test`.
For cloud-synced checkouts, set `MACOS_DIST_DIR=/tmp/steamquickexport-dist` when building;
the filesystem can reattach Finder metadata and make codesign reject a bundle in Documents.
Enable the pre-commit hook with `git config core.hooksPath .githooks` (it runs
ruff + the full suite, so commits take a minute).

## Architecture boundaries

- **One UI**: `steam_quick_export.py` → `steam_exporter/simple_ui.py`. The old
  manual-export UI lives archived on the `main-old` branch — never revive it.
- **One export pipeline**: `scripts/export_game.py` (`process_recording` /
  `publish` / `discard_staging`, strict 64 GB cap, keyframe-safe splitting,
  duration/stream verification, `verification.json`). Both the GUI backend
  (`export_client.py` → `export_backend.py`, spawned process + pipe IPC) and the
  batch script reuse it. Do not create a second remux/split implementation.
- `steam_exporter/media.py`: FFmpeg discovery, Steam library roots, game-name
  resolution, previews, shared helpers (`safe_name`, `recording_timestamp`,
  `unique_path`, `ConversionError`). `steam_exporter/library.py`: cached library scan.
- `steam_exporter/platform_paths.py`: guarded Windows registry access, macOS Movies
  and Application Support paths, Steam account recording-folder discovery. Saved
  folder choices override discovery; custom Steam recording locations remain selectable.
- The export worker calls `setsid()` on macOS before sending the `ready` IPC event.
  Cancellation waits for this event, then kills the worker's process group (including
  FFmpeg); Windows retains `taskkill /T /F`. Do not signal the GUI's process group.
- Frozen resources use `_MEIPASS`; Mac FFmpeg lookup also checks Homebrew locations
  because Finder does not inherit a terminal's PATH. Prefer the keg-only `ffmpeg-full`
  binary over PATH: the minimal Homebrew formula can lack DASH demuxing. Test with
  an actual `session.mpd`, not just `ffmpeg -version`.
- **Destructive script**: `scripts/export_library_and_prune.py` deletes source
  recordings. Treat changes as high risk: keep the `--delete-sources` gate,
  per-recording verify-then-delete order, and the `video_root.resolve()` boundary check.
- Coverage `source` includes `scripts/`; `simple_ui.py`/`export_client.py`/
  `export_backend.py` and the IPC/benchmark/icon helper scripts are omitted.
  `scripts/check_export_ipc.py` is a manual integration test (needs real
  recordings): `uv run python -m scripts.check_export_ipc --source <video root>`.

## Conventions

- Decode all FFmpeg/ffprobe subprocess output with `encoding="utf-8", errors="replace"`;
  pass `creationflags=CREATE_NO_WINDOW` on Windows; surface stderr tails in errors
  instead of bare messages.
- Stream copy only (`-c copy`) — never re-encode. Sanitize filenames with `safe_name()`.
- Tests must be hermetic: patch `find_executable` (e.g. `patch.object(export_game, "find_executable", ...)`)
  and `subprocess.run`, and mock `resolve_game_name` — no real FFmpeg, no network.
  CI has no FFmpeg on PATH and no Steam library.
- Type-annotate new/edited functions; UI strings are Chinese by default.
- All user-visible strings (GUI chrome, dialogs, pipeline/batch-script messages) go through
  `steam_exporter/i18n.py` `tr()`; add every key to **both** the zh-cn and en tables
  (a parity test enforces it). Pipeline messages are translated because the spawned
  export backend reads the language from `settings.json`. Tests pin the language with
  `i18n.set_language("en", persist=False)` so assertions stay deterministic.

## Gotchas

- `UV_MANAGED_PYTHON=1` in this machine's env conflicts with newer uv — run
  `unset UV_MANAGED_PYTHON` before uv commands; for network commands also unset
  `http_proxy https_proxy all_proxy` (the VPN is TUN-based).
- `store.steampowered.com` is blocked in China; game-name web resolution falls
  back to local ACF manifests. Don't rely on Steam API reachability in tests.
- `dist\` is the pinned-FFmpeg staging dir, embedded only with
  `build-quick.ps1 -BundleFFmpeg` (CI/release); local personal builds rely on
  the PATH ffmpeg (`find_executable` falls back to `shutil.which`).
  `dist-simple\` is the build output. Both git-ignored.
- **Shortcut contract**: the user launches the app via
  `D:\Videos\Steam 录制导出.lnk`, which targets
  `dist-simple\SteamQuickExport\SteamQuickExport.exe`. Keep that output path
  stable across build-script/refactor changes so the shortcut keeps working.
- Release flow: tag `v*` must match `version` in `pyproject.toml` (workflow
  verifies); release re-runs are idempotent (`gh release upload --clobber`).
- Read `CLAUDE.md` before touching the export pipeline or the prune script —
  it documents the contributor rules in more detail.
