import codecs
import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from reezsynth_jobs import (
    ROOT, PREFIX, build_plan, validate_row,
)


APP_NAME = "ReEzSynth-Windows-GUI"

THEME = """
QWidget {
    background: #252525;
    color: #b8b8b8;
    font-size: 12px;
}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTableWidget {
    background: #151515;
    border: 1px solid #454545;
    padding: 4px;
    selection-background-color: #007e6b;
    selection-color: white;
}
QPushButton {
    background: #383838;
    border: none;
    padding: 7px 12px;
}
QPushButton:hover { background: #505050; }
QPushButton[accent="true"] {
    background: #009f87;
    color: white;
}
QPushButton[accent="true"]:hover { background: #00b298; }
QPushButton:disabled {
    background: #303030;
    color: #666666;
}
QProgressBar {
    background: #151515;
    border: 1px solid #454545;
    text-align: center;
    color: white;
    min-height: 20px;
}
QProgressBar::chunk { background: #009f87; }
QHeaderView::section {
    background: #303030;
    color: #b8b8b8;
    border: none;
    padding: 6px;
}
QTableWidget { gridline-color: #383838; }
QTabWidget::pane { border: 1px solid #383838; }
QTabBar::tab {
    background: #303030;
    padding: 9px 15px;
}
QTabBar::tab:selected {
    background: #252525;
    border-bottom: 2px solid #009f87;
}
QTabBar::tab:disabled { color: #666666; }
"""


class FolderEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setPlaceholderText("Drop a directory here, or Select")
        self.setToolTip("Drop one existing directory directly onto this field.")

    def dropped_folder(self, event):
        if not self.isEnabled() or not event.mimeData().hasUrls():
            return None

        urls = event.mimeData().urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None

        try:
            path = Path(urls[0].toLocalFile())
            return str(path) if path.is_dir() else None
        except (OSError, ValueError):
            return None

    def dragEnterEvent(self, event):
        if self.dropped_folder(event) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        path = self.dropped_folder(event)
        if path is None:
            event.ignore()
            return
        self.setText(path)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME + " - v0.3")
        self.resize(1320, 820)

        self.rows = []
        self.video = {}
        self.keys = {}
        self.padding = 3
        self.locked = []
        self.busy = False
        self.loading_project = False
        self.project_file = None
        self.batch = None
        self.pending = []
        self.current = None
        self.cancelled = False
        self.completed_work = 0
        self.total_work = 1
        self.settled = True

        self.scan_timer = QTimer(self)
        self.scan_timer.setSingleShot(True)
        self.scan_timer.timeout.connect(self.rebuild_queue)

        self.process = QProcess(self)
        self.process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )
        self.process.readyReadStandardOutput.connect(
            lambda: self.read_stream("out")
        )
        self.process.readyReadStandardError.connect(
            lambda: self.read_stream("err")
        )
        self.process.finished.connect(self.job_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.reset_streams()

        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)

        title = QLabel("ReEzSynth")
        title.setStyleSheet(
            "color: #009f87; font-size: 25px; font-style: italic;"
        )
        layout.addWidget(title)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        video_page = QWidget()
        page = QVBoxLayout(video_page)
        self.tabs.addTab(video_page, "Video / Keyframes")

        for name in ("Image Synthesis (planned)", "Blend / Flow (planned)"):
            index = self.tabs.addTab(QWidget(), name)
            self.tabs.setTabEnabled(index, False)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(10000)
        self.tabs.addTab(self.log, "Diagnostics / Log")

        toolbar = QHBoxLayout()
        for text, callback in (
            ("Open", self.open_project),
            ("Save", lambda: self.save_project(False)),
            ("Save As", lambda: self.save_project(True)),
            ("Scan / Rebuild Queue", lambda: self.rebuild_queue(True)),
        ):
            button = self.button(text, callback)
            toolbar.addWidget(button)
            self.locked.append(button)
        toolbar.addStretch()
        page.addLayout(toolbar)

        form = QFormLayout()
        page.addLayout(form)

        self.project_dir = self.path_row(form, "Project directory")
        self.keyframe_dir = self.path_row(form, "Keyframes")
        self.video_dir = self.path_row(form, "Video frames")
        self.project_dir.setText(str(ROOT / "reezsynth_projects"))

        self.keyframe_dir.textChanged.connect(self.schedule_scan)
        self.video_dir.textChanged.connect(self.schedule_scan)

        options = QHBoxLayout()
        options.addWidget(QLabel("EzSynth preset:"))
        self.quality = QComboBox()
        self.quality.addItems(["Preview", "Standard"])
        options.addWidget(self.quality)

        options.addWidget(QLabel("Processing size:"))
        self.resolution = QComboBox()
        self.resolution.addItem("Maximum width 512 - preview", 512)
        self.resolution.addItem("Maximum width 960", 960)
        self.resolution.addItem("Original resolution", 0)
        options.addWidget(self.resolution)
        options.addStretch()
        page.addLayout(options)
        self.locked.extend([self.quality, self.resolution])

        self.summary = QLabel(
            "Select the source-frame and keyframe directories to build the queue."
        )
        self.summary.setWordWrap(True)
        page.addWidget(self.summary)

        note = QLabel(
            "Stops are inclusive. ← / → enable backward / forward propagation. "
            "Changing either input directory rebuilds the queue and resets its ranges.\n"
            "Each job has one keyframe and its own output sequence. "
            "No cross-keyframe blending is performed."
        )
        note.setWordWrap(True)
        page.addWidget(note)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "", "Stop", "←", "Keyframe", "→", "Stop",
            "Output subfolder", "Status", "%", "",
        ])
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        page.addWidget(self.table)

        actions = QHBoxLayout()
        self.run_all = self.button(
            "Run All", lambda: self.run_rows(list(self.rows)), True
        )
        self.stop = self.button("Stop Queue", self.stop_queue)
        self.open_output = self.button("Open Outputs", self.open_outputs)
        self.open_output.setEnabled(False)

        actions.addStretch()
        actions.addWidget(self.open_output)
        actions.addWidget(self.stop)
        actions.addWidget(self.run_all)
        page.addLayout(actions)

        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.overall = QProgressBar()
        self.overall.setRange(0, 100)
        self.overall.setValue(0)
        self.overall.setFormat("Queue: %p%")
        self.overall.setToolTip(
            "Work-weighted queue progress, not an estimated remaining time."
        )
        layout.addWidget(self.overall)

        self.set_busy(False)

    def button(self, text, callback, accent=False):
        button = QPushButton(text)
        button.clicked.connect(callback)
        if accent:
            button.setProperty("accent", True)
        return button

    def path_row(self, form, label):
        field = FolderEdit()
        select = self.button(
            "Select", lambda: self.choose_folder(field, label)
        )
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(field)
        box.addWidget(select)
        form.addRow(label, row)
        self.locked.extend([field, select])
        return field

    def choose_folder(self, field, label):
        selected = QFileDialog.getExistingDirectory(self, label)
        if selected:
            field.setText(selected)

    def path_value(self, field):
        text = field.text().strip().strip('"')
        if not text:
            raise ValueError("A required directory field is empty.")
        return str(Path(text).expanduser().resolve())

    def schedule_scan(self, *_):
        if not self.busy and not self.loading_project:
            self.scan_timer.start(500)

    def rebuild_queue(self, show_error=False):
        if self.busy:
            return False

        self.scan_timer.stop()
        self.rows.clear()
        self.table.setRowCount(0)

        try:
            self.video, self.keys, self.padding, definitions = build_plan(
                self.path_value(self.video_dir),
                self.path_value(self.keyframe_dir),
            )
            for definition in definitions:
                self.add_row(definition)

            self.summary.setText(
                f"{len(self.video)} source frames: "
                f"{min(self.video)}–{max(self.video)} | "
                f"{len(self.rows)} keyframe jobs"
            )
            self.set_busy(False)
            return True

        except Exception as exc:
            self.summary.setText(str(exc))
            self.set_busy(False)
            if show_error:
                QMessageBox.warning(self, "Cannot build queue", str(exc))
            return False

    def add_row(self, definition):
        definition = validate_row(definition, self.video, self.keys)
        key = definition["key"]

        row = {
            "key": key,
            "start": QSpinBox(),
            "end": QSpinBox(),
            "reverse": QCheckBox(),
            "forward": QCheckBox(),
            "folder": QLineEdit(definition["folder"]),
            "state": QLabel("Ready"),
            "bar": QProgressBar(),
        }

        row["start"].setRange(min(self.video), key)
        row["end"].setRange(key, max(self.video))
        row["start"].setValue(definition["start"])
        row["end"].setValue(definition["end"])
        row["reverse"].setChecked(definition["reverse"])
        row["forward"].setChecked(definition["forward"])
        row["bar"].setRange(0, 100)
        row["bar"].setValue(0)
        row["bar"].setMinimumWidth(90)
        row["bar"].setFormat("%p%")
        row["state"].setMinimumWidth(130)

        row["remove"] = self.button(
            "×", lambda checked=False, r=row: self.remove_row(r)
        )
        row["synth"] = self.button(
            "Synth", lambda checked=False, r=row: self.run_rows([r]), True
        )

        index = self.table.rowCount()
        self.table.insertRow(index)
        self.table.setRowHeight(index, 43)

        item = QTableWidgetItem(f"{key:0{self.padding}d}")
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        )
        item.setToolTip(str(self.keys[key]))
        self.table.setItem(index, 3, item)

        for column, field in (
            (0, "remove"), (1, "start"), (2, "reverse"),
            (4, "forward"), (5, "end"), (6, "folder"),
            (7, "state"), (8, "bar"), (9, "synth"),
        ):
            self.table.setCellWidget(index, column, row[field])

        row["reverse"].toggled.connect(
            lambda enabled, r=row:
            r["start"].setEnabled(enabled and not self.busy)
        )
        row["forward"].toggled.connect(
            lambda enabled, r=row:
            r["end"].setEnabled(enabled and not self.busy)
        )

        self.rows.append(row)

    def remove_row(self, row):
        if self.busy:
            return
        index = self.rows.index(row)
        self.table.removeRow(index)
        self.rows.pop(index)
        self.set_busy(False)

    def definition(self, row):
        return {
            "key": row["key"],
            "start": row["start"].value(),
            "end": row["end"].value(),
            "reverse": row["reverse"].isChecked(),
            "forward": row["forward"].isChecked(),
            "folder": row["folder"].text().strip(),
        }

    def save_project(self, save_as=False):
        try:
            if not self.rows:
                raise ValueError("Build a queue before saving the project.")

            data = {
                "format": APP_NAME,
                "version": 1,
                "project_dir": self.path_value(self.project_dir),
                "video_dir": self.path_value(self.video_dir),
                "keyframe_dir": self.path_value(self.keyframe_dir),
                "quality": self.quality.currentText(),
                "max_width": self.resolution.currentData(),
                "rows": [
                    validate_row(self.definition(row), self.video, self.keys)
                    for row in self.rows
                ],
            }

            path = self.project_file
            if save_as or path is None:
                selected, _ = QFileDialog.getSaveFileName(
                    self, "Save project",
                    str(ROOT / "project.reezsynth.json"),
                    "ReEzSynth project (*.json)",
                )
                if not selected:
                    return
                path = Path(selected)

            path.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            self.project_file = path
            self.status.setText(f"Project saved: {path}")

        except Exception as exc:
            QMessageBox.warning(self, "Cannot save project", str(exc))

    def open_project(self):
        selected, _ = QFileDialog.getOpenFileName(
            self, "Open ReEzSynth project", "",
            "ReEzSynth project (*.json)",
        )
        if not selected:
            return

        try:
            data = json.loads(Path(selected).read_text(encoding="utf-8"))
            if data.get("format") != APP_NAME or data.get("version") != 1:
                raise ValueError("Unsupported project format.")

            if data["quality"] not in {"Preview", "Standard"}:
                raise ValueError("Unknown quality preset.")
            if data["max_width"] not in {0, 512, 960}:
                raise ValueError("Unknown processing size.")

            video, keys, padding, _ = build_plan(
                data["video_dir"], data["keyframe_dir"]
            )
            definitions = [
                validate_row(row, video, keys) for row in data["rows"]
            ]
            if len({row["key"] for row in definitions}) != len(definitions):
                raise ValueError("Project contains duplicate keyframe rows.")

            self.loading_project = True
            self.scan_timer.stop()

            self.project_dir.setText(data["project_dir"])
            self.video_dir.setText(data["video_dir"])
            self.keyframe_dir.setText(data["keyframe_dir"])
            self.quality.setCurrentText(data["quality"])
            self.resolution.setCurrentIndex(
                self.resolution.findData(data["max_width"])
            )

            self.video, self.keys, self.padding = video, keys, padding
            self.rows.clear()
            self.table.setRowCount(0)

            for definition in definitions:
                self.add_row(definition)

            self.project_file = Path(selected)
            self.summary.setText(
                f"{len(video)} source frames | {len(self.rows)} saved jobs"
            )
            self.status.setText(f"Project loaded: {selected}")
            self.set_busy(False)

        except Exception as exc:
            QMessageBox.warning(self, "Cannot open project", str(exc))
        finally:
            self.loading_project = False

    def run_rows(self, rows):
        if self.busy:
            return

        try:
            if not rows:
                raise ValueError("There are no jobs to render.")

            # Rescan before starting; don't trust a stale directory listing.
            video, keys, padding, _ = build_plan(
                self.path_value(self.video_dir),
                self.path_value(self.keyframe_dir),
            )

            planned = []
            folders = set()

            for row in rows:
                definition = validate_row(
                    self.definition(row), video, keys
                )

                folder_key = definition["folder"].casefold()
                if folder_key in folders:
                    raise ValueError("Two selected jobs use the same output folder.")
                folders.add(folder_key)

                key = definition["key"]
                start = definition["start"] if definition["reverse"] else key
                end = definition["end"] if definition["forward"] else key

                frames = [
                    [number, str(path)]
                    for number, path in video.items()
                    if start <= number <= end
                ]

                planned.append((row, definition, frames, str(keys[key])))

            project_root = Path(self.path_value(self.project_dir))
            batch = project_root / "renders" / datetime.now().strftime(
                "batch_%Y%m%d_%H%M%S_%f"
            )
            batch.mkdir(parents=True, exist_ok=False)

            records = []
            for row, definition, frames, style in planned:
                destination = (batch / definition["folder"]).resolve()
                if not destination.is_relative_to(batch.resolve()):
                    raise ValueError("Output directory escapes the batch directory.")

                destination.mkdir(parents=True, exist_ok=True)

                job = {
                    "key": definition["key"],
                    "style": style,
                    "frames": frames,
                    "padding": padding,
                    "quality": self.quality.currentText(),
                    "max_width": self.resolution.currentData(),
                    "output": str(destination),
                }

                job_path = destination / "job.json"
                job_path.write_text(
                    json.dumps(job, indent=2), encoding="utf-8"
                )

                records.append({
                    "row": row,
                    "job_path": job_path,
                    "output": destination,
                    "weight": max(1, len(frames) - 1),
                })

            self.scan_timer.stop()
            self.batch = batch
            self.pending = records
            self.current = None
            self.cancelled = False
            self.completed_work = 0
            self.total_work = sum(record["weight"] for record in records)
            self.overall.setValue(0)
            self.log.clear()
            self.open_output.setEnabled(True)

            for record in records:
                record["row"]["state"].setText("Queued")
                record["row"]["bar"].setValue(0)

            self.set_busy(True)
            self.start_next()

        except Exception as exc:
            QMessageBox.warning(self, "Cannot start queue", str(exc))

    def start_next(self):
        if not self.busy or self.cancelled:
            return

        if not self.pending:
            self.overall.setValue(100)
            self.status.setText("Queue complete")
            self.set_busy(False)
            return

        self.current = self.pending.pop(0)
        self.settled = False
        self.reset_streams()

        row = self.current["row"]
        row["state"].setText("Starting")
        self.status.setText(f"Starting keyframe {row['key']}")

        self.log.appendPlainText(
            f"\n=== Keyframe {row['key']} ===\n"
            f"Output: {self.current['output']}"
        )

        self.process.setWorkingDirectory(str(ROOT))
        self.process.start(
            sys.executable,
            [
                "-X", "utf8", "-u",
                str(ROOT / "reezsynth_jobs.py"),
                str(self.current["job_path"]),
            ],
        )

    def reset_streams(self):
        self.decoders = {
            name: codecs.getincrementaldecoder("utf-8")(errors="replace")
            for name in ("out", "err")
        }
        self.buffers = {"out": "", "err": ""}
        self.streams_closed = False

    def read_stream(self, name, final=False):
        if self.streams_closed:
            return

        getter = (
            self.process.readAllStandardOutput
            if name == "out"
            else self.process.readAllStandardError
        )
        text = self.decoders[name].decode(bytes(getter()), final=final)
        self.buffers[name] += text.replace("\r", "\n")

        while "\n" in self.buffers[name]:
            line, self.buffers[name] = self.buffers[name].split("\n", 1)
            self.consume_line(name, line)

        if final and self.buffers[name]:
            self.consume_line(name, self.buffers[name])
            self.buffers[name] = ""

    def consume_line(self, name, line):
        if not line.strip():
            return

        if name == "out" and line.startswith(PREFIX):
            try:
                message = json.loads(line[len(PREFIX):])
                percent = max(0, min(99, int(message["percent"])))
                stage = str(message["stage"])
            except (ValueError, KeyError, TypeError):
                self.log.appendPlainText(line)
                return

            if self.current and not self.cancelled:
                row = self.current["row"]
                percent = max(row["bar"].value(), percent)
                row["bar"].setValue(percent)
                row["state"].setText(stage)
                self.status.setText(f"Keyframe {row['key']}: {stage}")
                self.update_overall(percent)
            return

        self.log.appendPlainText(line)

    def update_overall(self, percent=0):
        active = (
            self.current["weight"] * percent / 100
            if self.current else 0
        )
        value = int(
            100 * (self.completed_work + active) / self.total_work
        )
        self.overall.setValue(min(99, value))

    def job_finished(self, exit_code, exit_status):
        if self.settled or self.current is None:
            return

        self.settled = True
        self.read_stream("out", final=True)
        self.read_stream("err", final=True)
        self.streams_closed = True

        record = self.current
        row = record["row"]
        successful = (
            exit_code == 0
            and exit_status == QProcess.ExitStatus.NormalExit
            and (record["output"] / "COMPLETE.txt").is_file()
        )

        if self.cancelled:
            row["state"].setText("Stopped")
            self.end_queue("Queue stopped - output may be incomplete")
        elif not successful:
            row["state"].setText("Failed")
            self.end_queue(
                f"Queue halted: keyframe {row['key']} failed. See log."
            )
            self.tabs.setCurrentWidget(self.log)
        else:
            row["state"].setText("Complete")
            row["bar"].setValue(100)
            self.completed_work += record["weight"]
            self.current = None
            self.update_overall()
            QTimer.singleShot(0, self.start_next)

    def process_error(self, error):
        if not self.cancelled:
            self.log.appendPlainText(
                "Worker error: " + self.process.errorString()
            )

        if error == QProcess.ProcessError.FailedToStart:
            self.job_finished(-1, QProcess.ExitStatus.CrashExit)

    def end_queue(self, message):
        for record in self.pending:
            record["row"]["state"].setText("Not run")
        self.pending.clear()
        self.current = None
        self.status.setText(message)
        self.set_busy(False)

    def stop_queue(self):
        if not self.busy:
            return

        self.cancelled = True
        self.status.setText("Stopping queue...")
        self.stop.setEnabled(False)

        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        else:
            self.end_queue("Queue stopped")

    def set_busy(self, busy):
        self.busy = busy
        for widget in self.locked:
            widget.setEnabled(not busy)

        for row in self.rows:
            for field in ("reverse", "forward", "folder", "remove", "synth"):
                row[field].setEnabled(not busy)
            row["start"].setEnabled(
                not busy and row["reverse"].isChecked()
            )
            row["end"].setEnabled(
                not busy and row["forward"].isChecked()
            )

        self.run_all.setEnabled(not busy and bool(self.rows))
        self.stop.setEnabled(busy)

    def open_outputs(self):
        if self.batch:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.batch)))

    def closeEvent(self, event):
        if self.busy:
            answer = QMessageBox.question(
                self, "Queue running",
                "Stop the queue and close? Unsaved results will be lost.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

            self.stop_queue()
            if self.process.state() != QProcess.ProcessState.NotRunning:
                if not self.process.waitForFinished(5000):
                    event.ignore()
                    return

        self.scan_timer.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(THEME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())