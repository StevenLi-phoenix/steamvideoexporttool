"""Export one game's recordings without deleting sources or re-encoding."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from steam_exporter.media import find_executable, recording_timestamp, safe_name, unique_path

LIMIT = 64_000_000_000


def main(argv=None, log=print):
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
        raise RuntimeError("No recordings found")
    ffmpeg = find_executable("ffmpeg")
    ffprobe = find_executable("ffprobe", ffmpeg)
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and ffprobe are required")
    args.output.mkdir(parents=True, exist_ok=True)
    staging = args.output / ".pending"
    if staging.exists():
        raise RuntimeError("Existing pending export must be inspected before another run")
    total = sum(p.stat().st_size for f in folders for p in f.rglob("*.m4s"))
    if shutil.disk_usage(args.output).free < total * 1.15 + LIMIT:
        raise RuntimeError("Insufficient free space including splitting headroom")
    staging.mkdir()

    def probe(path):
        result = subprocess.run([str(ffprobe), "-v", "error", "-show_format", "-show_streams",
                                 "-of", "json", str(path)], capture_output=True, encoding="utf-8",
                                errors="replace", timeout=120, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError(f"ffprobe failed on {path}: {result.stderr[-2000:]}")
        data = json.loads(result.stdout)
        if not any(s["codec_type"] == "video" for s in data["streams"]):
            raise RuntimeError(f"Missing video: {path}")
        return data

    def remux(source, target, seconds=None):
        cmd = [str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
               "-i", str(source), "-map", "0", "-c", "copy"]
        if seconds is not None:
            cmd += ["-f", "segment", "-segment_time", str(seconds), "-reset_timestamps", "1"]
        cmd.append(str(target))
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError(result.stderr[-4000:])

    entries = []
    for index, folder in enumerate(folders, 1):
        log(f"[{index}/{len(folders)}] {folder.name}")
        manifest = folder / "session.mpd"
        original = probe(manifest)
        source_duration = float(original["format"]["duration"])
        target = staging / f"recording_{index:03d}.mp4"
        remux(manifest, target)
        pending = [target]
        parts = []
        while pending:
            part = pending.pop(0)
            data = probe(part)
            if part.stat().st_size >= LIMIT:
                seconds = float(data["format"]["duration"]) / 2
                if seconds < 1:
                    raise RuntimeError("Cannot split below cap with stream copy")
                split_dir = staging / (part.stem + "_split")
                split_dir.mkdir()
                remux(part, split_dir / "%04d.mp4", seconds)
                children = sorted(split_dir.glob("*.mp4"))
                if len(children) < 2:
                    raise RuntimeError("No usable keyframe split; pending outputs retained")
                part.unlink()
                pending[0:0] = children
            else:
                parts.append((part, data))
        duration = sum(float(d["format"]["duration"]) for _, d in parts)
        if abs(duration - source_duration) > max(2, len(parts) * 0.5):
            raise RuntimeError(f"Duration mismatch: source {source_duration}, output {duration}")
        expected = [(s["codec_type"], s.get("codec_name")) for s in original["streams"]]
        for part, data in parts:
            if [(s["codec_type"], s.get("codec_name")) for s in data["streams"]] != expected:
                raise RuntimeError("Stream/codec mismatch")
            entries.append((part, folder, data))
        log(f"Verified {len(parts)} part(s), {duration:.2f}s")

    report = []
    for index, (part, folder, data) in enumerate(entries, 1):
        stamp = recording_timestamp(folder).strftime("%Y-%m-%d_%H-%M-%S")
        dest = args.output / f"{safe_name(args.game)}_{stamp}_{index:03d}_of_{len(entries):03d}.mp4"
        if dest.exists():
            dest = unique_path(dest)
        size = part.stat().st_size
        if not 0 < size < LIMIT:
            raise RuntimeError("Output violates strict size cap")
        part.rename(dest)
        report.append({"file": str(dest), "bytes": size, "source": str(folder),
                       "duration": float(data["format"]["duration"]), "stream_copy": True})
    (args.output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for directory in sorted(staging.rglob("*"), reverse=True):
        if directory.is_dir():
            directory.rmdir()
    staging.rmdir()
    log(f"COMPLETE: {len(report)} files, {sum(r['bytes'] for r in report)} bytes; all < {LIMIT}. Sources retained.")


if __name__ == "__main__":
    main()
