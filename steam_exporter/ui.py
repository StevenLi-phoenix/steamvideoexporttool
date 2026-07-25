from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)

from .media import DEFAULT_PATTERN, format_bytes
from .worker import TaskThread


APP_TITLE = "Steam Video Exporter"
TOKEN_HELP = "Tokens: {game} {date} {time} {index} {source} {ext}"


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(980, 760)
        self.setMinimumSize(820, 650)
        self.busy = False
        self.thread: TaskThread | None = None
        self.preview_thread: TaskThread | None = None
        self.source_edit = QLineEdit()
        self.output_edit = QLineEdit()
        self.format_combo = QComboBox()
        self.format_combo.addItems(["mp4", "mov", "flv"])
        self.custom_limit = QSpinBox()
        self.custom_limit.setRange(1, 999999)
        self.custom_limit.setValue(16)
        self.limit_16 = QRadioButton("16 GB")
        self.limit_64 = QRadioButton("64 GB")
        self.limit_custom = QRadioButton("Custom")
        self.limit_16.setChecked(True)
        self.pattern_edit = QLineEdit(DEFAULT_PATTERN)
        self.game_value = QLabel("Not checked yet")
        self.status_value = QLabel("Choose an input folder to begin.")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.recording_list = QListWidget()
        self.recording_list.setMinimumHeight(150)
        self.preview_label = QLabel("Select a recording and click Preview first frame")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(320, 180)
        self.preview_label.setObjectName("preview")
        self.preflight_button = QPushButton("Run preflight checks")
        self.convert_button = QPushButton("Convert")
        self.preview_button = QPushButton("Preview first frame")
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        body = QWidget()
        self.setCentralWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        title = QLabel(APP_TITLE)
        title.setObjectName("title")
        root.addWidget(title)
        subtitle = QLabel("Lossless remuxing for Steam Game Recording .m4s files")
        subtitle.setObjectName("subtitle")
        root.addWidget(subtitle)
        paths = QGroupBox("Folders")
        path_grid = QGridLayout(paths)
        path_grid.setContentsMargins(16, 16, 16, 16)
        self._path_row(path_grid, 0, "Input folder", self.source_edit, self._choose_source)
        self._path_row(path_grid, 1, "Output folder", self.output_edit, self._choose_output)
        root.addWidget(paths)
        settings = QGroupBox("Export settings")
        grid = QGridLayout(settings)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.addWidget(QLabel("Format"), 0, 0)
        grid.addWidget(self.format_combo, 0, 1)
        grid.addWidget(QLabel("Max output segment"), 1, 0)
        limits = QHBoxLayout()
        limits.setSpacing(12)
        for button in (self.limit_16, self.limit_64, self.limit_custom):
            limits.addWidget(button)
        limits.addWidget(self.custom_limit)
        limits.addWidget(QLabel("GB"))
        limits.addStretch()
        grid.addLayout(limits, 1, 1, 1, 3)
        grid.addWidget(QLabel("Filename pattern"), 2, 0)
        grid.addWidget(self.pattern_edit, 2, 1, 1, 3)
        tokens = QLabel(TOKEN_HELP)
        tokens.setObjectName("hint")
        grid.addWidget(tokens, 3, 1, 1, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        root.addWidget(settings)

        recordings = QGroupBox("Recordings to export")
        recording_layout = QVBoxLayout(recordings)
        recording_layout.setContentsMargins(12, 12, 12, 12)
        recording_layout.addWidget(self.recording_list)
        recording_actions = QHBoxLayout()
        select_all = QPushButton("Select all")
        clear_all = QPushButton("Clear all")
        select_all.clicked.connect(lambda: self._set_all_recordings(Qt.Checked))
        clear_all.clicked.connect(lambda: self._set_all_recordings(Qt.Unchecked))
        self.preview_button.clicked.connect(self.preview_selected)
        recording_actions.addWidget(select_all)
        recording_actions.addWidget(clear_all)
        recording_actions.addWidget(self.preview_button)
        recording_actions.addStretch()
        recording_layout.addLayout(recording_actions)
        preview_row = QHBoxLayout()
        preview_row.addWidget(self.preview_label)
        preview_row.addStretch()
        recording_layout.addLayout(preview_row)
        root.addWidget(recordings)
        detected = QFrame()
        detected_layout = QHBoxLayout(detected)
        detected_layout.setContentsMargins(4, 0, 4, 0)
        label = QLabel("Detected game")
        label.setObjectName("fieldLabel")
        detected_layout.addWidget(label)
        detected_layout.addWidget(self.game_value)
        detected_layout.addStretch()
        root.addWidget(detected)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.preflight_button.clicked.connect(self.run_preflight)
        self.convert_button.clicked.connect(self.start_conversion)
        self.convert_button.setObjectName("primary")
        actions.addWidget(self.preflight_button)
        actions.addWidget(self.convert_button)
        actions.addWidget(self.status_value)
        actions.addStretch()
        root.addLayout(actions)
        root.addWidget(self.progress_bar)
        log_group = QGroupBox("Activity")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(12, 12, 12, 12)
        log_layout.addWidget(self.log_edit)
        root.addWidget(log_group, 1)

    def _path_row(self, grid, row, label, edit, command):
        grid.addWidget(QLabel(label), row, 0)
        grid.addWidget(edit, row, 1, 1, 3)
        button = QPushButton("Browse")
        button.clicked.connect(command)
        grid.addWidget(button, row, 4)

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f6f8fb; color: #172033; font-family: 'Segoe UI'; font-size: 10pt; }
            QLabel#title { font-size: 26pt; font-weight: 700; color: #14213d; }
            QLabel#subtitle, QLabel#hint { color: #667085; }
            QLabel#fieldLabel { font-weight: 600; color: #344054; }
            QGroupBox { background: #ffffff; border: 1px solid #d8dee9; border-radius: 10px; margin-top: 10px; padding-top: 8px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; color: #344054; }
            QLineEdit, QComboBox, QSpinBox, QPlainTextEdit { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 7px; padding: 8px; selection-background-color: #2563eb; }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus { border: 2px solid #5b8def; padding: 7px; }
            QPushButton { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 7px; padding: 9px 16px; font-weight: 600; }
            QPushButton:hover { background: #eef4ff; border-color: #8bb0f5; }
            QPushButton#primary { background: #2563eb; border-color: #2563eb; color: #ffffff; }
            QPushButton#primary:hover { background: #1d4ed8; }
            QPushButton:disabled { color: #98a2b3; background: #eef1f5; }
            QProgressBar { height: 8px; border: 0; border-radius: 4px; background: #e5e7eb; text-align: center; }
            QProgressBar::chunk { border-radius: 4px; background: #2563eb; }
            QPlainTextEdit { font-family: Consolas; font-size: 9pt; }
            QLabel#preview { background: #101828; color: #98a2b3; border-radius: 8px; padding: 8px; }
            QListWidget { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 7px; padding: 4px; }
            QListWidget::item { padding: 8px; border-radius: 5px; }
            QListWidget::item:selected { background: #e6efff; color: #14213d; }
        """)

    def _choose_source(self):
        selected = QFileDialog.getExistingDirectory(self, "Choose Steam recording folder")
        if selected:
            self.source_edit.setText(selected)
            if not self.output_edit.text():
                self.output_edit.setText(str(Path(selected) / "exports"))

    def _choose_output(self):
        selected = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if selected:
            self.output_edit.setText(selected)

    def _set_busy(self, busy):
        self.busy = busy
        self.preflight_button.setEnabled(not busy)
        self.convert_button.setEnabled(not busy)
        self.progress_bar.setRange(0, 0 if busy else 100)

    def _log(self, message):
        self.log_edit.appendPlainText(str(message))

    def _clear_log(self):
        self.log_edit.clear()
        self.progress_bar.setValue(0)

    def _set_all_recordings(self, state):
        for index in range(self.recording_list.count()):
            self.recording_list.item(index).setCheckState(state)

    def _populate_recordings(self, result):
        self.recording_list.clear()
        for recording in result.recordings:
            item = QListWidgetItem(f"{recording.folder.name}   |   {recording.game_name}   |   {len(recording.files):,} chunks")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, recording)
            self.recording_list.addItem(item)
        if self.recording_list.count():
            self.recording_list.setCurrentRow(0)

    def _selected_folders(self):
        selected = []
        for index in range(self.recording_list.count()):
            item = self.recording_list.item(index)
            if item.checkState() == Qt.Checked:
                selected.append(str(item.data(Qt.UserRole).folder))
        return selected

    def preview_selected(self):
        item = self.recording_list.currentItem()
        if not item or not item.data(Qt.UserRole):
            QMessageBox.information(self, APP_TITLE, "Select a recording first.")
            return
        recording = item.data(Qt.UserRole)
        self.preview_button.setEnabled(False)
        self.preview_label.setText("Creating preview...")
        thread = TaskThread("preview", (recording.files,), self)
        self.preview_thread = thread
        thread.preview_signal.connect(self._show_preview)
        thread.error_signal.connect(self._thread_error)
        thread.finished.connect(lambda: self.preview_button.setEnabled(True))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _show_preview(self, path):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview_label.setText("Preview could not be loaded")
        else:
            self.preview_label.setPixmap(pixmap)
            self.preview_label.setScaledContents(False)
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass

    def _connect_thread(self, thread):
        self.thread = thread
        thread.log_signal.connect(self._log)
        thread.progress_signal.connect(lambda value: self.progress_bar.setValue(int(value * 100)))
        thread.game_signal.connect(self.game_value.setText)
        thread.error_signal.connect(self._thread_error)
        thread.done_signal.connect(self._thread_done)
        thread.finished.connect(lambda: self._set_busy(False))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _thread_error(self, message):
        self.status_value.setText("Operation failed.")
        QMessageBox.critical(self, APP_TITLE, message)

    def _thread_done(self):
        self.status_value.setText("Conversion complete.")
        QMessageBox.information(self, APP_TITLE, "Conversion complete.")

    def run_preflight(self):
        if self.busy:
            return
        self._set_busy(True)
        self._clear_log()
        self.status_value.setText("Running preflight checks...")
        thread = TaskThread("preflight", (self.source_edit.text(), self.output_edit.text()), self)
        thread.preflight_signal.connect(self._show_preflight)
        self._connect_thread(thread)

    def _show_preflight(self, result):
        self.game_value.setText(result.game_name)
        self._populate_recordings(result)
        self._log("--- PREFLIGHT ---")
        self._log(f"Game name: {result.game_name}")
        self._log(f"Recordings: {len(result.recordings)} | Files: {len(result.files)} | Input size: {format_bytes(result.total_bytes)} | Free space: {format_bytes(result.free_bytes)}")
        for warning in result.warnings:
            self._log("WARNING: " + warning)
        for error in result.errors:
            self._log("ERROR: " + error)
        self.status_value.setText("Preflight passed." if result.ok else "Preflight found issues.")
        if result.ok:
            QMessageBox.information(self, APP_TITLE, "Preflight passed.")
        else:
            QMessageBox.critical(self, APP_TITLE, "Preflight failed. Fix the issues shown in Activity.")

    def _limit_bytes(self):
        gb = 16 if self.limit_16.isChecked() else 64 if self.limit_64.isChecked() else self.custom_limit.value()
        return int(gb * 1024**3)

    def start_conversion(self):
        if self.busy:
            return
        self._set_busy(True)
        self._clear_log()
        self.status_value.setText("Running lossless remux...")
        self.progress_bar.setRange(0, 100)
        selected = self._selected_folders()
        if not selected:
            self._set_busy(False)
            QMessageBox.information(self, APP_TITLE, "Select at least one recording folder to export.")
            return
        args = (self.source_edit.text(), self.output_edit.text(), self.format_combo.currentText(), self._limit_bytes(), self.pattern_edit.text(), selected)
        self._connect_thread(TaskThread("convert", args, self))
