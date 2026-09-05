"""Cached recording discovery with parallel filesystem work."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from multiprocessing import get_context
from pathlib import Path

from .media import RECORDING_DIR_APPID, resolve_game_name

CACHE_TTL = 300  # Also recheck in-place edits that do not change directory timestamps.
FALLBACK_NAME_TTL = 3600  # Retry folder-name fallbacks (e.g. offline) after an hour.


def cache_path(source: Path | str) -> Path:
    key = hashlib.sha256(str(Path(source).resolve()).casefold().encode()).hexdigest()[:24]
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SteamQuickExport" / f"library-{key}.json"


def read_cache(path: Path | str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if value.get("version") == 1 and isinstance(value.get("recordings"), dict) and isinstance(value.get("names"), dict):
            return value
    except (OSError, ValueError, AttributeError):
        pass
    return {"version": 1, "recordings": {}, "names": {}}


def inspect_folder(folder: str) -> dict:
    """Spawn-safe worker. scandir reuses Windows enumeration metadata for sizes."""
    total = 0
    directories = {}
    todo = [folder]
    while todo:
        current = todo.pop()
        directories[current] = os.stat(current).st_mtime_ns
        with os.scandir(current) as entries:
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    todo.append(entry.path)
                elif entry.name.lower().endswith(".m4s"):
                    total += entry.stat(follow_symlinks=False).st_size
    manifest = Path(folder) / "session.mpd"
    stat = manifest.stat()
    return {"size": total, "directories": directories, "manifest": [stat.st_mtime_ns, stat.st_size], "checked": time.time()}


def valid(folder: str, entry: dict, now: float) -> bool:
    try:
        if not isinstance(entry["size"], int) or entry["size"] < 0 or now - entry["checked"] >= CACHE_TTL:
            return False
        stat = (Path(folder) / "session.mpd").stat()
        return (
            [stat.st_mtime_ns, stat.st_size] == entry["manifest"]
            and bool(entry["directories"])
            and all(os.stat(p).st_mtime_ns == stamp for p, stamp in entry["directories"].items())
        )
    except (OSError, KeyError, TypeError, AttributeError):
        return False


def scan_library(
    source: Path | str,
    log: Callable[[str], None] = lambda _: None,
    *,
    force: bool = False,
    cache_file: Path | str | None = None,
    workers: int = 8,
) -> list[tuple[str, str, list[tuple[Path, int]]]]:
    source = Path(source).resolve()
    path = Path(cache_file) if cache_file else cache_path(source)
    cache = read_cache(path)
    now = time.time()
    folders = []
    for folder in sorted(source.glob("bg_*")):
        match = RECORDING_DIR_APPID.fullmatch(folder.name)
        if match and (folder / "session.mpd").is_file():
            folders.append((folder, match[1]))
    records, pending = {}, []
    for folder, _ in folders:
        key = str(folder)
        entry = cache["recordings"].get(key, {})
        if not force and valid(key, entry, now):
            records[key] = entry
        else:
            pending.append(key)
    log(f"{len(folders)} 段录像：{len(records)} 段命中缓存，{len(pending)} 段需要扫描")
    if pending:
        # Processes, not threads: per-entry Python work (name checks, dict
        # updates) holds the GIL, so threads measured ~2.6x slower than a
        # process pool on a real library despite the spawn cost.
        with ProcessPoolExecutor(max_workers=min(workers, len(pending)), mp_context=get_context("spawn")) as pool:
            futures = {pool.submit(inspect_folder, folder): folder for folder in pending}
            for number, future in enumerate(as_completed(futures), 1):
                folder = futures[future]
                try:
                    records[folder] = future.result()
                except OSError as exc:
                    log(f"暂时无法读取 {Path(folder).name}: {exc}")
                log(f"扫描 {number}/{len(pending)}")
    groups = {}
    for folder, appid in folders:
        if str(folder) in records:
            groups.setdefault(appid, []).append((folder, records[str(folder)]["size"]))
    names = cache["names"]
    unresolved = []
    for appid, rows in groups.items():
        entry = names.get(appid, {})
        if (
            force
            or not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or now - entry.get("checked", 0) > entry.get("ttl", 0)
        ):
            unresolved.append((appid, rows[0][0]))
    if unresolved:
        with ThreadPoolExecutor(max_workers=min(8, len(unresolved))) as pool:
            futures = {pool.submit(resolve_game_name, folder): (appid, folder) for appid, folder in unresolved}
            for future in as_completed(futures):
                appid, folder = futures[future]
                name = future.result()
                # A folder-name fallback means metadata is missing (or the store
                # API is unreachable); retrying every scan would stall each one,
                # so wait an hour. Shift+refresh bypasses the TTL.
                names[appid] = {"name": name, "checked": now, "ttl": FALLBACK_NAME_TTL if name == folder.name else 604800}
    cache = {"version": 1, "recordings": records, "names": names}
    # Atomic replacement; overlapping application instances never expose half-written JSON.
    temp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            json.dump(cache, handle, ensure_ascii=False)
        os.replace(temp, path)
    except OSError as exc:
        log(f"缓存未保存（本次结果仍可使用）：{exc}")
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return [(appid, names[appid]["name"], rows) for appid, rows in groups.items()]
