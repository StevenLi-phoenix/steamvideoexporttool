from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from .models import ConversionError, PreflightResult, RecordingInput


DEFAULT_PATTERN = "{game}_{date}_{time}_part{index}.{ext}"


def format_bytes(value: int | float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{amount:.1f} TB"


def safe_name(value: str, fallback: str = "SteamRecording") -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value).strip(" .")
    return value or fallback


def _ffmpeg_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("FFMPEG_PATH")
    if configured:
        candidates.append(Path(configured))
    app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    candidates.extend((app_dir / "ffmpeg.exe", app_dir / "bin" / "ffmpeg.exe"))
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(Path(found))
    return candidates


def find_executable(name: str, ffmpeg_path: Path | None = None) -> Path | None:
    if name == "ffmpeg":
        for candidate in _ffmpeg_candidates():
            if candidate.exists():
                return candidate
        return None
    if ffmpeg_path:
        sibling = ffmpeg_path.with_name(name + ffmpeg_path.suffix)
        if sibling.exists():
            return sibling
    found = shutil.which(name)
    return Path(found) if found else None


def _parse_appid(text: str) -> str | None:
    matches = re.findall(r"(?:^|[\\/_-])(\d{3,8})(?:$|[\\/_-])", text)
    return matches[-1] if matches else None


def _parse_steam_name(text: str) -> str | None:
    match = re.search(r'"name"\s+"((?:[^"\\]|\\.)*)"', text, re.IGNORECASE)
    if not match:
        return None
    return bytes(match.group(1), "utf-8").decode("unicode_escape", errors="ignore")


def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    for hive_name, subkey in (
        ("HKEY_CURRENT_USER", r"Software\Valve\Steam"),
        ("HKEY_LOCAL_MACHINE", r"SOFTWARE\WOW6432Node\Valve\Steam"),
    ):
        try:
            import winreg

            with winreg.OpenKey(getattr(winreg, hive_name), subkey) as handle:
                value, _ = winreg.QueryValueEx(handle, "SteamPath")
                roots.append(Path(value))
        except (OSError, ImportError):
            pass
    libraries = list(roots)
    for root in libraries:
        library_file = root / "steamapps" / "libraryfolders.vdf"
        try:
            text = library_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for value in re.findall(r'"path"\s+"((?:[^"\\]|\\.)*)"', text, re.IGNORECASE):
            libraries.append(Path(value.replace("\\\\", "\\")))
    return list(dict.fromkeys(libraries))


def resolve_game_name(source: Path) -> str:
    metadata_files = list(source.glob("*.json")) + list(source.glob("*.JSON"))
    if source.parent != source:
        metadata_files += list(source.parent.glob("*.json")) + list(source.parent.glob("*.JSON"))
    for metadata in metadata_files[:50]:
        try:
            data = json.loads(metadata.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, UnicodeError):
            continue
        if isinstance(data, dict):
            for key in ("gameName", "game_name", "gameTitle", "title", "name"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return safe_name(value)

    appid = _parse_appid(str(source))
    if appid:
        for root in [source, *_steam_roots()]:
            candidates = [root / f"appmanifest_{appid}.acf", root / "steamapps" / f"appmanifest_{appid}.acf"]
            for manifest in candidates:
                try:
                    name = _parse_steam_name(manifest.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    continue
                if name:
                    return safe_name(name)
    else:
        try:
            local_manifests = list(source.glob("*.acf"))
        except OSError:
            local_manifests = []
        for manifest in local_manifests:
            try:
                name = _parse_steam_name(manifest.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            if name:
                return safe_name(name)

    for part in reversed(source.parts):
        if part.lower() not in {"gamerecordings", "recordings", "video", "videos"} and not part.isdigit():
            return safe_name(part)
    return "SteamRecording"


def discover_m4s(source: Path) -> list[Path]:
    files: list[Path] = []
    for folder, _, names in os.walk(source):
        files.extend(Path(folder) / name for name in names if name.lower().endswith(".m4s"))
    return files


def discover_recordings(source: Path) -> list[tuple[Path, list[Path]]]:
    """Group chunks by Steam's bg_<appid>_<timestamp> recording directory."""
    groups: dict[Path, list[Path]] = {}
    recording_name = re.compile(r"^bg_\d+_\d{8}_\d{6}$", re.IGNORECASE)
    for path in discover_m4s(source):
        folder = next((parent for parent in (path.parent, *path.parents) if recording_name.match(parent.name)), path.parent)
        groups.setdefault(folder, []).append(path)
    return sorted(
        ((folder, sorted(files, key=lambda path: path.name.lower())) for folder, files in groups.items()),
        key=lambda item: str(item[0]).lower(),
    )


def recording_timestamp(folder: Path) -> datetime:
    match = re.match(r"^bg_\d+_(\d{8})_(\d{6})$", folder.name, re.IGNORECASE)
    if match:
        try:
            return datetime.strptime("_".join(match.groups()), "%Y%m%d_%H%M%S")
        except ValueError:
            pass
    return datetime.now()


def _escape_concat_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def _write_concat_list(files: list[Path]) -> Path:
    handle, name = tempfile.mkstemp(prefix="steam-video-", suffix=".txt", text=True)
    os.close(handle)
    list_path = Path(name)
    list_path.write_text("\n".join(f"file '{_escape_concat_path(path)}'" for path in files), encoding="utf-8")
    return list_path


def _read_duration(ffprobe: Path | None, concat_list: Path) -> float | None:
    if not ffprobe:
        return None
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-show_entries", "format=duration", "-of", "default=nk=1:nw=1"],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return None


def unique_path(path: Path) -> Path:
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ConversionError(f"Could not choose a free output name for {path.name}.")


def render_filename(pattern: str, game: str, source: str, date: datetime, index: int, extension: str, count: int) -> str:
    values = {
        "game": safe_name(game), "source": safe_name(source),
        "date": date.strftime("%Y-%m-%d"), "time": date.strftime("%H-%M-%S"),
        "index": f"{index:03d}", "ext": extension,
    }
    try:
        rendered = pattern.format(**values)
    except (KeyError, ValueError):
        rendered = DEFAULT_PATTERN.format(**values)
    rendered = safe_name(rendered)
    if not rendered.lower().endswith("." + extension):
        rendered += "." + extension
    if count > 1 and "{index}" not in pattern:
        rendered = f"{Path(rendered).stem}_part{index:03d}{Path(rendered).suffix}"
    return rendered


class SteamExporter:
    """Application service for discovery, preflight, and lossless remuxing."""

    def __init__(self, log, progress):
        self.log = log
        self.progress = progress

    def preflight(self, source_text: str, output_text: str) -> PreflightResult:
        errors: list[str] = []
        warnings: list[str] = []
        source = Path(source_text).expanduser()
        output = Path(output_text).expanduser()
        grouped = discover_recordings(source) if source.is_dir() else []
        files = [path for _, group in grouped for path in group]
        ffmpeg = find_executable("ffmpeg")
        ffprobe = find_executable("ffprobe", ffmpeg)
        if not source.is_dir():
            errors.append("The input folder does not exist or is not a folder.")
        if not files:
            errors.append("No .m4s files were found below the input folder.")
        if not ffmpeg:
            errors.append("FFmpeg was not found. Put ffmpeg.exe beside the app or add it to PATH.")
        if not output.exists():
            try:
                output.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                errors.append(f"The output folder could not be created: {exc}")
        if output.exists() and not os.access(output, os.W_OK):
            errors.append("The output folder is not writable.")
        total = sum(path.stat().st_size for path in files) if files else 0
        free = shutil.disk_usage(output).free if output.exists() else 0
        required = max(512 * 1024**2, int(total * 1.25))
        if output.exists() and free < required:
            errors.append(f"Not enough free space: {format_bytes(free)} available, about {format_bytes(required)} needed.")
        elif output.exists() and free < required * 2:
            warnings.append(f"Free space is tight ({format_bytes(free)}). A large conversion may need more headroom.")
        if ffmpeg and not ffprobe:
            warnings.append("ffprobe was not found; duration will be estimated and segment sizing may be less precise.")
        recordings = [RecordingInput(folder, group, resolve_game_name(folder)) for folder, group in grouped]
        game_name = recordings[0].game_name if recordings else "SteamRecording"
        return PreflightResult(errors, warnings, files, game_name, ffmpeg, ffprobe, total, free, recordings)

    def convert(self, result: PreflightResult, output_text: str, output_format: str, limit_bytes: int, pattern: str):
        if not result.ok or not result.ffmpeg:
            raise ConversionError("Preflight checks did not pass.")
        output = Path(output_text).expanduser()
        output.mkdir(parents=True, exist_ok=True)
        staging = output / f".steam-export-{uuid.uuid4().hex}"
        staging.mkdir()
        concat_list: Path | None = None
        try:
            self.log(f"Recordings: {len(result.recordings)} | Input: {len(result.files)} .m4s file(s), {format_bytes(result.total_bytes)}")
            self.log(f"Target: {output_format.upper()}, lossless stream copy, max {format_bytes(limit_bytes)} per segment")
            extension = output_format.lower()
            for recording_number, recording in enumerate(result.recordings, start=1):
                concat_list = _write_concat_list(recording.files)
                duration = _read_duration(result.ffprobe, concat_list)
                if not duration or duration <= 0:
                    duration = max(1800.0, sum(path.stat().st_size for path in recording.files) * 8 / 8_000_000)
                estimated_bps = max(1_500_000, sum(path.stat().st_size for path in recording.files) * 8 / duration)
                segment_seconds = max(30.0, (limit_bytes * 0.88 * 8) / estimated_bps)
                self.log(f"Recording {recording_number}/{len(result.recordings)}: {recording.folder.name} | game: {recording.game_name}")
                segments: list[Path] = []
                for attempt in range(3):
                    for old in staging.iterdir():
                        if old.is_file():
                            old.unlink()
                    self.log(f"Remux pass {attempt + 1}/3 (about {segment_seconds / 60:.0f} minutes per segment)...")
                    command = [str(result.ffmpeg), "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                               "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero", "-f", "segment",
                               "-segment_time", f"{segment_seconds:.3f}", "-reset_timestamps", "1"]
                    if extension in {"mp4", "mov"}:
                        command.extend(["-segment_format", extension, "-segment_format_options", "movflags=+faststart"])
                    else:
                        command.extend(["-segment_format", "flv"])
                    command.append(str(staging / f"segment_%04d.{extension}"))
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    assert process.stdout
                    for line in process.stdout:
                        line = line.strip()
                        if line and ("frame=" in line or "time=" in line or "Error" in line):
                            self.log(line[-180:])
                    if process.wait() != 0:
                        raise ConversionError("FFmpeg could not remux the selected .m4s files. Check the log for details.")
                    segments = sorted(staging.glob(f"*.{extension}"))
                    if not segments:
                        raise ConversionError("FFmpeg finished without producing an output video.")
                    largest = max(path.stat().st_size for path in segments)
                    if largest <= limit_bytes * 0.98 or attempt == 2:
                        break
                    segment_seconds *= 0.72
                    self.log(f"Largest segment was {format_bytes(largest)}; shortening boundaries and retrying.")

                date = recording_timestamp(recording.folder)
                for index, segment in enumerate(segments, start=1):
                    filename = render_filename(pattern, recording.game_name, recording.folder.name, date, index, extension, len(segments))
                    destination = output / filename
                    if destination.exists():
                        destination = unique_path(destination)
                    shutil.move(str(segment), str(destination))
                    self.log(f"Created {destination.name} ({format_bytes(destination.stat().st_size)})")
                    self.progress(((recording_number - 1) + index / len(segments)) / len(result.recordings))
                concat_list.unlink(missing_ok=True)
                concat_list = None
            self.log(f"Done: {len(result.recordings)} recording(s) written to {output}")
        finally:
            try:
                if concat_list:
                    concat_list.unlink(missing_ok=True)
            except OSError:
                pass
            shutil.rmtree(staging, ignore_errors=True)
