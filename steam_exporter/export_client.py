"""Nonblocking Qt adapter for the separate export process."""

import logging
import os
import signal
import subprocess
import sys
from multiprocessing import get_context

from PySide6.QtCore import QObject, QTimer, Signal

from .export_backend import run_export
from .i18n import tr


class ExportClient(QObject):
    message = Signal(str)
    progress = Signal(float)
    completed = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.receiver = None
        self.outcome = None
        self.cancel_requested = False
        self.backend_ready = False
        self.cancel_sent = False
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
        self.backend_ready = False
        self.cancel_sent = False
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

    def cancel(self) -> None:
        if not self.process or not self.isRunning() or self.cancel_sent:
            return
        self.cancel_requested = True
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self.cancel_sent = True
        elif self.backend_ready:
            # Wait for the ready message before signalling: cancellation may be
            # requested while spawn is still importing, before setsid runs.
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # The worker already exited.
            self.cancel_sent = True
        logging.getLogger(__name__).info("Export cancellation requested for worker %s", self.process.pid)

    def poll(self):
        # Bound event processing so even a noisy backend cannot monopolize Qt.
        try:
            for _ in range(50):
                if not self.receiver.poll():
                    break
                try:
                    kind, payload = self.receiver.recv()
                except (EOFError, OSError):
                    break
                if kind == "ready":
                    self.backend_ready = True
                    if self.cancel_requested:
                        self.cancel()
                elif kind == "log":
                    self.message.emit(payload)
                elif kind == "progress":
                    self.progress.emit(float(payload))
                else:
                    self.outcome = kind, payload
        except (EOFError, OSError):
            pass
        if self.process.is_alive():
            return
        # Drain on the next tick if a large log batch preceded the terminal event.
        if self.outcome is None:
            try:
                if self.receiver.poll():
                    kind, payload = self.receiver.recv()
                    if kind == "log":
                        self.message.emit(payload)
                    elif kind == "progress":
                        self.progress.emit(float(payload))
                    else:
                        self.outcome = kind, payload
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
