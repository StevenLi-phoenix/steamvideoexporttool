from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from steam_exporter.media import (
    ConversionError,
    _GAME_NAME_CACHE,
    _escape_concat_path,
    _fetch_steam_game_name,
    _steam_roots,
    _write_concat_list,
    _parse_appid,
    _parse_steam_name,
    extract_preview_frames,
    find_executable,
    recording_timestamp,
    resolve_game_name,
    resource_path,
    safe_name,
    unique_path,
)


class NamingTests(unittest.TestCase):
    def test_safe_name_removes_windows_invalid_characters(self):
        self.assertEqual(safe_name('A:game/recording?*'), 'A_game_recording__')
        self.assertEqual(safe_name(' . '), 'SteamRecording')


class SteamMetadataTests(unittest.TestCase):
    def test_parsers_extract_app_id_and_manifest_name(self):
        self.assertEqual(_parse_appid(r'D:\Videos\Steam\video\bg_620_20260725_104500'), '620')
        self.assertIsNone(_parse_appid('no-app-id-here'))
        self.assertEqual(_parse_steam_name('"AppState" { "name" "Portal 2" }'), 'Portal 2')

    def test_parse_steam_name_unescapes_valve_strings_without_corrupting_utf8(self):
        self.assertEqual(_parse_steam_name('"name" "反恐精英2"'), '反恐精英2')
        self.assertEqual(_parse_steam_name(r'"name" "Counter\"Strike"'), 'Counter"Strike')
        self.assertEqual(_parse_steam_name(r'"name" "Left 4\\Dead 2\n"'), 'Left 4\\Dead 2\n')
        self.assertIsNone(_parse_steam_name('no name here'))

    def test_local_json_game_name_takes_priority_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            recording = Path(temporary) / 'bg_620_20260725_104500'
            recording.mkdir()
            (recording / 'metadata.json').write_text('{"gameName": "Portal 2"}', encoding='utf-8')
            with patch('steam_exporter.media._fetch_steam_game_name') as fetch:
                self.assertEqual(resolve_game_name(recording), 'Portal 2')
            fetch.assert_not_called()

    def test_fetch_steam_game_name_caches_success_and_handles_network_error(self):
        class Response:
            def read(self):
                return b'{"620": {"data": {"name": "Portal 2"}}}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        _GAME_NAME_CACHE.clear()
        with patch('steam_exporter.media.urllib.request.urlopen', return_value=Response()) as request:
            self.assertEqual(_fetch_steam_game_name('620'), 'Portal 2')
            self.assertEqual(_fetch_steam_game_name('620'), 'Portal 2')
        request.assert_called_once()
        _GAME_NAME_CACHE.clear()
        with patch('steam_exporter.media.urllib.request.urlopen', side_effect=OSError):
            self.assertIsNone(_fetch_steam_game_name('missing'))

    def test_local_manifest_and_online_fallback_are_used_when_metadata_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            recording = Path(temporary) / 'bg_620_20260725_104500'
            recording.mkdir()
            manifest = recording / 'appmanifest_620.acf'
            manifest.write_text('"AppState" { "name" "Portal 2" }', encoding='utf-8')
            self.assertEqual(resolve_game_name(recording), 'Portal 2')
            manifest.unlink()
            with patch('steam_exporter.media._steam_roots', return_value=[]), patch('steam_exporter.media._fetch_steam_game_name', return_value='Online Portal'):
                self.assertEqual(resolve_game_name(recording), 'Online Portal')

    def test_steam_roots_reads_libraryfolders_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'Programs'
            steam = root / 'Steam'
            (steam / 'steamapps').mkdir(parents=True)
            library = Path(temporary) / 'Library'
            escaped = str(library).replace('\\', '\\\\')
            (steam / 'steamapps' / 'libraryfolders.vdf').write_text(f'"path" "{escaped}"', encoding='utf-8')
            environment = {'PROGRAMFILES(X86)': str(root), 'PROGRAMFILES': '', 'LOCALAPPDATA': ''}
            with patch.dict('steam_exporter.media.os.environ', environment, clear=True):
                roots = _steam_roots()
            self.assertEqual(roots, [steam, library])


class ProcessHelperTests(unittest.TestCase):
    def test_concat_list_helper_escapes_paths(self):
        self.assertIn("'\\''", _escape_concat_path(Path("a'b.m4s")))
        with tempfile.TemporaryDirectory() as temporary:
            media = Path(temporary) / 'chunk-stream0-00001.m4s'
            media.write_bytes(b'video')
            listing = _write_concat_list([media])
            try:
                self.assertIn("file '", listing.read_text(encoding='utf-8'))
            finally:
                listing.unlink(missing_ok=True)

    def test_recording_timestamp_uses_steam_folder_date(self):
        timestamp = recording_timestamp(Path('bg_620_20260725_104500'))
        self.assertEqual(timestamp, datetime(2026, 7, 25, 10, 45, 0))

    def test_invalid_timestamp_uses_current_time_and_unique_path_adds_suffix(self):
        before = datetime.now()
        timestamp = recording_timestamp(Path('not-a-recording'))
        self.assertGreaterEqual(timestamp, before)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'clip.mp4'
            path.touch()
            self.assertEqual(unique_path(path).name, 'clip_2.mp4')

    def test_extract_preview_frames_requires_ffmpeg_and_ffprobe(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination_dir = Path(temporary) / 'previews'
            with patch('steam_exporter.media.find_executable', return_value=None):
                with self.assertRaises(ConversionError):
                    extract_preview_frames([], destination_dir, Path('session.mpd'))

    def test_extract_preview_frames_creates_four_thumbnails_at_even_offsets(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination_dir = Path(temporary) / 'previews'
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                if command[0] == 'ffprobe.exe':
                    return SimpleNamespace(stdout='40.0\n')
                for index in range(1, 5):
                    (destination_dir / f'frame_{index}.jpg').write_bytes(b'x')
                return SimpleNamespace(returncode=0)

            with patch('steam_exporter.media.find_executable', side_effect=lambda name, ffmpeg_path=None: Path(f'{name}.exe')), \
                 patch('steam_exporter.media.subprocess.run', side_effect=fake_run):
                outputs = extract_preview_frames([], destination_dir, Path('session.mpd'))
            self.assertEqual(len(outputs), 4)
            self.assertTrue(all(path.exists() for path in outputs))
            offsets = [float(calls[1][index + 1]) for index, token in enumerate(calls[1]) if token == '-ss']
            self.assertEqual(offsets, [0.0, 10.0, 20.0, 30.0])

    def test_extract_preview_frames_raises_when_ffmpeg_produces_no_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination_dir = Path(temporary) / 'previews'

            def fake_run(command, **kwargs):
                if command[0] == 'ffprobe.exe':
                    return SimpleNamespace(stdout='10.0')
                return SimpleNamespace(returncode=1, stderr='Invalid data found')

            with patch('steam_exporter.media.find_executable', side_effect=lambda name, ffmpeg_path=None: Path(f'{name}.exe')), \
                 patch('steam_exporter.media.subprocess.run', side_effect=fake_run):
                with self.assertRaises(ConversionError) as raised:
                    extract_preview_frames([], destination_dir, Path('session.mpd'))
            self.assertIn('Invalid data found', str(raised.exception))

    def test_extract_preview_frames_surfaces_stderr_when_duration_is_unreadable(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination_dir = Path(temporary) / 'previews'
            destination_dir.mkdir()
            (destination_dir / 'frame_1.jpg').write_bytes(b'stale')

            def fake_run(command, **kwargs):
                return SimpleNamespace(stdout='N/A', stderr='moov atom not found', returncode=1)

            with patch('steam_exporter.media.find_executable', side_effect=lambda name, ffmpeg_path=None: Path(f'{name}.exe')), \
                 patch('steam_exporter.media.subprocess.run', side_effect=fake_run):
                with self.assertRaises(ConversionError) as raised:
                    extract_preview_frames([], destination_dir, Path('session.mpd'))
            self.assertIn('moov atom not found', str(raised.exception))
            self.assertFalse((destination_dir / 'frame_1.jpg').exists())

    def test_extract_preview_frames_reports_timeouts_and_cleans_partial_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination_dir = Path(temporary) / 'previews'

            def fake_run(command, **kwargs):
                if command[0] == 'ffprobe.exe':
                    return SimpleNamespace(stdout='40.0')
                raise subprocess.TimeoutExpired(cmd='ffmpeg', timeout=120)

            with patch('steam_exporter.media.find_executable', side_effect=lambda name, ffmpeg_path=None: Path(f'{name}.exe')), \
                 patch('steam_exporter.media.subprocess.run', side_effect=fake_run):
                with self.assertRaises(ConversionError) as raised:
                    extract_preview_frames([], destination_dir, Path('session.mpd'))
            self.assertIn('timed out', str(raised.exception))
            self.assertFalse(any(destination_dir.glob('frame_*.jpg')))

    def test_resource_path_resolves_relative_to_project_root_when_not_frozen(self):
        expected = Path(__file__).resolve().parent.parent / 'assets' / 'app-icon.ico'
        self.assertEqual(resource_path('assets', 'app-icon.ico'), expected)

    def test_find_executable_prefers_bundled_sibling(self):
        with tempfile.TemporaryDirectory() as temporary:
            ffmpeg = Path(temporary) / 'ffmpeg.exe'
            ffprobe = Path(temporary) / 'ffprobe.exe'
            ffmpeg.touch()
            ffprobe.touch()
            self.assertEqual(find_executable('ffprobe', ffmpeg), ffprobe)


if __name__ == '__main__':
    unittest.main()
