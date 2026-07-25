from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import END, BooleanVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


APP_TITLE = "Steam Video Exporter"
DEFAULT_PATTERN = "{game}_{date}_{time}_part{index}.{ext}"
TOKEN_HELP = "Tokens: {game} {date} {time} {index} {source} {ext}"


def format_bytes(value: int | float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{amount:.1f} TB"


def safe_name(value: str, fallback: str = "SteamRecording") -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value).strip(" .")
    return value or fallback


def ffmpeg_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("FFMPEG_PATH")
    if configured:
        candidates.append(Path(configured))
    app_dir = Path(__file__).resolve().parent
    candidates.extend((app_dir / "ffmpeg.exe", app_dir / "bin" / "ffmpeg.exe"))
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(Path(found))
    return candidates


def find_executable(name: str, ffmpeg_path: Path | None = None) -> Path | None:
    if name == "ffmpeg":
        for candidate in ffmpeg_candidates():
            if candidate.exists():
                return candidate
        return None
    if ffmpeg_path:
        sibling = ffmpeg_path.with_name(name + ffmpeg_path.suffix)
        if sibling.exists():
            return sibling
    found = shutil.which(name)
    return Path(found) if found else None


def parse_appid(text: str) -> str | None:
    matches = re.findall(r"(?:^|[\\/_-])(\d{3,8})(?:$|[\\/_-])", text)
    return matches[-1] if matches else None


def parse_steam_name(text: str) -> str | None:
    match = re.search(r'"name"\s+"((?:[^"\\]|\\.)*)"', text, re.IGNORECASE)
    if not match:
        return None
    return bytes(match.group(1), "utf-8").decode("unicode_escape", errors="ignore")


def steam_roots() -> list[Path]:
    roots: list[Path] = []
    for key in (
        r"HKEY_CURRENT_USER\Software\Valve\Steam",
        r"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Valve\Steam",
    ):
        try:
            import winreg

            hive, subkey = key.split("\\", 1)
            hive_obj = getattr(winreg, hive)
            with winreg.OpenKey(hive_obj, subkey) as handle:
                value, _ = winreg.QueryValueEx(handle, "SteamPath")
                roots.append(Path(value))
        except (OSError, ImportError):
            pass
    roots.extend(
        Path(value)
        for value in (
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("PROGRAMFILES"),
            os.environ.get("LOCALAPPDATA"),
        )
        if value
    )
    return list(dict.fromkeys(roots))


def resolve_game_name(source: Path) -> str:
    # Steam recording metadata has appeared in JSON and VDF-like files over time.
    for metadata in sorted(source.rglob("*.json"))[:50]:
        try:
            data = json.loads(metadata.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, UnicodeError):
            continue
        if isinstance(data, dict):
            for key in ("gameName", "game_name", "gameTitle", "title", "name"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return safe_name(value)

    appid = parse_appid(str(source))
    search_roots = [source] + steam_roots()
    for root in search_roots:
        if not root.exists():
            continue
        patterns = [f"appmanifest_{appid}.acf"] if appid else []
        patterns.append("*.acf")
        for pattern in patterns:
            try:
                manifests = list(root.rglob(pattern))[:100]
            except OSError:
                manifests = []
            for manifest in manifests:
                try:
                    name = parse_steam_name(manifest.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    continue
                if name:
                    return safe_name(name)

    for part in reversed(source.parts):
        if part.lower() not in {"gamerecordings", "recordings", "video", "videos"} and not part.isdigit():
            return safe_name(part)
    return "SteamRecording"


def discover_m4s(source: Path) -> list[Path]:
    return sorted(
        (path for path in source.rglob("*.m4s") if path.is_file()),
        key=lambda path: (str(path.parent).lower(), path.name.lower()),
    )


def escape_concat_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def write_concat_list(files: list[Path]) -> Path:
    handle, name = tempfile.mkstemp(prefix="steam-video-", suffix=".txt", text=True)
    os.close(handle)
    list_path = Path(name)
    list_path.write_text("\n".join(f"file '{escape_concat_path(path)}'" for path in files), encoding="utf-8")
    return list_path


def read_duration(ffprobe: Path | None, concat_list: Path) -> float | None:
    if not ffprobe:
        return None
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-show_entries", "format=duration", "-of", "default=nk=1:nw=1"],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return None


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

    @property
    def ok(self) -> bool:
        return not self.errors


class ConversionError(RuntimeError):
    pass


class SteamExporter:
    def __init__(self, log, progress):
        self.log = log
        self.progress = progress

    def preflight(self, source_text: str, output_text: str) -> PreflightResult:
        errors: list[str] = []
        warnings: list[str] = []
        source = Path(source_text).expanduser()
        output = Path(output_text).expanduser()
        files = discover_m4s(source) if source.is_dir() else []
        ffmpeg = find_executable("ffmpeg")
        ffprobe = find_executable("ffprobe", ffmpeg)

        if not source.is_dir():
            errors.append("The input folder does not exist or is not a folder.")
        if not files:
            errors.append("No .m4s files were found below the input folder.")
        if not ffmpeg:
            errors.append("FFmpeg was not found. Put ffmpeg.exe beside the app or add it to PATH.")
        if not output.exists():
            try:
                output.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                errors.append(f"The output folder could not be created: {exc}")
        if output.exists() and not os.access(output, os.W_OK):
            errors.append("The output folder is not writable.")

        total = sum(path.stat().st_size for path in files) if files else 0
        free = shutil.disk_usage(output).free if output.exists() else 0
        # Conversion needs source files plus a staged output; leave a 512 MiB safety margin.
        required = max(512 * 1024**2, int(total * 1.25))
        if output.exists() and free < required:
            errors.append(f"Not enough free space: {format_bytes(free)} available, about {format_bytes(required)} needed.")
        elif output.exists() and free < required * 2:
            warnings.append(f"Free space is tight ({format_bytes(free)}). A large conversion may need more headroom.")
        if ffmpeg and not ffprobe:
            warnings.append("ffprobe was not found; duration will be estimated and segment sizing may be less precise.")

        game_name = resolve_game_name(source) if source.exists() else "SteamRecording"
        return PreflightResult(errors, warnings, files, game_name, ffmpeg, ffprobe, total, free)

    def convert(self, result: PreflightResult, output_text: str, output_format: str, limit_bytes: int, pattern: str):
        if not result.ok or not result.ffmpeg:
            raise ConversionError("Preflight checks did not pass.")
        output = Path(output_text).expanduser()
        output.mkdir(parents=True, exist_ok=True)
        concat_list = write_concat_list(result.files)
        staging = output / f".steam-export-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            duration = read_duration(result.ffprobe, concat_list)
            if not duration or duration <= 0:
                duration = max(1800.0, result.total_bytes * 8 / 8_000_000)
            estimated_bps = max(1_500_000, result.total_bytes * 8 / duration * 1.15)
            segment_seconds = max(30.0, (limit_bytes * 0.88 * 8) / estimated_bps)
            self.log(f"Game: {result.game_name}")
            self.log(f"Input: {len(result.files)} .m4s file(s), {format_bytes(result.total_bytes)}")
            self.log(f"Target: {output_format.upper()}, max {format_bytes(limit_bytes)} per segment")

            for attempt in range(3):
                for old in staging.iterdir():
                    if old.is_file():
                        old.unlink()
                self.log(f"Encoding pass {attempt + 1}/3 (about {segment_seconds / 60:.0f} minutes per segment)...")
                extension = output_format.lower()
                command = [str(result.ffmpeg), "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                           "-map", "0:v:0?", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                           "-c:a", "aac", "-b:a", "192k", "-force_key_frames", f"expr:gte(t,n_forced*{segment_seconds:.3f})",
                           "-f", "segment", "-segment_time", f"{segment_seconds:.3f}", "-reset_timestamps", "1"]
                if extension in {"mp4", "mov"}:
                    command.extend(["-segment_format", extension, "-movflags", "+faststart"])
                else:
                    command.extend(["-segment_format", "flv"])
                command.append(str(staging / f"segment_%04d.{extension}"))

                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                assert process.stdout
                for line in process.stdout:
                    line = line.strip()
                    if line and ("frame=" in line or "time=" in line or "Error" in line):
                        self.log(line[-180:])
                code = process.wait()
                if code != 0:
                    raise ConversionError("FFmpeg could not decode the selected .m4s files. Check the log for details.")

                segments = sorted(staging.glob(f"*.{extension}"))
                if not segments:
                    raise ConversionError("FFmpeg finished without producing an output video.")
                largest = max(path.stat().st_size for path in segments)
                if largest <= limit_bytes * 0.98 or attempt == 2:
                    break
                segment_seconds *= 0.72
                self.log(f"Largest segment was {format_bytes(largest)}; reducing segment duration and retrying.")

            date = datetime.now()
            source_name = safe_name(result.files[0].parent.name if result.files else "recording")
            final_paths: list[Path] = []
            for index, segment in enumerate(segments, start=1):
                filename = render_filename(pattern, result.game_name, source_name, date, index, extension, len(segments))
                destination = output / filename
                if destination.exists():
                    destination = unique_path(destination)
                shutil.move(str(segment), str(destination))
                final_paths.append(destination)
                self.log(f"Created {destination.name} ({format_bytes(destination.stat().st_size)})")
                self.progress(index / len(segments))
            self.log(f"Done: {len(final_paths)} file(s) written to {output}")
        finally:
            try:
                concat_list.unlink(missing_ok=True)
            except OSError:
                pass
            shutil.rmtree(staging, ignore_errors=True)


def unique_path(path: Path) -> Path:
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ConversionError(f"Could not choose a free output name for {path.name}.")


def render_filename(pattern: str, game: str, source: str, date: datetime, index: int, extension: str, count: int) -> str:
    values = {
        "game": safe_name(game),
        "source": safe_name(source),
        "date": date.strftime("%Y-%m-%d"),
        "time": date.strftime("%H-%M-%S"),
        "index": f"{index:03d}",
        "ext": extension,
    }
    try:
        rendered = pattern.format(**values)
    except (KeyError, ValueError):
        rendered = DEFAULT_PATTERN.format(**values)
    rendered = safe_name(rendered)
    if not rendered.lower().endswith("." + extension):
        rendered += "." + extension
    if count > 1 and "{index}" not in pattern:
        stem = Path(rendered).stem
        rendered = f"{stem}_part{index:03d}{Path(rendered).suffix}"
    return rendered


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("920x720")
        self.root.minsize(780, 620)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False

        self.source = StringVar()
        self.output = StringVar()
        self.output_format = StringVar(value="mp4")
        self.limit_choice = StringVar(value="16")
        self.custom_limit = StringVar(value="16")
        self.pattern = StringVar(value=DEFAULT_PATTERN)
        self.detected_game = StringVar(value="Not checked yet")
        self.progress_value = __import__("tkinter").DoubleVar(value=0)
        self.status = StringVar(value="Choose an input folder to begin.")
        self._build_ui()
        self.root.after(150, self._poll_events)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP_TITLE, font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Convert Steam Game Recording .m4s files into size-limited, shareable videos.", foreground="#555").pack(anchor="w", pady=(2, 18))

        paths = ttk.LabelFrame(outer, text="Folders", padding=12)
        paths.pack(fill="x")
        self._path_row(paths, "Input folder", self.source, self._choose_source)
        self._path_row(paths, "Output folder", self.output, self._choose_output)

        settings = ttk.LabelFrame(outer, text="Export settings", padding=12)
        settings.pack(fill="x", pady=12)
        ttk.Label(settings, text="Format").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Combobox(settings, textvariable=self.output_format, values=("mp4", "mov", "flv"), state="readonly", width=8).grid(row=0, column=1, sticky="w", pady=5)
        ttk.Label(settings, text="Max size per output segment").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        limits = ttk.Frame(settings)
        limits.grid(row=1, column=1, columnspan=3, sticky="w", pady=5)
        for value, label in (("16", "16 GB"), ("64", "64 GB"), ("custom", "Custom")):
            ttk.Radiobutton(limits, text=label, value=value, variable=self.limit_choice).pack(side="left", padx=(0, 12))
        ttk.Entry(limits, textvariable=self.custom_limit, width=8).pack(side="left")
        ttk.Label(limits, text="GB").pack(side="left", padx=(4, 0))
        ttk.Label(settings, text="Filename pattern").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Entry(settings, textvariable=self.pattern).grid(row=2, column=1, columnspan=4, sticky="ew", pady=5)
        ttk.Label(settings, text=TOKEN_HELP, foreground="#666").grid(row=3, column=1, columnspan=4, sticky="w")
        settings.columnconfigure(4, weight=1)

        info = ttk.Frame(outer)
        info.pack(fill="x", pady=(0, 10))
        ttk.Label(info, text="Detected game:", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Label(info, textvariable=self.detected_game).pack(side="left", padx=(6, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(0, 8))
        self.preflight_button = ttk.Button(actions, text="Run preflight checks", command=self.run_preflight)
        self.preflight_button.pack(side="left")
        self.convert_button = ttk.Button(actions, text="Convert", command=self.start_conversion)
        self.convert_button.pack(side="left", padx=8)
        ttk.Label(actions, textvariable=self.status, foreground="#555").pack(side="left", padx=8)

        self.progress = ttk.Progressbar(outer, variable=self.progress_value, maximum=1, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 10))
        log_frame = ttk.LabelFrame(outer, text="Preflight and conversion log", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log_text = ScrolledText(log_frame, height=14, wrap="word", state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

    def _path_row(self, parent, label, variable, command):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=18).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=command).pack(side="left", padx=(8, 0))

    def _choose_source(self):
        selected = filedialog.askdirectory(title="Choose Steam recording folder")
        if selected:
            self.source.set(selected)
            if not self.output.get():
                self.output.set(str(Path(selected) / "exports"))

    def _choose_output(self):
        selected = filedialog.askdirectory(title="Choose output folder")
        if selected:
            self.output.set(selected)

    def log(self, message: str):
        self.events.put(("log", message))

    def progress(self, value: float):
        self.events.put(("progress", value))

    def _poll_events(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "log":
                    self.log_text.configure(state="normal")
                    self.log_text.insert(END, str(value) + "\n")
                    self.log_text.see(END)
                    self.log_text.configure(state="disabled")
                elif event == "progress":
                    self.progress_value.set(float(value))
                elif event == "preflight":
                    self._show_preflight(value)
                elif event == "done":
                    self._set_busy(False)
                    self.status.set("Conversion complete.")
                    messagebox.showinfo(APP_TITLE, "Conversion complete.")
                elif event == "error":
                    self._set_busy(False)
                    self.status.set("Operation failed.")
                    messagebox.showerror(APP_TITLE, str(value))
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def _set_busy(self, busy: bool):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.preflight_button.configure(state=state)
        self.convert_button.configure(state=state)

    def _show_preflight(self, result: PreflightResult):
        self.detected_game.set(result.game_name)
        self._set_busy(False)
        self.status.set("Preflight passed." if result.ok else "Preflight found issues.")
        self.log("--- PREFLIGHT ---")
        self.log(f"Game name: {result.game_name}")
        self.log(f"Files: {len(result.files)} | Input size: {format_bytes(result.total_bytes)} | Free space: {format_bytes(result.free_bytes)}")
        for warning in result.warnings:
            self.log("WARNING: " + warning)
        for error in result.errors:
            self.log("ERROR: " + error)
        if result.ok:
            messagebox.showinfo(APP_TITLE, "Preflight passed. The selected folder is ready to convert.")
        else:
            messagebox.showerror(APP_TITLE, "Preflight failed. Fix the errors shown in the log, then try again.")

    def _limit_bytes(self) -> int:
        value = self.custom_limit.get() if self.limit_choice.get() == "custom" else self.limit_choice.get()
        try:
            gb = float(value)
        except ValueError as exc:
            raise ConversionError("Custom segment size must be a positive number of GB.") from exc
        if gb <= 0:
            raise ConversionError("Segment size must be greater than zero.")
        return int(gb * 1024**3)

    def run_preflight(self):
        if self.busy:
            return
        self._set_busy(True)
        self.status.set("Running preflight checks...")
        self._clear_log()
        threading.Thread(target=self._preflight_worker, daemon=True).start()

    def _preflight_worker(self):
        try:
            result = SteamExporter(self.log, self.progress).preflight(self.source.get(), self.output.get())
            self.events.put(("preflight", result))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def start_conversion(self):
        if self.busy:
            return
        try:
            limit = self._limit_bytes()
        except ConversionError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self._set_busy(True)
        self.progress_value.set(0)
        self.status.set("Running preflight checks...")
        self._clear_log()
        threading.Thread(target=self._conversion_worker, args=(limit,), daemon=True).start()

    def _conversion_worker(self, limit: int):
        try:
            exporter = SteamExporter(self.log, self.progress)
            result = exporter.preflight(self.source.get(), self.output.get())
            self.detected_game.set(result.game_name)
            if not result.ok:
                self.events.put(("error", "Preflight failed: " + " ".join(result.errors)))
                return
            self.events.put(("log", "--- CONVERSION ---"))
            exporter.convert(result, self.output.get(), self.output_format.get(), limit, self.pattern.get())
            self.events.put(("done", None))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", END)
        self.log_text.configure(state="disabled")


def main():
    root = Tk()
    try:
        root.tk.call("tk", "scaling", 1.15)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
