import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from steam_exporter import media, platform_paths


class MacPathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        home_patch = patch.object(Path, "home", return_value=self.home)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        platform_patch = patch("sys.platform", "darwin")
        platform_patch.start()
        self.addCleanup(platform_patch.stop)

    def test_mac_user_directories(self):
        self.assertEqual(platform_paths.videos_path(), self.home / "Movies")
        self.assertEqual(platform_paths.settings_dir(), self.home / "Library/Application Support/SteamQuickExport")

    def test_discovers_recordings_under_steam_account(self):
        video = self.home / "Library/Application Support/Steam/userdata/123/gamerecordings/video"
        video.mkdir(parents=True)
        self.assertEqual(platform_paths.default_recordings_path(), video)

    def test_mac_recordings_fallback(self):
        self.assertEqual(platform_paths.default_recordings_path(), self.home / "Movies/Steam/video")

    def test_mac_steam_root_and_external_library(self):
        steam = self.home / "Library/Application Support/Steam"
        (steam / "steamapps").mkdir(parents=True)
        external = self.home / "External Library"
        escaped = str(external).replace("\\", "\\\\")
        (steam / "steamapps/libraryfolders.vdf").write_text(f'"path" "{escaped}"', encoding="utf-8")
        with patch.object(media, "_STEAM_ROOTS_CACHE", None):
            self.assertEqual(media._steam_roots(), [steam, external])

    def test_frozen_resources_and_native_ffmpeg(self):
        binary = self.home / "ffmpeg"
        binary.touch()
        with (
            patch("sys.frozen", True, create=True),
            patch("sys._MEIPASS", str(self.home), create=True),
            patch.dict(os.environ, {}, clear=True),
            patch.object(media.shutil, "which", return_value=None),
        ):
            self.assertEqual(media.resource_path("assets", "app-icon.ico"), self.home / "assets/app-icon.ico")
            self.assertEqual(media.find_executable("ffmpeg"), binary)

    def test_finder_launch_searches_homebrew_without_path(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(media.shutil, "which", return_value=None):
            self.assertIn(Path("/opt/homebrew/bin/ffmpeg"), media._ffmpeg_candidates())
            self.assertIn(Path("/usr/local/bin/ffmpeg"), media._ffmpeg_candidates())

    def test_full_homebrew_ffmpeg_precedes_minimal_path_binary(self):
        full = Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
        with patch.dict(os.environ, {}, clear=True), patch.object(media.shutil, "which", return_value="/opt/homebrew/bin/ffmpeg"):
            candidates = media._ffmpeg_candidates()
            self.assertLess(candidates.index(full), candidates.index(Path("/opt/homebrew/bin/ffmpeg")))

    def test_explicit_ffmpeg_override_takes_precedence(self):
        with patch.dict(os.environ, {"FFMPEG_PATH": "/custom/ffmpeg"}):
            self.assertEqual(media._ffmpeg_candidates()[0], Path("/custom/ffmpeg"))


class CancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QCoreApplication

        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        from steam_exporter.export_client import ExportClient

        self.client = ExportClient()
        self.client.process = Mock(pid=12345)
        self.client.timer = Mock()
        self.client.receiver = Mock()
        kill_signal = patch.object(signal, "SIGKILL", 9, create=True)
        kill_signal.start()
        self.addCleanup(kill_signal.stop)

    def test_mac_cancel_waits_for_worker_session_then_kills_group(self):
        with patch("sys.platform", "darwin"), patch("os.killpg", create=True) as kill:
            self.client.cancel()
            kill.assert_not_called()
            self.client.receiver.poll.side_effect = [True, False]
            self.client.receiver.recv.return_value = ("ready", None)
            self.client.poll()
            kill.assert_called_once_with(12345, signal.SIGKILL)

    def test_cancel_finished_group_is_harmless(self):
        self.client.backend_ready = True
        with patch("sys.platform", "darwin"), patch("os.killpg", side_effect=ProcessLookupError, create=True):
            self.client.cancel()
        self.assertTrue(self.client.cancel_requested)

    def test_repeated_cancel_signals_worker_only_once(self):
        self.client.backend_ready = True
        with patch("sys.platform", "darwin"), patch("os.killpg", create=True) as kill:
            self.client.cancel()
            self.client.cancel()
        kill.assert_called_once_with(12345, signal.SIGKILL)

    def test_windows_keeps_process_tree_cancellation(self):
        with (
            patch("sys.platform", "win32"),
            patch("steam_exporter.export_client.subprocess.run") as run,
            patch("subprocess.CREATE_NO_WINDOW", 0x08000000, create=True),
        ):
            self.client.cancel()
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "12345", "/T", "/F"])

    def test_backend_announces_session_before_export(self):
        from steam_exporter.export_backend import run_export

        sender = Mock()
        events = []
        sender.send.side_effect = lambda message: events.append(message[0])
        with (
            tempfile.TemporaryDirectory() as temp,
            patch("sys.platform", "darwin"),
            patch("os.setsid", side_effect=lambda: events.append("session"), create=True),
            patch("steam_exporter.export_backend.export_game", side_effect=lambda *a, **k: events.append("export")),
        ):
            run_export(["--output", str(Path(temp) / "out")], sender)
        self.assertEqual(events[:2], ["session", "ready"])
        self.assertLess(events.index("ready"), events.index("export"))
        sender.close.assert_called_once()
