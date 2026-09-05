"""Recording-library UI; media processing lives in export_game and media."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import traceback
import webbrowser
import winreg
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .export_client import ExportClient
from .i18n import current_language, normalize_language, set_language, tr
from .library import scan_library
from .media import extract_preview_frames, find_executable, format_bytes, recording_timestamp, resource_path, safe_name
from .settings import load_settings, update_settings
from .taskqueue import ExportTask, TaskQueue

_PROGRESS = re.compile(r"^\[(\d+)/(\d+)\]")


def videos_path():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            return Path(os.path.expandvars(winreg.QueryValueEx(key, "My Video")[0]))
    except OSError:
        return Path.home() / "Videos"


class Job(QThread):
    message = Signal(str)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.result.emit(self.action(self.message.emit))
        except Exception as exc:
            # The traceback lands in the log pane via the error dialog's details.
            detail = "".join(traceback.format_exception(exc))
            self.failed.emit(f"{type(exc).__name__}: {exc}\n\n{detail}")


class SimpleApp(QMainWindow):
    def __init__(self, autoscan=True):
        super().__init__()
        self.setMinimumSize(820, 620)
        saved = load_settings()
        self.source = Path(saved["source"]) if saved.get("source") else videos_path() / "Steam" / "video"
        self.output = Path(saved["output"]) if saved.get("output") else videos_path() / "exported"
        self.job = self.preview_job = None
        self.close_after_cancel = False
        self.cancel_in_progress = False
        self._games = []
        self._status = None
        self.export_client = ExportClient(self)
        self.export_client.message.connect(self.export_message)
        self.export_client.progress.connect(self.export_progress)
        self.export_client.completed.connect(self.export_completed)
        self.export_client.failed.connect(self.error)
        self.export_client.finished.connect(self.export_finished)
        self.working = False
        self.tasks = TaskQueue()
        self.games = QListWidget()
        self.games.setContextMenuPolicy(Qt.CustomContextMenu)
        self.recordings = QTreeWidget()
        self.recordings.setRootIsDecorated(False)
        self.recordings.setColumnWidth(0, 300)
        self.recordings.setAlternatingRowColors(True)
        self.preview = QWidget()
        preview_layout = QHBoxLayout(self.preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_frames = []
        for _ in range(4):
            frame = QLabel()
            frame.setAlignment(Qt.AlignCenter)
            frame.setMinimumHeight(150)
            frame.setStyleSheet("background: #ededed; color: #666;")
            preview_layout.addWidget(frame)
            self.preview_frames.append(frame)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.detail = QLabel()
        self.status = QLabel()
        self.start = QPushButton()
        self.start.setEnabled(False)
        self.cancel = QPushButton()
        self.cancel.setVisible(False)
        self.cancel.setMinimumWidth(110)
        self.refresh = QPushButton()
        self.location = QPushButton()
        self.steam_recordings = QPushButton()
        self.destination = QPushButton()
        self.select_all = QPushButton()
        self.select_none = QPushButton()
        self.open_output = QPushButton()
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(6)
        self.progress.setTextVisible(False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMaximumHeight(100)
        self.logs = QPushButton()
        self.logs.setCheckable(True)
        self.logs.setChecked(bool(saved.get("log_visible")))
        self.log.setVisible(self.logs.isChecked())
        self.language = QPushButton()
        self.output_label = QLabel()
        self.output_label.setWordWrap(True)
        self.update_output()
        self.queue_label = QLabel()
        self.queue_label.setWordWrap(True)
        self.queue_label.setStyleSheet("color: #666;")
        self.queue_label.hide()
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        header = QHBoxLayout()
        self.heading = QLabel()
        self.heading.setStyleSheet("font-size: 28px; font-weight: 600;")
        header.addWidget(self.heading)
        header.addStretch()
        header.addWidget(self.language)
        header.addWidget(self.steam_recordings)
        header.addWidget(self.location)
        header.addWidget(self.refresh)
        layout.addLayout(header)
        splitter = QSplitter()
        splitter.addWidget(self.games)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 0, 0, 0)
        right_layout.addWidget(self.title)
        right_layout.addWidget(self.detail)
        row = QHBoxLayout()
        row.addWidget(self.select_all)
        row.addWidget(self.select_none)
        row.addStretch()
        right_layout.addLayout(row)
        right_layout.addWidget(self.recordings, 2)
        right_layout.addWidget(self.preview, 1)
        splitter.addWidget(right)
        splitter.setSizes([270, 700])
        layout.addWidget(splitter, 1)
        layout.addWidget(self.output_label)
        layout.addWidget(self.queue_label)
        footer = QHBoxLayout()
        for button in [self.destination, self.open_output, self.logs]:
            footer.addWidget(button)
        footer.addStretch()
        footer.addWidget(self.cancel)
        footer.addWidget(self.start)
        layout.addLayout(footer)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        layout.addWidget(self.log)
        self.setCentralWidget(body)
        self.setStyleSheet("""
            QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; }
            QPushButton { padding: 6px 12px; }
            QListWidget, QTreeWidget, QPlainTextEdit { border: 1px solid #ddd; background: white; }
            QListWidget::item { padding: 14px 10px; }
            QTreeWidget::item { padding: 7px 4px; }
        """)
        self.refresh.clicked.connect(self.scan_games)
        self.location.clicked.connect(self.choose_source)
        self.steam_recordings.clicked.connect(self.open_steam_recordings)
        self.destination.clicked.connect(self.choose_output)
        self.language.clicked.connect(self.toggle_language)
        self.games.currentItemChanged.connect(self.show_game)
        self.games.customContextMenuRequested.connect(self.games_context_menu)
        self.recordings.itemChanged.connect(self.selection_changed)
        self.recordings.currentItemChanged.connect(self.show_preview)
        self.select_all.clicked.connect(lambda: self.check_all(True))
        self.select_none.clicked.connect(lambda: self.check_all(False))
        self.start.clicked.connect(self.export)
        self.cancel.clicked.connect(self.cancel_export)
        self.open_output.clicked.connect(self.open_output_folder)
        self.logs.toggled.connect(self.log.setVisible)
        self.logs.toggled.connect(lambda visible: update_settings(log_visible=visible))
        self.retranslate()
        geometry = saved.get("geometry")
        if not geometry or not self.restoreGeometry(QByteArray.fromHex(geometry.encode())):
            self.resize(1040, 760)
        if autoscan:
            QTimer.singleShot(0, self.scan_games)

    def retranslate(self):
        """Re-apply every static string; called at startup and on language switch."""
        self.setWindowTitle(tr("app_title"))
        self.heading.setText(tr("heading_library"))
        self.steam_recordings.setText(tr("btn_open_steam"))
        self.location.setText(tr("btn_change_source"))
        self.refresh.setText(tr("btn_refresh"))
        self.refresh.setToolTip(tr("refresh_tooltip"))
        self.destination.setText(tr("btn_change_output"))
        self.open_output.setText(tr("btn_open_output"))
        self.logs.setText(tr("btn_logs"))
        self.select_all.setText(tr("btn_select_all"))
        self.select_none.setText(tr("btn_select_none"))
        self.cancel.setText(tr("btn_cancel"))
        self.start.setText(tr("btn_export", count=0))
        self.language.setText(tr("language_toggle"))
        self.language.setToolTip(tr("language_tooltip"))
        self.recordings.setHeaderLabels([tr("col_time"), tr("col_size")])
        for frame in self.preview_frames:
            if frame.pixmap() is None or frame.pixmap().isNull():
                frame.clear()
                frame.setText(tr("preview_placeholder"))
        for index in range(self.games.count()):
            item = self.games.item(index)
            appid, name, rows = item.data(Qt.UserRole)
            item.setText(f"{name}\n{tr('recordings_count', count=len(rows))}")
        self.refresh_queue_strip()
        current = self.games.currentItem()
        if current is not None:
            appid, name, rows = current.data(Qt.UserRole)
            self.title.setText(name)
            self.detail.setText(tr("detail_hint", count=len(rows)))
        elif self._games:
            self.title.setText(tr("title_placeholder"))
            self.detail.setText(tr("detail_none"))
        else:
            self.title.setText(tr("title_placeholder"))
            self.detail.setText(tr("detail_finding"))
        if self._status is None and not self.status.text():
            self.set_status("status_auto")
        elif self._status is not None:
            key, kwargs = self._status
            self.status.setText(tr(key, **kwargs))
        self.update_output()
        self.refresh_task_state()

    def update_output(self):
        self.output_label.setText(tr("output_label", output=self.output))

    def set_status(self, key, **kwargs):
        """Static status: remembered and re-rendered by retranslate()."""
        self._status = (key, kwargs)
        self.status.setText(tr(key, **kwargs))

    def set_raw_status(self, text):
        """Transient text (progress/log lines); left untouched by retranslate()."""
        self._status = None
        self.status.setText(text)

    def choose_source(self):
        value = QFileDialog.getExistingDirectory(self, tr("dialog_choose_source"), str(self.source))
        if value:
            self.source = Path(value)
            if (self.source / "video").is_dir():
                self.source /= "video"
            update_settings(source=str(self.source))
            self.scan_games()

    def open_steam_recordings(self):
        # Recordings live in Steam's "View > Screenshots and Recordings" manager,
        # not the Settings dialog; that manager is reachable via this URI handler.
        try:
            webbrowser.open("steam://open/screenshots")
            self.set_status("steam_opened")
        except OSError as exc:
            QMessageBox.warning(self, tr("steam_open_failed"), str(exc))

    def choose_output(self):
        value = QFileDialog.getExistingDirectory(self, tr("dialog_choose_output"), str(self.output))
        if value:
            self.output = Path(value)
            update_settings(output=str(self.output))
            self.update_output()

    def open_output_folder(self):
        existed = self.output.exists()
        try:
            self.output.mkdir(parents=True, exist_ok=True)
        except OSError:
            QMessageBox.warning(self, tr("dialog_notice"), tr("output_open_failed", path=self.output))
            return
        if not existed:
            self.set_status("output_created", path=self.output)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output)))

    def toggle_language(self):
        set_language("en" if current_language() == "zh-cn" else "zh-cn", persist=True)
        self.retranslate()

    def busy(self, value):
        self.working = value
        for widget in [self.games, self.recordings, self.location, self.destination, self.refresh, self.select_all, self.select_none]:
            widget.setEnabled(not value)
        if value:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        self.selection_changed()
        self.cancel.setVisible(value and self.export_client.isRunning())

    def run_job(self, action, done, on_message=None):
        self.busy(True)
        self.job = Job(action, self)
        self.job.message.connect(self.log.appendPlainText)
        if on_message:
            # Connected before the thread starts so early messages are not lost.
            self.job.message.connect(on_message)
        self.job.result.connect(done)
        self.job.failed.connect(self.error)
        self.job.finished.connect(lambda: self.busy(False))
        self.job.start()

    def error(self, message):
        if self.cancel_in_progress:
            # Cancelling is a user request, not a failure; the log suffices.
            self.cancel_in_progress = False
            self.log.appendPlainText(message)
            return
        self.set_status("error_status")
        self.log.appendPlainText(message)
        self.log.show()
        self.logs.setChecked(True)
        head, _, detail = message.partition("\n")
        box = QMessageBox(QMessageBox.Icon.Warning, tr("dialog_notice"), head or tr("dialog_notice"), parent=self)
        if detail:
            box.setDetailedText(detail.strip())
        box.exec()

    def scan_games(self):
        source = self.source
        force = bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)
        self.set_status("status_scanning")
        self.run_job(lambda log: scan_library(source, log, force=force), self.load_games, on_message=self.set_raw_status)

    def load_games(self, games):
        self._games = games
        self.games.clear()
        for appid, name, rows in games:
            item = QListWidgetItem(f"{name}\n{tr('recordings_count', count=len(rows))}")
            item.setData(Qt.UserRole, (appid, name, rows))
            self.games.addItem(item)
        if games:
            self.games.setCurrentRow(0)
        else:
            self.title.setText(tr("title_placeholder"))
            self.detail.setText(tr("detail_none"))
        self.set_status("status_found", count=len(games), source=self.source)

    def show_game(self, item, previous=None):
        self.recordings.clear()
        for frame in self.preview_frames:
            frame.clear()
            frame.setText(tr("preview_placeholder"))
        if not item:
            return
        appid, name, rows = item.data(Qt.UserRole)
        self.title.setText(name)
        self.detail.setText(tr("detail_hint", count=len(rows)))
        for folder, size in rows:
            row = QTreeWidgetItem([recording_timestamp(folder).strftime("%Y-%m-%d  %H:%M:%S"), format_bytes(size)])
            row.setData(0, Qt.UserRole, str(folder))
            row.setCheckState(0, Qt.Checked)
            self.recordings.addTopLevelItem(row)
        self.refresh_task_state()

    def selected(self):
        return [
            self.recordings.topLevelItem(i).data(0, Qt.UserRole)
            for i in range(self.recordings.topLevelItemCount())
            if self.recordings.topLevelItem(i).checkState(0) == Qt.Checked and not self.recordings.topLevelItem(i).isDisabled()
        ]

    def selection_changed(self, *args):
        count = len(self.selected())
        queued_mode = self.tasks.running is not None or bool(self.tasks.pending)
        self.start.setText(tr("btn_queue" if queued_mode else "btn_export", count=count))
        self.start.setEnabled(count > 0 and not self.working)

    def check_all(self, checked):
        for i in range(self.recordings.topLevelItemCount()):
            row = self.recordings.topLevelItem(i)
            if not row.isDisabled():
                row.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)

    def refresh_task_state(self):
        """Sync badges, locked rows, and the queue strip with the task queue."""
        locked = self.tasks.lock_paths()
        for index in range(self.games.count()):
            item = self.games.item(index)
            appid, name, rows = item.data(Qt.UserRole)
            badge = ""
            if self.tasks.running and self.tasks.running.appid == appid:
                badge = tr("badge_exporting")
            elif any(task.appid == appid for task in self.tasks.pending):
                badge = tr("badge_queued")
            text = f"{name}\n{tr('recordings_count', count=len(rows))}"
            if badge:
                text += f" · {badge}"
            item.setText(text)
        for i in range(self.recordings.topLevelItemCount()):
            row = self.recordings.topLevelItem(i)
            row.setDisabled(row.data(0, Qt.UserRole) in locked)
        self.refresh_queue_strip()
        self.selection_changed()

    def refresh_queue_strip(self):
        if not self.tasks.pending:
            self.queue_label.hide()
            return
        items = "、".join(
            tr("queue_item", index=index, game=task.game, count=len(task.recordings)) for index, task in enumerate(self.tasks.pending, 1)
        )
        self.queue_label.setText(tr("queue_strip", tasks=items))
        self.queue_label.setToolTip(tr("queue_remove_hint"))
        self.queue_label.show()

    def games_context_menu(self, pos):
        item = self.games.itemAt(pos)
        if not item:
            return
        appid, name, _ = item.data(Qt.UserRole)
        if not any(task.appid == appid for task in self.tasks.pending):
            return
        menu = QMenu(self)
        remove = menu.addAction(tr("context_remove"))
        if menu.exec(self.games.mapToGlobal(pos)) == remove:
            self.tasks.remove_game(appid)
            self.refresh_task_state()

    def show_preview(self, item, previous=None):
        if not item or (self.preview_job and self.preview_job.isRunning()):
            return
        folder = Path(item.data(0, Qt.UserRole))
        for frame in self.preview_frames:
            frame.clear()
            frame.setText(tr("preview_loading"))

        def action(log):
            with tempfile.TemporaryDirectory(prefix="steam-preview-") as temp:
                targets = extract_preview_frames([], Path(temp), folder / "session.mpd")
                return (str(folder), [target.read_bytes() for target in targets])

        def done(result):
            current = self.recordings.currentItem()
            if current and current.data(0, Qt.UserRole) == result[0]:
                for frame, data in zip(self.preview_frames, result[1], strict=False):
                    pixmap = QPixmap()
                    pixmap.loadFromData(data)
                    frame.setPixmap(pixmap.scaled(frame.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

        self.preview_job = Job(action, self)
        self.preview_job.result.connect(done)
        self.preview_job.failed.connect(lambda _: [frame.setText(tr("preview_unavailable")) for frame in self.preview_frames])

        def next_preview():
            current = self.recordings.currentItem()
            if current and current.data(0, Qt.UserRole) != str(folder):
                self.show_preview(current)

        self.preview_job.finished.connect(next_preview)
        self.preview_job.start()

    def export(self):
        item = self.games.currentItem()
        selected = self.selected()
        if not item or not selected:
            return
        appid, game, _ = item.data(Qt.UserRole)
        locked = self.tasks.lock_paths()
        paths = [folder for folder in selected if folder not in locked]
        if not paths:
            self.set_status("already_queued")
            return
        task = ExportTask(
            appid=appid,
            game=game,
            recordings=[Path(folder).name for folder in paths],
            paths=paths,
        )
        if self.tasks.running is None:
            self.start_task(task)
        else:
            self.tasks.enqueue(task)
            self.set_status("task_queued", game=game, count=len(paths))
            self.refresh_task_state()

    def start_task(self, task):
        self.tasks.running = task
        output = self.output / safe_name(task.game)
        args = ["--source", str(self.source), "--output", str(output), "--appid", task.appid, "--game", task.game]
        for recording in task.recordings:
            args += ["--recording", recording]
        self.log.clear()
        self.set_status("status_exporting", count=len(task.recordings))
        self.busy(True)
        # Library browsing stays usable while the snapshot of selected paths exports.
        for widget in [self.games, self.recordings, self.select_all, self.select_none]:
            widget.setEnabled(True)
        self.export_client.start(args)
        self.cancel.setVisible(True)
        self.cancel.setEnabled(True)
        self.refresh_task_state()

    def cancel_export(self):
        if self.export_client.isRunning():
            self.cancel_in_progress = True
            self.cancel.setEnabled(False)
            self.set_status("status_cancelling")
            self.export_client.cancel()

    def export_finished(self):
        finished_paths = set(self.tasks.running.paths) if self.tasks.running else set()
        self.tasks.finish()
        self.busy(False)
        # Uncheck the rows that just completed so the same task is not re-queued by accident.
        for i in range(self.recordings.topLevelItemCount()):
            row = self.recordings.topLevelItem(i)
            if row.data(0, Qt.UserRole) in finished_paths:
                row.setCheckState(0, Qt.Unchecked)
        if self.close_after_cancel:
            self.close_after_cancel = False
            self.close()
            return
        next_task = self.tasks.take_next()
        self.refresh_task_state()
        if next_task:
            self.start_task(next_task)

    def export_progress(self, fraction):
        """Real progress from FFmpeg's -progress feed, mapped over the whole task."""
        self.progress.setRange(0, 1000)
        self.progress.setValue(max(1, int(fraction * 1000)))

    def export_message(self, message):
        self.log.appendPlainText(message)
        self.set_raw_status(message[-160:])
        match = _PROGRESS.match(message)
        if match:
            index, total = int(match[1]), int(match[2])
            self.progress.setRange(0, total)
            self.progress.setValue(index - 1)
        elif message.startswith(("COMPLETE", "完成")):
            self.progress.setRange(0, 1)
            self.progress.setValue(1)

    def export_completed(self, output):
        self.set_status("export_done", output=output)
        QDesktopServices.openUrl(QUrl.fromLocalFile(output))

    def closeEvent(self, event):
        update_settings(geometry=bytes(self.saveGeometry().toHex()).decode("ascii"))
        if self.export_client.isRunning():
            self.close_after_cancel = True
            self.cancel_export()
            self.set_status("status_close_cancel")
            event.ignore()
        elif any(job and job.isRunning() for job in [self.job, self.preview_job]):
            QMessageBox.information(self, tr("dialog_busy_title"), tr("dialog_busy_text"))
            event.ignore()
        else:
            event.accept()


def configure_app(app):
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in [
        (QPalette.Window, "#fafafa"),
        (QPalette.WindowText, "#202020"),
        (QPalette.Base, "#ffffff"),
        (QPalette.AlternateBase, "#f6f6f6"),
        (QPalette.Text, "#202020"),
        (QPalette.Button, "#f5f5f5"),
        (QPalette.ButtonText, "#202020"),
        (QPalette.Highlight, "#dedede"),
        (QPalette.HighlightedText, "#111111"),
    ]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    icon_path = resource_path("assets", "app-icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))


def main():
    if "--lang" in sys.argv:
        value = normalize_language(sys.argv[sys.argv.index("--lang") + 1])
        if value:
            set_language(value)
    app = QApplication([])
    app.setApplicationName("SteamQuickExport")
    configure_app(app)
    smoke = "--self-test" in sys.argv
    window = SimpleApp(autoscan=not smoke)
    window.show()
    if smoke:
        for name in ("ffmpeg", "ffprobe"):
            binary = find_executable(name, find_executable("ffmpeg"))
            if not binary:
                raise RuntimeError(f"Missing bundled {name}")
            subprocess.run(
                [str(binary), "-version"], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=20
            )
        if "--scan-self-test" in sys.argv:
            scan_library(window.source, force=True)
        QTimer.singleShot(100, app.quit)
    app.exec()
