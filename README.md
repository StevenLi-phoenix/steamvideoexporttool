# Steam Video Exporter

Standalone Windows GUI for converting a folder of Steam Game Recording `.m4s` files into MP4, MOV, or FLV. The app uses the game name from nearby Steam metadata/app manifests instead of using the selected folder name.

## Run from source

1. Install Python 3.10+ on Windows.
2. Put `ffmpeg.exe` (and preferably `ffprobe.exe`) beside `steam_video_exporter.py`, or add FFmpeg to `PATH`.
3. Run:

```powershell
python .\steam_video_exporter.py
```

## Package as a standalone EXE

Install PyInstaller once, then run the included build script:

```powershell
python -m pip install pyinstaller
.\build.ps1
```

If FFmpeg is not installed globally, place `ffmpeg.exe` and `ffprobe.exe` in the project folder before building. The script includes them in the `dist` folder next to the EXE.

## Filename tokens

The default pattern is `{game}_{date}_{time}_part{index}.{ext}`.

Available tokens are `{game}`, `{source}`, `{date}` (`YYYY-MM-DD`), `{time}` (`HH-MM-SS`), `{index}` (`001`, `002`, ...), and `{ext}`.

## Notes

- Preflight checks the input folder, `.m4s` discovery, FFmpeg availability, output-folder writability, and free disk space.
- Conversion stages output files in a temporary subfolder and only moves completed segments into the selected output folder.
- Segment size is treated as GiB-style GB (`1 GB = 1024^3 bytes`) and is checked after encoding. The app automatically retries with shorter segment durations when a segment is too large.
