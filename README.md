# Steam Video Exporter

<p align="center">
  <img src="assets/app-screenshot.png" alt="Steam Video Exporter application window" width="960">
</p>

Standalone Windows GUI for losslessly remuxing a Steam Game Recording folder into MP4, MOV, or FLV. It accepts one recording folder or a Steam library root such as `D:\Videos\Steam`; library roots are grouped by each `bg_<appid>_<timestamp>` recording directory so unrelated sessions are never concatenated. The app uses the game name from nearby Steam metadata/app manifests instead of using the selected folder name.

## Run from source

1. Install Python 3.10+ and [uv](https://docs.astral.sh/uv/) on Windows.
2. Put `ffmpeg.exe` (and preferably `ffprobe.exe`) beside `steam_video_exporter.py`, or add FFmpeg to `PATH`.
3. Run with uv (the project environment is created automatically):

```powershell
uv run python .\steam_video_exporter.py
```

## TDD pre-commit hook

The repository uses the version-controlled `.githooks/pre-commit` hook to run the unit-test suite before each commit. Enable it once per clone:

```powershell
git config core.hooksPath .githooks
```

The hook also enforces an 80% minimum coverage threshold for the testable conversion core (`steam_exporter.media` and `steam_exporter.models`). The Qt UI and thread wiring are covered separately through integration checks.

## Package as a standalone EXE

The included build script uses the uv-managed environment and does not call `pip`:

```powershell
.\build.ps1
```

If FFmpeg is not installed globally, place `ffmpeg.exe` and `ffprobe.exe` in the project folder before building. The script includes them in the `dist` folder next to the EXE.

## Filename tokens

The default pattern is `{game}_{date}_{time}_part{index}.{ext}`.

Available tokens are `{game}`, `{source}`, `{date}` (`YYYY-MM-DD`), `{time}` (`HH-MM-SS`), `{index}` (`001`, `002`, ...), and `{ext}`.

## Notes

- Preflight checks the input folder, recording grouping, `.m4s` discovery, FFmpeg availability, output-folder writability, and free disk space.
- After preflight, each recording folder appears as a checked item; clear individual items or use Select all/Clear all to choose a partial batch.
- Select a recording and use Preview first frame to generate a temporary thumbnail through FFmpeg.
- Conversion uses FFmpeg stream copy (`-c copy`) and never re-renders the video or audio. If the source codecs are not accepted by the requested container, the app reports the failure instead of silently re-encoding.
- Conversion stages output files in a temporary subfolder and only moves completed segments into the selected output folder.
- Segment size is treated as GiB-style GB (`1 GB = 1024^3 bytes`) and is checked after encoding. The app automatically retries with shorter segment durations when a segment is too large.
