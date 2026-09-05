"""FIFO export queue: one export at a time, recordings locked while queued/running.

The GUI queues one task per game/selection snapshot. Every recording folder in
a queued or running task is locked, so the same footage cannot be triggered
twice; a different recording of the same game may still be queued.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExportTask:
    appid: str
    game: str
    recordings: list[str]  # bg_ folder names passed to the export pipeline
    paths: list[str]  # absolute recording folder paths, used as lock keys


class TaskQueue:
    def __init__(self):
        self.pending: list[ExportTask] = []
        self.running: ExportTask | None = None

    def lock_paths(self) -> set[str]:
        """Recording paths that are exporting or waiting; they must not be re-triggered."""
        locked: set[str] = set()
        if self.running:
            locked.update(self.running.paths)
        for task in self.pending:
            locked.update(task.paths)
        return locked

    def enqueue(self, task: ExportTask) -> bool:
        """Append a task unless every one of its recordings is already locked."""
        locked = self.lock_paths()
        if task.paths and all(path in locked for path in task.paths):
            return False
        self.pending.append(task)
        return True

    def take_next(self) -> ExportTask | None:
        """Pop the oldest pending task into the running slot (FIFO)."""
        if self.running is not None or not self.pending:
            return None
        self.running = self.pending.pop(0)
        return self.running

    def finish(self) -> None:
        """Clear the running slot; call after the export process ends."""
        self.running = None

    def remove_game(self, appid: str) -> int:
        """Drop every pending task of one game; the running task is untouched."""
        remaining = [task for task in self.pending if task.appid != appid]
        removed = len(self.pending) - len(remaining)
        self.pending = remaining
        return removed

    def clear(self) -> None:
        self.pending.clear()
        self.running = None
