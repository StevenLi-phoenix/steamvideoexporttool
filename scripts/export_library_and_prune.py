"""Losslessly export a Steam recording library and delete only verified sources.

Run with --delete-sources. The script deliberately processes one bg_* recording directory
at a time so the completed MP4 replaces its source before the next recording begins.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from steam_exporter.media import SteamExporter, find_executable, format_bytes
from steam_exporter.models import ConversionError


SOURCE_ROOT = Path(r"D:\Videos\Steam")
OUTPUT_ROOT = SOURCE_ROOT / "exports"
SEGMENT_LIMIT = 16 * 1024**3


def duration(path: Path, ffprobe: Path | None) -> float | None:
    if not ffprobe:
        return None
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-i", str(path), "-show_entries", "format=duration", "-of", "default=nk=1:nw=1"],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def verify_outputs(created: set[Path], source_duration: float | None, ffprobe: Path | None) -> None:
    if not created:
        raise ConversionError("No new MP4 files were produced; source files will be retained.")
    sizes = [path.stat().st_size for path in created]
    if any(size <= 0 for size in sizes):
        raise ConversionError("An output file is empty; source files will be retained.")
    exported_duration = sum(value for value in (duration(path, ffprobe) for path in created) if value is not None)
    if source_duration and exported_duration < source_duration * 0.98:
        raise ConversionError(
            f"Output duration ({exported_duration:.1f}s) is shorter than source ({source_duration:.1f}s); source files will be retained."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete-sources", action="store_true", help="Delete each source recording only after verification.")
    args = parser.parse_args()
    if not args.delete_sources:
        raise SystemExit("Refusing to delete source footage without --delete-sources.")

    video_root = SOURCE_ROOT / "video"
    output_root = OUTPUT_ROOT
    output_root.mkdir(parents=True, exist_ok=True)
    folders = sorted(folder for folder in video_root.iterdir() if folder.is_dir() and folder.name.startswith("bg_"))
    if not folders:
        raise SystemExit("No Steam recording folders were found.")

    exporter = SteamExporter(lambda message: print(message, flush=True), lambda _: None)
    for position, folder in enumerate(folders, start=1):
        if folder.parent.resolve() != video_root.resolve():
            raise ConversionError(f"Unexpected source folder: {folder}")
        print(f"\n[{position}/{len(folders)}] Exporting {folder.name}", flush=True)
        result = exporter.preflight(str(folder), str(output_root))
        if not result.ok:
            raise ConversionError("Preflight failed: " + " ".join(result.errors))
        source_duration = duration(result.recordings[0].manifest, result.ffprobe) if result.recordings[0].manifest else None
        existing = {path.resolve() for path in output_root.glob("*.mp4")}
        exporter.convert(result, str(output_root), "mp4", SEGMENT_LIMIT, "{game}_{date}_{time}_part{index}.{ext}")
        created = {path.resolve() for path in output_root.glob("*.mp4")} - existing
        verify_outputs(created, source_duration, result.ffprobe)
        print(f"Verified {len(created)} MP4 file(s), {format_bytes(sum(path.stat().st_size for path in created))}. Deleting {folder}.", flush=True)
        shutil.rmtree(folder)

    if not any(video_root.iterdir()):
        video_root.rmdir()
    print("All original recording folders were exported, verified, and deleted.", flush=True)


if __name__ == "__main__":
    main()
