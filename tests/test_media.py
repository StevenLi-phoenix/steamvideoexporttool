from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from steam_exporter.media import (
    DEFAULT_PATTERN,
    ConversionError,
    SteamExporter,
    _GAME_NAME_CACHE,
    _escape_concat_path,
    _fetch_steam_game_name,
    _read_duration,
    _steam_roots,
    _write_concat_list,
    _parse_appid,
    _parse_steam_name,
    discover_m4s,
    discover_recordings,
    extract_first_frame,
    find_executable,
    format_bytes,
    recording_timestamp,
    render_filename,
    resolve_game_name,
    safe_name,
    unique_path,
)
from steam_exporter.models import PreflightResult, RecordingInput


class NamingTests(unittest.TestCase):
    def test_format_bytes_uses_human_readable_units(self):
        self.assertEqual(format_bytes(512), '512 B')
        self.assertEqual(format_bytes(1024), '1.0 KB')
        self.assertEqual(format_bytes(1024**2), '1.0 MB')
    def test_safe_name_removes_windows_invalid_characters(self):
        self.assertEqual(safe_name('A:game/recording?*'), 'A_game_recording__')
        self.assertEqual(safe_name(' . '), 'SteamRecording')

    def test_render_filename_substitutes_tokens_and_extension(self):
        rendered = render_filename(
            '{game}_{source}_{date}_{time}_{index}.{ext}',
            'Portal 2',
            'bg_620_20260725_104500',
            datetime(2026, 7, 25, 10, 45, 0),
            7,
            'mp4',
            1,
        )
        self.assertEqual(rendered, 'Portal 2_bg_620_20260725_104500_2026-07-25_10-45-00_007.mp4')

    def test_render_filename_adds_part_when_pattern_has_no_index(self):
        rendered = render_filename('{game}.{ext}', 'Portal 2', 'recording', datetime.now(), 2, 'mov', 3)
        self.assertEqual(rendered, 'Portal 2_part002.mov')

    def test_bad_pattern_falls_back_to_default_pattern(self):
        rendered = render_filename('{unknown}', 'Portal 2', 'recording', datetime(2026, 1, 2, 3, 4, 5), 1, 'mp4', 1)
        self.assertEqual(rendered, 'Portal 2_2026-01-02_03-04-05_part001.mp4')
        self.assertIn('{game}', DEFAULT_PATTERN)


class SteamMetadataTests(unittest.TestCase):
    def test_parsers_extract_app_id_and_manifest_name(self):
        self.assertEqual(_parse_appid(r'D:\Videos\Steam\video\bg_620_20260725_104500'), '620')
        self.assertIsNone(_parse_appid('no-app-id-here'))
        self.assertEqual(_parse_steam_name('"AppState" { "name" "Portal 2" }'), 'Portal 2')

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
            (steam / 'steamapps' / 'libraryfolders.vdf').write_text(f'"path" "{library}"', encoding='utf-8')
            environment = {'PROGRAMFILES(X86)': str(root), 'PROGRAMFILES': '', 'LOCALAPPDATA': ''}
            with patch.dict('steam_exporter.media.os.environ', environment, clear=True):
                roots = _steam_roots()
            self.assertEqual(roots, [steam, library])


class DiscoveryTests(unittest.TestCase):
    def test_discovery_groups_chunks_by_recording_folder_and_sorts_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / 'video' / 'bg_620_20260725_104500'
            second = root / 'video' / 'bg_440_20260726_112233'
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            for name in ('chunk-stream0-00002.m4s', 'chunk-stream0-00001.m4s'):
                (first / name).write_bytes(b'chunk')
            (second / 'chunk-stream0-00001.m4s').write_bytes(b'chunk')

            recordings = discover_recordings(root)

            self.assertEqual([folder.name for folder, _ in recordings], [second.name, first.name])
            self.assertEqual([file.name for file in recordings[1][1]], ['chunk-stream0-00001.m4s', 'chunk-stream0-00002.m4s'])

    def test_discovery_ignores_dash_init_segments_and_helper_paths_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / 'part.m4s'
            init = root / 'init-stream0.m4s'
            media.write_bytes(b'video')
            init.write_bytes(b'init')
            self.assertEqual(discover_m4s(root), [media])
            self.assertIn("'\\''", _escape_concat_path(Path("a'b.m4s")))
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


class ProcessHelperTests(unittest.TestCase):
    def test_read_duration_handles_valid_and_invalid_ffprobe_output(self):
        result = SimpleNamespace(stdout='42.5\n')
        with patch('steam_exporter.media.subprocess.run', return_value=result) as run:
            self.assertEqual(_read_duration(Path('ffprobe.exe'), Path('chunks.txt')), 42.5)
        self.assertIn('-f', run.call_args.args[0])
        with patch('steam_exporter.media.subprocess.run', return_value=SimpleNamespace(stdout='not-a-number')):
            self.assertIsNone(_read_duration(Path('ffprobe.exe'), manifest=Path('session.mpd')))
        self.assertIsNone(_read_duration(None, Path('chunks.txt')))

    def test_extract_preview_reports_missing_ffmpeg_and_cleans_failed_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'preview.jpg'
            with patch('steam_exporter.media.find_executable', return_value=None):
                with self.assertRaises(ConversionError):
                    extract_first_frame([], destination)
            destination.write_bytes(b'partial')
            with patch('steam_exporter.media.find_executable', return_value=Path('ffmpeg.exe')), patch('steam_exporter.media.subprocess.run', return_value=SimpleNamespace(returncode=1)):
                with self.assertRaises(ConversionError):
                    extract_first_frame([], destination, Path('session.mpd'))
            self.assertFalse(destination.exists())

    def test_find_executable_prefers_bundled_sibling(self):
        with tempfile.TemporaryDirectory() as temporary:
            ffmpeg = Path(temporary) / 'ffmpeg.exe'
            ffprobe = Path(temporary) / 'ffprobe.exe'
            ffmpeg.touch()
            ffprobe.touch()
            self.assertEqual(find_executable('ffprobe', ffmpeg), ffprobe)


class ConversionTests(unittest.TestCase):
    def test_convert_stream_copies_a_recording_into_the_output_folder(self):
        class Process:
            stdout = ['frame=  1 time=00:00:00.01\n']

            def wait(self):
                return 0

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'bg_620_20260725_104500'
            source.mkdir()
            chunk = source / 'chunk-stream0-00001.m4s'
            chunk.write_bytes(b'video-data')
            output = root / 'out'
            output.mkdir()
            recording = RecordingInput(source, [chunk], 'Portal 2')
            result = PreflightResult([], [], [chunk], 'Portal 2', Path('ffmpeg.exe'), Path('ffprobe.exe'), chunk.stat().st_size, 10 * 1024**3, [recording])
            logs, progress = [], []

            def fake_popen(command, **_):
                Path(command[-1].replace('%04d', '0000')).write_bytes(b'remuxed')
                return Process()

            with patch('steam_exporter.media._read_duration', return_value=10.0), patch('steam_exporter.media.subprocess.Popen', side_effect=fake_popen):
                SteamExporter(logs.append, progress.append).convert(result, str(output), 'mp4', 1024**3, '{game}_{index}.{ext}')

            self.assertEqual((output / 'Portal 2_001.mp4').read_bytes(), b'remuxed')
            self.assertEqual(progress, [1.0])
            self.assertTrue(any('lossless stream copy' in message for message in logs))


class PreflightTests(unittest.TestCase):
    def test_preflight_reports_missing_source_and_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'out'
            exporter = SteamExporter(lambda _: None, lambda _: None)
            with patch('steam_exporter.media.find_executable', return_value=None):
                result = exporter.preflight(str(Path(temporary) / 'missing'), str(output))

            self.assertFalse(result.ok)
            self.assertIn('The input folder does not exist or is not a folder.', result.errors)
            self.assertIn('No .m4s files were found below the input folder.', result.errors)
            self.assertIn('FFmpeg was not found. Put ffmpeg.exe beside the app or add it to PATH.', result.errors)

    def test_preflight_accepts_a_valid_recording(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recording = root / 'bg_620_20260725_104500'
            recording.mkdir()
            chunk = recording / 'chunk-stream0-00001.m4s'
            chunk.write_bytes(b'12345678')
            output = root / 'out'
            ffmpeg = root / 'ffmpeg.exe'
            ffprobe = root / 'ffprobe.exe'
            ffmpeg.touch()
            ffprobe.touch()
            exporter = SteamExporter(lambda _: None, lambda _: None)

            with (
                patch('steam_exporter.media.find_executable', side_effect=[ffmpeg, ffprobe]),
                patch('steam_exporter.media.resolve_game_name', return_value='Portal 2'),
                patch('steam_exporter.media.shutil.disk_usage', return_value=SimpleNamespace(free=10 * 1024**3)),
            ):
                result = exporter.preflight(str(root), str(output))

            self.assertTrue(result.ok)
            self.assertEqual(result.game_name, 'Portal 2')
            self.assertEqual(result.total_bytes, 8)
            self.assertEqual(len(result.recordings), 1)


if __name__ == '__main__':
    unittest.main()
