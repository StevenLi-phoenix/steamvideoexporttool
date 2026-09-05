"""Nonblocking Qt adapter for the separate export process."""

import subprocess
from multiprocessing import get_context

from PySide6.QtCore import QObject, QTimer, Signal

from .export_backend import run_export
from .i18n import tr


class ExportClient(QObject):
    message = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.receiver = None
        self.outcome = None
        self.cancel_requested = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)

    def isRunning(self):
        return self.timer.isActive()

    def start(self, arguments):
        context = get_context("spawn")
        self.receiver, sender = context.Pipe(duplex=False)
        self.outcome = None
        self.cancel_requested = False
        self.process = context.Process(target=run_export, args=(list(arguments), sender))
        try:
            self.process.start()
        except Exception as exc:
            self.receiver.close()
            self.failed.emit(str(exc))
            self.finished.emit()
            return
        finally:
            sender.close()
        self.timer.start()

    def cancel(self):
        if not self.process or not self.isRunning():
            return
        self.cancel_requested = True
        # The backend owns FFmpeg; terminate the whole Windows process tree.
        subprocess.run(
            ["taskkill", "/PID", str(self.process.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
        )

    def poll(self):
        # Bound event processing so even a noisy backend cannot monopolize Qt.
        try:
            for _ in range(50):
                if not self.receiver.poll():
                    break
                try:
                    kind, text = self.receiver.recv()
                except (EOFError, OSError):
                    break
                if kind == "log":
                    self.message.emit(text)
                else:
                    self.outcome = kind, text
        except (EOFError, OSError):
            pass
        if self.process.is_alive():
            return
        # Drain on the next tick if a large log batch preceded the terminal event.
        if self.outcome is None:
            try:
                if self.receiver.poll():
                    kind, text = self.receiver.recv()
                    if kind == "log":
                        self.message.emit(text)
                    else:
                        self.outcome = kind, text
                    return
            except (EOFError, OSError):
                pass
        exitcode = self.process.exitcode
        self.timer.stop()
        self.receiver.close()
        self.process.join(timeout=0)
        self.process.close()
        if self.cancel_requested:
            self.failed.emit(tr("cancel_note"))
        elif self.outcome and self.outcome[0] == "done" and exitcode == 0:
            self.completed.emit(self.outcome[1])
        else:
            self.failed.emit(self.outcome[1] if self.outcome else tr("backend_exited", code=exitcode))
        self.finished.emit()
