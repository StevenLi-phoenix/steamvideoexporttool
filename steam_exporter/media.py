from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


class ConversionError(RuntimeError):
    """A user-facing conversion, preview, or validation failure."""


RECORDING_DIR_NAME = re.compile(r"^bg_\d+_\d{8}_\d{6}$", re.IGNORECASE)
RECORDING_DIR_APPID = re.compile(r"^bg_(\d+)_\d{8}_\d{6}$", re.IGNORECASE)
PROBE_TIMEOUT_SECONDS = 120
_GAME_NAME_CACHE: dict[str, str | None] = {}


def format_bytes(value: int | float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{int(amount)} B" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    raise AssertionError("unreachable")


def safe_name(value: str, fallback: str = "SteamRecording") -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value).strip(" .")
    return value or fallback


def resource_path(*parts: str) -> Path:
    """Locate a bundled resource (e.g. the app icon): next to the running exe
    when frozen, or under the project root when running from source."""
    app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return app_dir.joinpath(*parts)


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
    recording_match = re.search(r"(?:^|[\\/])bg_(\d{3,8})_\d{8}_\d{6}(?:$|[\\/])", text, re.IGNORECASE)
    if recording_match:
        return recording_match.group(1)
    matches = re.findall(r"(?:^|[\\/_-])(\d{3,8})(?:$|[\\/_-])", text)
    return matches[0] if matches else None


_VDF_ESCAPES = {"\\\\": "\\", '\\"': '"', "\\n": "\n", "\\r": "\r", "\\t": "\t"}


def _unescape_vdf(value: str) -> str:
    """Resolve Valve's string escapes directly. unicode_escape would mangle
    multi-byte UTF-8 characters such as Chinese game names."""
    out: list[str] = []
    index = 0
    while index < len(value):
        pair = value[index : index + 2]
        if pair in _VDF_ESCAPES:
            out.append(_VDF_ESCAPES[pair])
            index += 2
        else:
            out.append(value[index])
            index += 1
    return "".join(out)


def _parse_steam_name(text: str) -> str | None:
    match = re.search(r'"name"\s+"((?:[^"\\]|\\.)*)"', text, re.IGNORECASE)
    if not match:
        return None
    return _unescape_vdf(match.group(1))


def _fetch_steam_game_name(appid: str) -> str | None:
    if appid in _GAME_NAME_CACHE:
        return _GAME_NAME_CACHE[appid]
    try:
        query = urllib.parse.urlencode({"appids": appid, "l": "english"})
        with urllib.request.urlopen(f"https://store.steampowered.com/api/appdetails?{query}", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        value = payload.get(appid, {}).get("data", {}).get("name")
        name = safe_name(value) if isinstance(value, str) and value.strip() else None
    except (OSError, ValueError, json.JSONDecodeError):
        name = None
    _GAME_NAME_CACHE[appid] = name
    return name


def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if base:
            roots.append(Path(base) / "Steam")
    libraries = list(roots)
    for root in list(roots):
        library_file = root / "steamapps" / "libraryfolders.vdf"
        try:
            text = library_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for value in re.findall(r'"path"\s+"((?:[^"\\]|\\.)*)"', text, re.IGNORECASE):
            libraries.append(Path(_unescape_vdf(value)))
    return list(dict.fromkeys(libraries))


def _metadata_json_files(folder: Path) -> list[Path]:
    """*.json and *.JSON collapse to the same files on Windows; dedupe by casefold."""
    found = {str(path).casefold(): path for path in folder.glob("*.json")}
    found.update({str(path).casefold(): path for path in folder.glob("*.JSON")})
    return sorted(found.values(), key=lambda path: path.name.lower())


def resolve_game_name(source: Path) -> str:
    metadata_files = _metadata_json_files(source)
    if source.parent != source:
        metadata_files += _metadata_json_files(source.parent)
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
        online_name = _fetch_steam_game_name(appid)
        if online_name:
            return online_name
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


def _clear_preview_frames(destination_dir: Path) -> None:
    for index in range(1, 5):
        (destination_dir / f"frame_{index}.jpg").unlink(missing_ok=True)


def extract_preview_frames(files: list[Path], destination_dir: Path, manifest: Path | None = None) -> list[Path]:
    """Create four representative thumbnails without modifying the recording."""
    ffmpeg = find_executable("ffmpeg")
    ffprobe = find_executable("ffprobe", ffmpeg)
    if not ffmpeg or not ffprobe:
        raise ConversionError("FFmpeg and ffprobe are required for previews.")
    destination_dir.mkdir(parents=True, exist_ok=True)
    concat_list = _write_concat_list(files) if manifest is None else None
    try:
        probe = [str(ffprobe), "-v", "error"]
        if manifest:
            probe += ["-i", str(manifest)]
        else:
            probe += ["-f", "concat", "-safe", "0", "-i", str(concat_list)]
        probe += ["-show_entries", "format=duration", "-of", "default=nk=1:nw=1"]
        result = subprocess.run(
            probe,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            duration = max(0.0, float(result.stdout.strip()))
        except ValueError:
            detail = (result.stderr or "").strip()[-400:]
            raise ConversionError("ffprobe could not read the recording duration." + (f" {detail}" if detail else "")) from None
        # One FFmpeg process with four independent fast seeks. It avoids decoding
        # the whole recording while still keeping preview generation to one call.
        command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y"]
        for fraction in (0.0, 0.25, 0.5, 0.75):
            command += ["-ss", str(duration * fraction)]
            if manifest:
                command += ["-i", str(manifest)]
            else:
                command += ["-f", "concat", "-safe", "0", "-i", str(concat_list)]
        for index in range(4):
            command += [
                "-map",
                f"{index}:v:0",
                "-frames:v",
                "1",
                "-vf",
                "scale=320:-2",
                "-q:v",
                "5",
                str(destination_dir / f"frame_{index + 1}.jpg"),
            ]
        try:
            created = subprocess.run(
                command,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=PROBE_TIMEOUT_SECONDS,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired:
            raise ConversionError("FFmpeg timed out while generating the preview.") from None
        outputs = [destination_dir / f"frame_{index}.jpg" for index in range(1, 5) if (destination_dir / f"frame_{index}.jpg").exists()]
        if created.returncode != 0:
            outputs = []
        if not outputs:
            detail = (created.stderr or "").strip()[-400:]
            raise ConversionError("FFmpeg could not create preview frames." + (f" {detail}" if detail else ""))
        return outputs
    except BaseException:
        _clear_preview_frames(destination_dir)
        raise
    finally:
        if concat_list:
            concat_list.unlink(missing_ok=True)


def unique_path(path: Path) -> Path:
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ConversionError(f"Could not choose a free output name for {path.name}.")
