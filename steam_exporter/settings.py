"""Tiny JSON settings store shared by the GUI and the spawned export backend.

A JSON file (not QSettings) because the Qt-free export backend also needs to
read the language preference.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .platform_paths import settings_dir

SETTINGS_DIR = settings_dir()
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


def load_settings(path: Path | None = None) -> dict:
    try:
        value = json.loads((path or SETTINGS_FILE).read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    except (OSError, ValueError):
        pass
    return {}


def update_settings(**updates) -> None:
    """Merge updates into settings.json; failures are non-fatal by design."""
    merged = load_settings()
    merged.update(updates)
    temp = None
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=SETTINGS_FILE.parent, delete=False) as handle:
            temp = Path(handle.name)
            json.dump(merged, handle, ensure_ascii=False, indent=2)
        os.replace(temp, SETTINGS_FILE)
    except OSError:
        pass
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
