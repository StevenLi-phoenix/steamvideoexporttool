"""Recording-library UI; media processing lives in export_game and media."""
from __future__ import annotations

import os
import tempfile
import sys
import subprocess
import webbrowser
import winreg
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap, QPalette, QColor
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget)

from .export_client import ExportClient
from .library import scan_library
from .media import resolve_game_name, safe_name, recording_timestamp, extract_first_frame, find_executable


def videos_path():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
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
            self.failed.emit(str(exc))


class SimpleApp(QMainWindow):
    def __init__(self, autoscan=True):
        super().__init__()
        self.setWindowTitle("Steam 录制")
        self.resize(1040, 760)
        self.setMinimumSize(820, 620)
        self.source = videos_path() / "Steam" / "video"
        self.output = videos_path() / "exported"
        self.job = self.preview_job = None
        self.close_after_cancel = False
        self.export_client = ExportClient(self)
        self.export_client.message.connect(self.export_message)
        self.export_client.completed.connect(lambda output: self.status.setText(f"导出完成：{output}"))
        self.export_client.failed.connect(self.error)
        self.export_client.finished.connect(self.export_finished)
        self.working = False
        self.games = QListWidget()
        self.recordings = QTreeWidget()
        self.recordings.setHeaderLabels(["录像时间", "大小"])
        self.recordings.setRootIsDecorated(False)
        self.recordings.setColumnWidth(0, 300)
        self.recordings.setAlternatingRowColors(True)
        self.preview = QLabel("点击录像，查看首帧")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(180)
        self.preview.setStyleSheet("background: #ededed; color: #666;")
        self.title = QLabel("你的游戏")
        self.title.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.detail = QLabel("正在查找录制…")
        self.status = QLabel("自动查找 Steam 录制，无需输入 AppID。")
        self.start = QPushButton("导出所选录像")
        self.start.setEnabled(False)
        self.cancel = QPushButton("取消导出")
        self.cancel.setVisible(False)
        self.cancel.setMinimumWidth(110)
        self.refresh = QPushButton("刷新")
        self.refresh.setToolTip("使用缓存刷新；按住 Shift 点击可强制重新扫描")
        self.location = QPushButton("更改录制位置…")
        self.steam_recordings = QPushButton("打开 Steam 录制")
        self.destination = QPushButton("更改输出位置…")
        self.select_all = QPushButton("全选")
        self.select_none = QPushButton("清空选择")
        self.open_output = QPushButton("打开输出文件夹")
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(6)
        self.progress.setTextVisible(False)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMaximumHeight(100)
        self.log.hide()
        self.logs = QPushButton("日志")
        self.output_label = QLabel()
        self.output_label.setWordWrap(True)
        self.update_output()
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        header = QHBoxLayout()
        heading = QLabel("录制库")
        heading.setStyleSheet("font-size: 28px; font-weight: 600;")
        header.addWidget(heading)
        header.addStretch()
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
        self.games.currentItemChanged.connect(self.show_game)
        self.recordings.itemChanged.connect(self.selection_changed)
        self.recordings.currentItemChanged.connect(self.show_preview)
        self.select_all.clicked.connect(lambda: self.check_all(True))
        self.select_none.clicked.connect(lambda: self.check_all(False))
        self.start.clicked.connect(self.export)
        self.cancel.clicked.connect(self.cancel_export)
        self.open_output.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output))))
        self.logs.clicked.connect(lambda: self.log.setVisible(not self.log.isVisible()))
        if autoscan:
            QTimer.singleShot(0, self.scan_games)

    def update_output(self):
        self.output_label.setText(f"保存到 {self.output} / 游戏名\nMP4 · 原画质无损封装 · 每段 < 64 GB · 保留原文件")

    def choose_source(self):
        value = QFileDialog.getExistingDirectory(self, "选择 Steam 录制目录", str(self.source))
        if value:
            self.source = Path(value)
            if (self.source / "video").is_dir():
                self.source /= "video"
            self.scan_games()

    def open_steam_recordings(self):
        # Recordings live in Steam's "View > Screenshots and Recordings" manager,
        # not the Settings dialog; that manager is reachable via this URI handler.
        try:
            webbrowser.open("steam://open/screenshots")
            self.status.setText("已打开 Steam 的“截图与录像”，请在其中删除录像；完成后点击刷新。")
        except OSError as exc:
            QMessageBox.warning(self, "无法打开 Steam", str(exc))

    def choose_output(self):
        value = QFileDialog.getExistingDirectory(self, "选择输出位置", str(self.output))
        if value:
            self.output = Path(value)
            self.update_output()

    def busy(self, value):
        self.working = value
        for widget in [self.games, self.recordings, self.location, self.destination,
                       self.refresh, self.select_all, self.select_none]:
            widget.setEnabled(not value)
        self.progress.setRange(0, 0 if value else 100)
        self.selection_changed()
        self.cancel.setVisible(value and self.export_client.isRunning())

    def run_job(self, action, done):
        self.busy(True)
        self.job = Job(action, self)
        self.job.message.connect(self.log.appendPlainText)
        self.job.result.connect(done)
        self.job.failed.connect(self.error)
        self.job.finished.connect(lambda: self.busy(False))
        self.job.start()

    def error(self, message):
        self.status.setText("操作未完成，原始录制已保留。")
        self.log.appendPlainText(message)
        self.log.show()
        QMessageBox.warning(self, "提示", message)

    def scan_games(self):
        source = self.source
        force = bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)
        self.status.setText("正在读取录制库…")
        self.run_job(lambda log: scan_library(source, log, force=force), self.load_games)
        self.job.message.connect(self.status.setText)

    def load_games(self, games):
        self.games.clear()
        for appid, name, rows in games:
            item = QListWidgetItem(f"{name}\n{len(rows)} 段录像")
            item.setData(Qt.UserRole, (appid, name, rows))
            self.games.addItem(item)
        if games:
            self.games.setCurrentRow(0)
        else:
            self.detail.setText("未找到录制，请点击右上角“更改录制位置”。")
        self.status.setText(f"找到 {len(games)} 个游戏 · {self.source}")

    def show_game(self, item, previous=None):
        self.recordings.clear()
        self.preview.clear()
        self.preview.setText("点击录像，查看首帧")
        if not item:
            return
        appid, name, rows = item.data(Qt.UserRole)
        self.title.setText(name)
        self.detail.setText(f"{len(rows)} 段录像 · 勾选要导出的录像，点击行预览")
        for folder, size in rows:
            row = QTreeWidgetItem([recording_timestamp(folder).strftime("%Y-%m-%d  %H:%M:%S"), f"{size / 1e9:.2f} GB"])
            row.setData(0, Qt.UserRole, str(folder))
            row.setCheckState(0, Qt.Checked)
            self.recordings.addTopLevelItem(row)
        self.selection_changed()

    def selected(self):
        return [self.recordings.topLevelItem(i).data(0, Qt.UserRole)
                for i in range(self.recordings.topLevelItemCount())
                if self.recordings.topLevelItem(i).checkState(0) == Qt.Checked]

    def selection_changed(self, *args):
        count = len(self.selected())
        self.start.setText(f"导出所选录像 ({count})")
        self.start.setEnabled(count > 0 and not self.working)

    def check_all(self, checked):
        for i in range(self.recordings.topLevelItemCount()):
            self.recordings.topLevelItem(i).setCheckState(0, Qt.Checked if checked else Qt.Unchecked)

    def show_preview(self, item, previous=None):
        if not item or (self.preview_job and self.preview_job.isRunning()):
            return
        folder = Path(item.data(0, Qt.UserRole))
        self.preview.setText("正在读取首帧…")
        def action(log):
            with tempfile.TemporaryDirectory(prefix="steam-preview-") as temp:
                target = extract_first_frame([], Path(temp) / "frame.jpg", folder / "session.mpd")
                return (str(folder), target.read_bytes())
        def done(result):
            current = self.recordings.currentItem()
            if current and current.data(0, Qt.UserRole) == result[0]:
                pixmap = QPixmap()
                pixmap.loadFromData(result[1])
                self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.preview_job = Job(action, self)
        self.preview_job.result.connect(done)
        self.preview_job.failed.connect(lambda _: self.preview.setText("此录像首帧暂不可用"))
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
        output = self.output / safe_name(game)
        args = ["--source", str(self.source), "--output", str(output), "--appid", appid, "--game", game]
        for folder in selected:
            args += ["--recording", Path(folder).name]
        self.log.clear()
        self.status.setText(f"正在导出 {len(selected)} 段录像，请保持程序打开…")
        self.busy(True)
        # Library browsing stays usable while the snapshot of selected paths exports.
        for widget in [self.games, self.recordings, self.select_all, self.select_none]:
            widget.setEnabled(True)
        self.export_client.start(args)
        self.cancel.setVisible(True)
        self.cancel.setEnabled(True)

    def cancel_export(self):
        if self.export_client.isRunning():
            self.cancel.setEnabled(False)
            self.status.setText("正在取消导出并停止后台进程…")
            self.export_client.cancel()

    def export_finished(self):
        self.busy(False)
        if self.close_after_cancel:
            self.close_after_cancel = False
            self.close()

    def export_message(self, message):
        self.log.appendPlainText(message)
        self.status.setText(message[-160:])

    def closeEvent(self, event):
        if self.export_client.isRunning():
            self.close_after_cancel = True
            self.cancel_export()
            self.status.setText("正在取消导出，完成后关闭窗口…")
            event.ignore()
        elif any(job and job.isRunning() for job in [self.job, self.preview_job]):
            QMessageBox.information(self, "正在处理", "请等待当前操作完成后关闭程序。")
            event.ignore()
        else:
            event.accept()


def configure_app(app):
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in [(QPalette.Window, "#fafafa"), (QPalette.WindowText, "#202020"),
                        (QPalette.Base, "#ffffff"), (QPalette.AlternateBase, "#f6f6f6"),
                        (QPalette.Text, "#202020"), (QPalette.Button, "#f5f5f5"),
                        (QPalette.ButtonText, "#202020"), (QPalette.Highlight, "#dedede"),
                        (QPalette.HighlightedText, "#111111")]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)


def main():
    app = QApplication([])
    configure_app(app)
    smoke = "--self-test" in sys.argv
    window = SimpleApp(autoscan=not smoke)
    window.show()
    if smoke:
        for name in ("ffmpeg", "ffprobe"):
            binary = find_executable(name, find_executable("ffmpeg"))
            if not binary:
                raise RuntimeError(f"Missing bundled {name}")
            subprocess.run([str(binary), "-version"], check=True, capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
        if "--scan-self-test" in sys.argv:
            scan_library(window.source, force=True)
        QTimer.singleShot(100, app.quit)
    app.exec()
