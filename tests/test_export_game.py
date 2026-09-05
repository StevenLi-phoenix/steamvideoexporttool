"""Tests for the shared export pipeline in scripts/export_game.py.

FFmpeg/ffprobe subprocesses are faked: probes return canned JSON and remuxes
write real small files, driven with a tiny injectable size cap so the
split/verify/publish logic runs for real.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import scripts.export_game as export_game

STREAMS = [{"codec_type": "video", "codec_name": "h264"},
           {"codec_type": "audio", "codec_name": "aac"}]


class FakeMedia:
    """Fake ffprobe (canned JSON per path) + ffmpeg remux (writes real files)."""

    def __init__(self, streams=STREAMS, split_children=2):
        self.probe_data: dict[str, dict] = {}
        self.split_children = split_children
        self.streams = streams
        self.calls: list[list[str]] = []

    def register(self, path: Path, duration: float, streams=None) -> None:
        self.probe_data[str(path)] = {
            "streams": self.streams if streams is None else streams,
            "format": {"duration": str(duration)},
        }

    def run(self, command, **kwargs):
        self.calls.append(command)
        if Path(command[0]).name.startswith("ffprobe"):
            path = str(Path(command[-1]))
            if path not in self.probe_data:
                return SimpleNamespace(returncode=1, stdout="", stderr=f"Invalid data found when processing input: {path}")
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.probe_data[path]), stderr="")
        target = Path(command[-1])
        source = Path(command[[i for i, token in enumerate(command) if token == "-i"][0] + 1])
        if "%04d" in target.name:  # segment split of an oversized part
            parent_duration = float(self.probe_data[str(source)]["format"]["duration"])
            for child_index in range(self.split_children):
                child = target.parent / target.name.replace("%04d", f"{child_index:04d}")
                child.write_bytes(b"x" * 4)
                self.register(child, parent_duration / self.split_children)
        else:
            target.write_bytes(b"x" * 8)
            self.register(target, 100.0)
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def make_recording(root: Path, name="bg_620_20260725_104500") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "chunk-stream0-00001.m4s").write_bytes(b"chunk")
    (folder / "session.mpd").write_bytes(b"mpd")
    return folder


class ExportGameTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = make_recording(self.root)
        self.output = self.root / "out"
        self.media = FakeMedia()
        self.media.register(self.source / "session.mpd", 100.0)
        self.patcher = patch.object(export_game.subprocess, "run", side_effect=self.media.run)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def run_main(self, limit=1000, recording=None):
        export_game.main(
            ["--source", str(self.source.parent), "--output", str(self.output),
             "--appid", "620", "--game", "Portal 2"] + (recording or []),
            log=lambda message: None, limit=limit,
        )

    def test_remux_publishes_verified_output_and_writes_report(self):
        self.run_main()
        exports = sorted(self.output.glob("*.mp4"))
        self.assertEqual([path.name for path in exports],
                         ["Portal 2_2026-07-25_10-45-00_001_of_001.mp4"])
        report = json.loads((self.output / "verification.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report), 1)
        self.assertTrue(report[0]["stream_copy"])
        self.assertEqual(Path(report[0]["file"]), exports[0])
        self.assertFalse((self.output / ".pending").exists())

    def test_oversized_part_is_split_and_both_parts_published(self):
        # limit below the fake remux size (8 bytes) forces one split round.
        self.run_main(limit=5)
        exports = sorted(self.output.glob("*.mp4"))
        self.assertEqual(len(exports), 2)
        report = json.loads((self.output / "verification.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report), 2)
        for entry in report:
            self.assertLess(entry["bytes"], 5)

    def test_duration_mismatch_is_rejected(self):
        # Split children report half the parent duration each only when the
        # parent was 100s; shrink the source duration so the total diverges.
        self.media.register(self.source / "session.mpd", 500.0)
        with self.assertRaises(RuntimeError) as raised:
            self.run_main(limit=5)
        self.assertIn("Duration mismatch", str(raised.exception))

    def test_stream_mismatch_is_rejected(self):
        wrong_streams = [{"codec_type": "video", "codec_name": "hevc"}]
        self.media.register(self.source / "session.mpd", 100.0, streams=wrong_streams)
        with self.assertRaises(RuntimeError) as raised:
            self.run_main()
        self.assertIn("Stream/codec mismatch", str(raised.exception))

    def test_failed_split_retains_pending_outputs(self):
        self.media.split_children = 1  # no usable keyframe split
        with self.assertRaises(RuntimeError) as raised:
            self.run_main(limit=5)
        self.assertIn("keyframe split", str(raised.exception))
        self.assertTrue((self.output / ".pending").exists())

    def test_existing_pending_export_is_refused(self):
        (self.output / ".pending").mkdir(parents=True)
        with self.assertRaises(RuntimeError) as raised:
            self.run_main()
        self.assertIn("pending export", str(raised.exception))

    def test_insufficient_disk_space_is_refused(self):
        with patch.object(export_game.shutil, "disk_usage",
                          return_value=SimpleNamespace(free=0)):
            with self.assertRaises(RuntimeError) as raised:
                self.run_main()
        self.assertIn("free space", str(raised.exception))

    def test_destination_collision_falls_back_to_unique_name(self):
        stamp = "Portal 2_2026-07-25_10-45-00_001_of_001.mp4"
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / stamp).write_bytes(b"previous export")
        self.run_main()
        self.assertEqual(sorted(path.name for path in self.output.glob("*.mp4")),
                         [stamp, Path(stamp).stem + "_2.mp4"])

    def test_probe_failure_surfaces_ffmpeg_stderr(self):
        # Unregistered staged part -> ffprobe "fails" with its stderr message.
        self.media.probe_data.clear()
        with self.assertRaises(RuntimeError) as raised:
            self.run_main()
        self.assertIn("Invalid data found", str(raised.exception))

    def test_missing_video_stream_is_rejected(self):
        self.media.register(self.source / "session.mpd", 100.0,
                            streams=[{"codec_type": "audio", "codec_name": "aac"}])
        with self.assertRaises(RuntimeError) as raised:
            self.run_main()
        self.assertIn("Missing video", str(raised.exception))

    def test_no_recordings_for_appid_is_rejected(self):
        with self.assertRaises(RuntimeError) as raised:
            self.run_main(recording=["--recording", "bg_620_20990101_000000"])
        self.assertIn("No recordings found", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
