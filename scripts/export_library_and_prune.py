"""Losslessly export a Steam recording library and delete only verified sources.

Run with --delete-sources. The script deliberately processes one bg_* recording directory
at a time so the completed MP4 replaces its source before the next recording begins.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.export_game import LIMIT, discard_staging, process_recording, publish
from steam_exporter.media import find_executable, resolve_game_name


def default_source_root() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos" / "Steam"


def main() -> None:
    # Start-Process output redirection inherits the active Windows code page by default.
    # Steam game names can contain characters outside that page, so make logs UTF-8 safe.
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=default_source_root(),
                        help="Steam video root containing the video\\bg_* folders (default: %%USERPROFILE%%\\Videos\\Steam).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Export destination (default: <source>\\exports).")
    parser.add_argument("--delete-sources", action="store_true",
                        help="Delete each source recording only after verification.")
    args = parser.parse_args()
    if not args.delete_sources:
        raise SystemExit("Refusing to delete source footage without --delete-sources.")

    video_root = args.source / "video"
    output_root = args.output or (args.source / "exports")
    if not video_root.is_dir():
        raise SystemExit(f"No Steam video folder was found at {video_root}.")
    folders = sorted(folder for folder in video_root.iterdir() if folder.is_dir() and folder.name.startswith("bg_"))
    if not folders:
        raise SystemExit("No Steam recording folders were found.")
    ffmpeg = find_executable("ffmpeg")
    ffprobe = find_executable("ffprobe", ffmpeg)
    if not ffmpeg or not ffprobe:
        raise SystemExit("FFmpeg and ffprobe are required.")
    output_root.mkdir(parents=True, exist_ok=True)

    for position, folder in enumerate(folders, start=1):
        if folder.parent.resolve() != video_root.resolve():
            raise SystemExit(f"Unexpected source folder: {folder}")
        print(f"\n[{position}/{len(folders)}] Exporting {folder.name}", flush=True)
        staging = output_root / ".pending"
        if staging.exists():
            raise SystemExit("Existing pending export must be inspected before another run")
        total = sum(path.stat().st_size for path in folder.rglob("*.m4s"))
        if shutil.disk_usage(output_root).free < total * 1.15 + LIMIT:
            raise SystemExit("Insufficient free space including splitting headroom")
        staging.mkdir()
        try:
            game = resolve_game_name(folder)
            parts = process_recording(folder, staging, ffmpeg, ffprobe, log=lambda m: print(m, flush=True))
            report = [publish(part, data, output_root, game, folder, index, len(parts))
                      for index, (part, data) in enumerate(parts, 1)]
            (output_root / f"verification-{folder.name}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            for entry in report:
                exported = Path(entry["file"])
                if not exported.is_file() or exported.stat().st_size <= 0:
                    raise SystemExit(f"Verified output is missing or empty: {exported}; source retained.")
        finally:
            if staging.exists():
                discard_staging(staging)
        print(f"Verified {len(report)} MP4 file(s). Deleting {folder.name}.", flush=True)
        shutil.rmtree(folder)

    if not any(video_root.iterdir()):
        video_root.rmdir()
    print("All original recording folders were exported, verified, and deleted.", flush=True)


if __name__ == "__main__":
    main()
