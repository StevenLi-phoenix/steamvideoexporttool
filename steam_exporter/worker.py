from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .media import SteamExporter


class TaskThread(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(float)
    preflight_signal = Signal(object)
    game_signal = Signal(str)
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
            source, output, output_format, limit, pattern = self.args
            result = exporter.preflight(source, output)
            self.game_signal.emit(result.game_name)
            if not result.ok:
                self.error_signal.emit("Preflight failed: " + " ".join(result.errors))
                return
            exporter.convert(result, output, output_format, limit, pattern)
            self.done_signal.emit()
        except Exception as exc:
            self.error_signal.emit(str(exc))
