"""Safety-gate tests for the destructive scripts/export_library_and_prune.py."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.export_library_and_prune as prune
from tests.test_export_game import FakeMedia, STREAMS


def make_recording(root: Path, name="bg_620_20260725_104500") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "chunk-stream0-00001.m4s").write_bytes(b"chunk")
    (folder / "session.mpd").write_bytes(b"mpd")
    return folder


class PruneScriptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.media = FakeMedia()
        self.patchers = [
            patch.object(prune.subprocess, "run", side_effect=self.media.run),
            patch.object(prune, "find_executable", side_effect=lambda name, ffmpeg_path=None: Path(f"{name}.exe")),
            patch.object(prune, "LIMIT", 1000),
            patch.object(prune, "resolve_game_name", return_value="Portal 2"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_main(self, *extra):
        prune.main(["--source", str(self.root), *extra])

    def test_refuses_to_delete_sources_without_explicit_flag(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_main()
        self.assertIn("--delete-sources", str(raised.exception))

    def test_missing_video_root_is_reported(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_main("--delete-sources")
        self.assertIn("video", str(raised.exception))

    def test_refuses_when_no_recordings_exist(self):
        (self.root / "video").mkdir()
        with self.assertRaises(SystemExit) as raised:
            self.run_main("--delete-sources")
        self.assertIn("No Steam recording folders", str(raised.exception))

    def test_exports_verifies_then_deletes_each_source(self):
        video_root = self.root / "video"
        recording = make_recording(video_root, "bg_440_20260726_112233")
        self.media.register(recording / "session.mpd", 100.0, streams=STREAMS)

        self.run_main("--delete-sources")

        exports = list((self.root / "exports").glob("*.mp4"))
        self.assertEqual(len(exports), 1)
        report = json.loads((self.root / "exports" / f"verification-{recording.name}.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(report[0]["file"]), exports[0])
        self.assertFalse(recording.exists())  # source deleted after verification
        self.assertFalse(video_root.exists())  # emptied video root removed

    def test_failed_export_stops_before_any_deletion(self):
        video_root = self.root / "video"
        recording = make_recording(video_root, "bg_440_20260726_112233")
        self.media.register(recording / "session.mpd", 100.0, streams=STREAMS)
        # bg_620 sorts second; its manifest never registers with the fake
        # ffprobe, so its export fails after the first recording succeeded.
        second = make_recording(video_root, "bg_620_20260725_104500")

        with self.assertRaises(RuntimeError):
            self.run_main("--delete-sources")

        self.assertTrue(second.exists())  # current source retained on failure
        self.assertFalse(recording.exists())  # earlier recording already migrated
        self.assertTrue(video_root.exists())  # root kept while sources remain


if __name__ == "__main__":
    unittest.main()
