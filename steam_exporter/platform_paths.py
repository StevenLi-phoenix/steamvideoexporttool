"""Platform defaults shared by the GUI, settings, and recording discovery."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def videos_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Movies"
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                return Path(os.path.expandvars(winreg.QueryValueEx(key, "My Video")[0]))
        except OSError:
            pass
    return Path.home() / "Videos"


def settings_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SteamQuickExport"
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SteamQuickExport"


def steam_installation_roots() -> list[Path]:
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "Steam"]
    return list(
        dict.fromkeys(
            Path(base) / "Steam" for key in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA") if (base := os.environ.get(key))
        )
    )


def default_recordings_path() -> Path:
    if sys.platform == "darwin":
        candidates = []
        for root in steam_installation_roots():
            candidates.extend(root.glob("userdata/*/gamerecordings/video"))
            candidates.append(root / "gamerecordings" / "video")
        existing = []
        for path in candidates:
            try:
                if path.is_dir():
                    existing.append((path.stat().st_mtime_ns, path))
            except OSError:
                logger.debug("Cannot inspect recording folder %s", path, exc_info=True)
        if existing:
            selected = max(existing, key=lambda item: item[0])[1]
            logger.info("Found %d Steam recording folders; selected %s", len(existing), selected)
            return selected
    return videos_path() / "Steam" / "video"
