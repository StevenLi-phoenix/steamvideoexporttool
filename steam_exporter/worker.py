from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .media import SteamExporter, extract_first_frame


class TaskThread(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(float)
    preflight_signal = Signal(object)
    game_signal = Signal(str)
    preview_signal = Signal(str)
    error_signal = Signal(str)
    done_signal = Signal()

    def __init__(self, task: str, args: tuple, parent=None):
        super().__init__(parent)
        self.task = task
        self.args = args

    def run(self):
        try:
            exporter = SteamExporter(self.log_signal.emit, self.progress_signal.emit)
            if self.task == "preflight":
                self.preflight_signal.emit(exporter.preflight(*self.args))
                return
            if self.task == "preview":
                files = self.args[0]
                handle, name = tempfile.mkstemp(prefix="steam-preview-", suffix=".jpg")
                os.close(handle)
                target = Path(name)
                self.preview_signal.emit(str(extract_first_frame(files, target, self.args[1] if len(self.args) > 1 else None)))
                return
            source, output, output_format, limit, pattern, selected_folders = self.args
            result = exporter.preflight(source, output)
            selected = {Path(folder).resolve() for folder in selected_folders}
            result.recordings = [recording for recording in result.recordings if recording.folder.resolve() in selected]
            result.files = [path for recording in result.recordings for path in recording.files]
            result.game_name = result.recordings[0].game_name if result.recordings else "SteamRecording"
            if not result.recordings:
                self.error_signal.emit("No recording folders are selected.")
                return
            result.total_bytes = sum(path.stat().st_size for path in result.files)
            required = max(512 * 1024**2, int(result.total_bytes * 1.25))
            result.errors = [error for error in result.errors if not error.startswith("Not enough free space:")]
            if result.free_bytes < required:
                result.errors.append(f"Not enough free space for the selected recordings: {result.free_bytes:,} bytes available, about {required:,} needed.")
            self.game_signal.emit(result.game_name)
            if not result.ok:
                self.error_signal.emit("Preflight failed: " + " ".join(result.errors))
                return
            exporter.convert(result, output, output_format, limit, pattern)
            self.done_signal.emit()
        except Exception as exc:
            self.error_signal.emit(str(exc))
