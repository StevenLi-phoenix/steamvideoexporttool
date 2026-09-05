import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from steam_exporter.library import scan_library


class LibraryTests(unittest.TestCase):
    def test_cache_changes_deletion_and_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "bg_2950790_20260824_191110"
            folder.mkdir()
            (folder / "session.mpd").write_text("manifest")
            (folder / "a.m4s").write_bytes(b"123")
            cache = root / "cache.json"
            with patch("steam_exporter.library.resolve_game_name", return_value="Game") as lookup:
                first = scan_library(root, cache_file=cache, workers=2)
                self.assertEqual(first[0][2][0][1], 3)
                with patch("steam_exporter.library.ProcessPoolExecutor", side_effect=AssertionError("cache miss")):
                    self.assertEqual(scan_library(root, cache_file=cache), first)
                self.assertEqual(lookup.call_count, 1)
                (folder / "b.m4s").write_bytes(b"4567")
                stat = folder.stat()
                os.utime(folder, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
                self.assertEqual(scan_library(root, cache_file=cache)[0][2][0][1], 7)
                # In-place edits may not update the directory timestamp; forced scan catches them.
                (folder / "b.m4s").write_bytes(b"4")
                self.assertEqual(scan_library(root, cache_file=cache, force=True)[0][2][0][1], 4)
                (folder / "session.mpd").unlink()
                self.assertEqual(scan_library(root, cache_file=cache), [])

    def test_corrupt_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache.json"
            cache.write_text("{bad json")
            self.assertEqual(scan_library(root, cache_file=cache), [])


if __name__ == "__main__":
    unittest.main()
