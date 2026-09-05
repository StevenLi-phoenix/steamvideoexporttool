"""Export one game's recordings without deleting sources or re-encoding.

This is the single export pipeline used by both the GUI backend and the
batch migration script: stream-copy remux, split over the strict size cap,
verify duration and streams, then publish.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from steam_exporter.i18n import tr
from steam_exporter.media import find_executable, format_bytes, recording_timestamp, safe_name, unique_path

LIMIT = 64_000_000_000


def _probe(ffprobe: Path, path: Path) -> dict:
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError(tr("probe_failed", path=path, stderr=result.stderr[-2000:]))
    data = json.loads(result.stdout)
    if not any(s["codec_type"] == "video" for s in data["streams"]):
        raise RuntimeError(tr("missing_video", path=path))
    return data


def _remux(ffmpeg: Path, source: Path, target: Path, seconds: float | None = None) -> None:
    command = [str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source), "-map", "0", "-c", "copy"]
    if seconds is not None:
        command += ["-f", "segment", "-segment_time", str(seconds), "-reset_timestamps", "1"]
    command.append(str(target))
    result = subprocess.run(
        command, capture_output=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    if result.returncode:
        raise RuntimeError(tr("remux_failed", stderr=result.stderr[-4000:]))


def process_recording(
    folder: Path, staging: Path, ffmpeg: Path, ffprobe: Path, *, limit: int = LIMIT, log=print
) -> list[tuple[Path, dict]]:
    """Stream-copy one bg_ recording folder into staging, split any part over the
    strict size cap, and verify total duration and streams against the source."""
    manifest = folder / "session.mpd"
    original = _probe(ffprobe, manifest)
    source_duration = float(original["format"]["duration"])
    target = staging / f"{folder.name}.mp4"
    _remux(ffmpeg, manifest, target)
    pending = [target]
    parts: list[tuple[Path, dict]] = []
    while pending:
        part = pending.pop(0)
        data = _probe(ffprobe, part)
        if part.stat().st_size >= limit:
            seconds = float(data["format"]["duration"]) / 2
            if seconds < 1:
                raise RuntimeError(tr("cannot_split"))
            split_dir = staging / (part.stem + "_split")
            split_dir.mkdir()
            _remux(ffmpeg, part, split_dir / "%04d.mp4", seconds)
            children = sorted(split_dir.glob("*.mp4"))
            if len(children) < 2:
                raise RuntimeError(tr("no_split"))
            part.unlink()
            pending[0:0] = children
        else:
            parts.append((part, data))
    duration = sum(float(d["format"]["duration"]) for _, d in parts)
    if abs(duration - source_duration) > max(2, len(parts) * 0.5):
        raise RuntimeError(tr("duration_mismatch", source=f"{source_duration:.2f}", output=f"{duration:.2f}"))
    expected = [(s["codec_type"], s.get("codec_name")) for s in original["streams"]]
    for _, data in parts:
        if [(s["codec_type"], s.get("codec_name")) for s in data["streams"]] != expected:
            raise RuntimeError(tr("stream_mismatch"))
    log(tr("verified", folder=folder.name, count=len(parts), duration=f"{duration:.2f}"))
    return parts


def publish(part: Path, data: dict, output: Path, game: str, folder: Path, index: int, total: int, *, limit: int = LIMIT) -> dict:
    """Rename a verified staged part to its final export name, avoiding collisions."""
    stamp = recording_timestamp(folder).strftime("%Y-%m-%d_%H-%M-%S")
    dest = output / f"{safe_name(game)}_{stamp}_{index:03d}_of_{total:03d}.mp4"
    if dest.exists():
        dest = unique_path(dest)
    size = part.stat().st_size
    if not 0 < size < limit:
        raise RuntimeError(tr("size_cap"))
    part.rename(dest)
    return {"file": str(dest), "bytes": size, "source": str(folder), "duration": float(data["format"]["duration"]), "stream_copy": True}


def discard_staging(staging: Path) -> None:
    """Remove the staging tree; leftover files mean unverified outputs and raise."""
    for directory in sorted(staging.rglob("*"), reverse=True):
        if directory.is_dir():
            directory.rmdir()
    staging.rmdir()


def main(argv=None, log=print, limit=LIMIT):
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--appid", required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--recording", action="append", default=[])
    args = parser.parse_args(argv)
    folders = sorted(args.source.glob(f"bg_{args.appid}_*"))
    if args.recording:
        folders = [folder for folder in folders if folder.name in set(args.recording)]
    if not folders:
        raise RuntimeError(tr("no_recordings"))
    ffmpeg = find_executable("ffmpeg")
    ffprobe = find_executable("ffprobe", ffmpeg)
    if not ffmpeg or not ffprobe:
        raise RuntimeError(tr("need_ffmpeg"))
    args.output.mkdir(parents=True, exist_ok=True)
    staging = args.output / ".pending"
    if staging.exists():
        raise RuntimeError(tr("pending_exists"))
    total = sum(p.stat().st_size for f in folders for p in f.rglob("*.m4s"))
    if shutil.disk_usage(args.output).free < total * 1.15 + limit:
        raise RuntimeError(tr("no_space"))
    staging.mkdir()

    entries: list[tuple[Path, dict, Path]] = []
    for index, folder in enumerate(folders, 1):
        log(tr("progress", index=index, total=len(folders), folder=folder.name))
        for part, data in process_recording(folder, staging, ffmpeg, ffprobe, limit=limit, log=log):
            entries.append((part, data, folder))

    report = [
        publish(part, data, args.output, args.game, folder, number, len(entries), limit=limit)
        for number, (part, data, folder) in enumerate(entries, 1)
    ]
    (args.output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    discard_staging(staging)
    log(tr("complete", count=len(report), size=format_bytes(sum(r["bytes"] for r in report)), limit=format_bytes(limit)))


if __name__ == "__main__":
    main()
