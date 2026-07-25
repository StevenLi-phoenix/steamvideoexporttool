from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RecordingInput:
    folder: Path
    files: list[Path]
    game_name: str
    manifest: Path | None = None


@dataclass
class PreflightResult:
    errors: list[str]
    warnings: list[str]
    files: list[Path]
    game_name: str
    ffmpeg: Path | None
    ffprobe: Path | None
    total_bytes: int
    free_bytes: int
    recordings: list[RecordingInput]

    @property
    def ok(self) -> bool:
        return not self.errors


class ConversionError(RuntimeError):
    """A user-facing conversion or validation failure."""
