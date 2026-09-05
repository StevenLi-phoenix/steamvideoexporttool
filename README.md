# Steam Video Exporter

<p align="center">
  <img src="assets/app-screenshot.png" alt="Steam Video Exporter application window" width="960">
</p>

Losslessly remux Steam Game Recording footage into MP4, MOV, or FLV — no
re-encoding, so quality and sync are identical to the original capture.

Two Windows GUIs, pick whichever fits you:

- **Steam Video Exporter** — English UI, manual: point it at an input folder
  (a single recording or a whole library) and an output folder.
- **Steam Quick Export** ("Steam 录制") — Chinese UI, automatic: finds your
  whole Steam library and every game's recordings on its own, no folder or
  AppID entry needed.

> Looking for architecture, internals, or contributor notes instead? See
> [CLAUDE.md](CLAUDE.md).

## Downloads

Grab the latest build from [Releases](../../releases). Each app ships as two
zips per version:

- **`...-win-x64-ffmpeg.zip`** — includes FFmpeg/ffprobe, works out of the box.
- **`...-win-x64.zip`** — smaller, for when you already have FFmpeg on `PATH`
  or want to supply your own.

## Steam Video Exporter (manual, English UI)

Point it at a single recording folder or a library root such as
`D:\Videos\Steam` and it groups recordings automatically so unrelated
sessions are never mixed together.

- Resolves the real game name (from Steam metadata, not the folder name).
- Checkable batch list with Select all / Clear all, and a first-frame preview.
- MP4, MOV, or FLV output, with 16 GB, 64 GB, or custom maximum segment sizes.
- Custom output folder and filename tokens.
- Preflight checks (source, FFmpeg, output folder, free disk space) before you convert.

### Run from source

1. Install Python 3.10+ and [uv](https://docs.astral.sh/uv/) on Windows.
2. Put `ffmpeg.exe` (and preferably `ffprobe.exe`) beside `steam_video_exporter.py`,
   or add FFmpeg to `PATH`.
3. Run with uv (the project environment is created automatically):

```powershell
uv run python .\steam_video_exporter.py
```

### Package as a standalone EXE

```powershell
.\build.ps1
```

Keep the resulting `SteamVideoExporter.exe`, `ffmpeg.exe`, and `ffprobe.exe`
(all in `dist\`) together when moving the app around.

### Filename tokens

Default pattern: `{game}_{date}_{time}_part{index}.{ext}`.

Available tokens: `{game}`, `{source}`, `{date}` (`YYYY-MM-DD`), `{time}`
(`HH-MM-SS`), `{index}` (`001`, `002`, ...), `{ext}`.

## Steam Quick Export ("Steam 录制", automatic, Chinese UI)

<p align="center">
  <img src="assets/app-screenshot-quick.png" alt="Steam Quick Export application window" width="960">
</p>

Run `uv run python steam_quick_export.py`, or launch the packaged
`SteamQuickExport.exe`. Click a game, check the recordings you want, click one
for a first-frame preview, hit export. **Source recordings are never deleted
by this app.** Output defaults to your Windows Videos folder under
`exported/<game>/`.

- Scans your whole library automatically and caches the result, so reopening
  the app is fast; hold Shift while clicking Refresh to force a full rescan.
- **Open Steam Recordings** opens Steam's own screenshot/recording manager so
  you can delete captures through Steam; click Refresh afterward.
- Exporting runs in the background, so the library stays browsable and you
  can cancel an export at any time without closing the app.
- Output is MP4 via stream copy, capped at 64 GB per file (larger recordings
  are split automatically), and each export writes a `verification.json`
  confirming durations and codecs matched the source.

### Package as a standalone EXE

```powershell
.\build-quick.ps1
```

Keep the entire `dist-simple\SteamQuickExport\` folder together — it bundles
Python, Qt, FFmpeg, and ffprobe.

## Exporting a whole library and deleting source fragments

For a large library with insufficient free space to duplicate everything at
once, use the sequential migration script. It exports one recording at a time
to `D:\Videos\Steam\exports`, verifies the resulting MP4 segments with FFprobe,
then deletes only that recording's original source folder before starting the
next one.

> Warning: this permanently deletes the original Steam recording fragments
> after verification. Confirm that `D:\Videos\Steam\exports` is the intended
> destination before running it.

```powershell
uv run python -m scripts.export_library_and_prune --delete-sources
```

It stops on any failed preflight, remux, or duration verification, leaving the
current source recording intact. Progress is written to
`D:\Videos\Steam\exports\export-and-prune.log`.
