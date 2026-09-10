import codecs
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QPointF,
    QProcess,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from reezsynth_jobs import (
    ROOT,
    PREFIX,
    build_plan,
    validate_row,
)


APP_NAME = "ReEzSynth-Windows-GUI"
SESSION_PREFIX = "@@REEZSYNTH_SESSION@@"
SHUTDOWN_TIMEOUT_MS = 30_000
ROW_HEIGHT = 36
STEP_COLUMN_WIDTH = 30

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
QSpinBox#QueueNumberEditor {
    background: #151515;
    border: none;
    padding: 0px 5px;
}
QSpinBox#QueueNumberEditor:disabled {
    color: #666666;
}
"""


class FolderEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setPlaceholderText("Drop a directory here, or Select")
        self.setToolTip(
            "Drop one existing directory directly onto this field."
        )

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


class StepButton(QAbstractButton):
    """An arrow button occupying half of the frame control."""

    def __init__(self, direction):
        super().__init__()
        self.direction = direction

        self.setAutoRepeat(True)
        self.setAutoRepeatDelay(350)
        self.setAutoRepeatInterval(80)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )

        description = (
            "Increase frame number"
            if direction > 0
            else "Decrease frame number"
        )
        self.setToolTip(description)
        self.setAccessibleName(description)

    def sizeHint(self):
        return QSize(STEP_COLUMN_WIDTH, ROW_HEIGHT // 2)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        width = self.width()
        height = self.height()
        if width < 1 or height < 1:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.isEnabled():
            background, foreground = "#303030", "#777777"
        elif self.isDown():
            background, foreground = "#007e6b", "#ffffff"
        elif self.underMouse():
            background, foreground = "#555555", "#ffffff"
        else:
            background, foreground = "#414141", "#eeeeee"

        painter.fillRect(self.rect(), QColor(background))
        painter.setPen(QColor("#626262"))
        painter.drawLine(0, 0, width - 1, 0)

        center_x = width / 2
        center_y = height / 2
        half_width = min(6.5, width * 0.24)
        half_height = min(4.0, height * 0.24)

        if self.direction > 0:
            points = [
                QPointF(center_x, center_y - half_height),
                QPointF(center_x - half_width, center_y + half_height),
                QPointF(center_x + half_width, center_y + half_height),
            ]
        else:
            points = [
                QPointF(center_x - half_width, center_y - half_height),
                QPointF(center_x + half_width, center_y - half_height),
                QPointF(center_x, center_y + half_height),
            ]

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(foreground))
        painter.drawPolygon(QPolygonF(points))


class FullHeightSpinBox(QWidget):
    """Editable frame number with full-height arrow controls."""

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(92)

        self.number = QSpinBox()
        self.number.setObjectName("QueueNumberEditor")
        self.number.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.number.setKeyboardTracking(False)
        self.number.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self.up = StepButton(1)
        self.down = StepButton(-1)

        column = QWidget()
        column.setFixedWidth(STEP_COLUMN_WIDTH)

        arrows = QVBoxLayout(column)
        arrows.setContentsMargins(0, 0, 0, 0)
        arrows.setSpacing(0)
        arrows.addWidget(self.up, 1)
        arrows.addWidget(self.down, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.number, 1)
        layout.addWidget(column)

        self.up.clicked.connect(self.number.stepUp)
        self.down.clicked.connect(self.number.stepDown)
        self.number.valueChanged.connect(self.update_buttons)

        self.update_buttons()

    def sizeHint(self):
        return QSize(92, ROW_HEIGHT)

    def update_buttons(self, *_):
        value = self.number.value()
        self.up.setEnabled(value < self.number.maximum())
        self.down.setEnabled(value > self.number.minimum())

    def setRange(self, minimum, maximum):
        self.number.setRange(minimum, maximum)
        self.update_buttons()

    def setValue(self, value):
        self.number.setValue(value)
        self.update_buttons()

    def value(self):
        self.number.interpretText()
        return self.number.value()

    def minimum(self):
        return self.number.minimum()

    def maximum(self):
        return self.number.maximum()


class CenteredToggle(QAbstractButton):
    """Centered propagation toggle with a full-cell hit area."""

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(32)
        self.toggled.connect(lambda _: self.update())

    def sizeHint(self):
        return QSize(36, ROW_HEIGHT)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#252525"))

        size = max(
            2.0,
            min(24.0, self.width() - 8.0, self.height() - 8.0),
        )
        x = (self.width() - size) / 2
        y = (self.height() - size) / 2

        if not self.isEnabled():
            fill, border, tick = "#333333", "#555555", "#888888"
        else:
            fill = "#009f87" if self.isChecked() else "#151515"
            border = "#00c9aa" if self.hasFocus() else "#777777"
            tick = "#ffffff"

        border_pen = QPen(QColor(border))
        border_pen.setWidthF(1.2)
        painter.setPen(border_pen)
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(QRectF(x, y, size, size), 2, 2)

        if self.isChecked():
            path = QPainterPath()
            path.moveTo(x + size * 0.19, y + size * 0.51)
            path.lineTo(x + size * 0.43, y + size * 0.75)
            path.lineTo(x + size * 0.82, y + size * 0.28)

            tick_pen = QPen(QColor(tick))
            tick_pen.setWidthF(max(1.5, size * 0.12))
            tick_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            tick_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

            painter.setPen(tick_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
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

        self.shared_this_run = False
        self.session_closing = False
        self.session_error = None
        self.job_sent = False
        self.queue_started_at = None

        self.process = None
        self.finalizing_process = False
        self.shutdown_process = None
        self.queue_generation = 0
        self.close_when_idle = False

        self.preferences = QSettings("ReEzSynth", APP_NAME)

        self.scan_timer = QTimer(self)
        self.scan_timer.setSingleShot(True)
        self.scan_timer.timeout.connect(self.rebuild_queue)

        self.shutdown_timer = QTimer(self)
        self.shutdown_timer.setSingleShot(True)
        self.shutdown_timer.setInterval(SHUTDOWN_TIMEOUT_MS)
        self.shutdown_timer.timeout.connect(self.worker_shutdown_timeout)

        self.reset_streams()
        self.build_interface()
        self.set_busy(False)

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def build_interface(self):
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
            "Select the source-frame and keyframe directories "
            "to build the queue."
        )
        self.summary.setWordWrap(True)
        page.addWidget(self.summary)

        note = QLabel(
            "Stops are inclusive. ← / → enable backward / forward "
            "propagation. Changing either input directory rebuilds "
            "the queue and resets its ranges.\n"
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

        vertical = self.table.verticalHeader()
        vertical.setVisible(False)
        vertical.setMinimumSectionSize(32)
        vertical.setDefaultSectionSize(ROW_HEIGHT)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(
            6, QHeaderView.ResizeMode.Stretch
        )
        for column in (2, 4):
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.Fixed
            )
            header.resizeSection(column, 36)

        page.addWidget(self.table)

        actions = QHBoxLayout()
        self.run_all = self.button(
            "Run All",
            lambda: self.run_rows(list(self.rows)),
            True,
        )
        self.stop = self.button("Stop Queue", self.stop_queue)
        self.open_output = self.button(
            "Open Outputs", self.open_outputs
        )
        self.open_output.setEnabled(False)

        actions.addStretch()
        actions.addWidget(self.open_output)
        actions.addWidget(self.stop)
        actions.addWidget(self.run_all)
        page.addLayout(actions)

        settings_page = QWidget()
        settings_layout = QVBoxLayout(settings_page)

        self.reuse_worker = QCheckBox(
            "Reuse worker between renders (recommended)"
        )
        self.reuse_worker.setChecked(
            self.preferences.value(
                "reuse_queue_worker", True, type=bool
            )
        )
        self.reuse_worker.setStyleSheet(
            "QCheckBox::indicator { width: 20px; height: 20px; }"
        )
        self.reuse_worker.toggled.connect(
            lambda enabled: self.preferences.setValue(
                "reuse_queue_worker", enabled
            )
        )

        description = QLabel(
            "Speeds up queued renders while initializing the engine "
            "for each job. The worker exits when the queue ends to "
            "release memory.\n\n"
            "Disable to start a fresh worker for each render if "
            "memory usage grows or renders become unstable."
        )
        description.setWordWrap(True)

        settings_layout.addWidget(self.reuse_worker)
        settings_layout.addWidget(description)
        settings_layout.addStretch()
        self.tabs.addTab(settings_page, "Settings")
        self.locked.append(self.reuse_worker)

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

    # ------------------------------------------------------------------
    # Queue editing and project files
    # ------------------------------------------------------------------

    def schedule_scan(self, *_):
        if (
            not self.busy
            and not self.loading_project
            and not self.close_when_idle
        ):
            self.scan_timer.start(500)

    def rebuild_queue(self, show_error=False):
        if self.busy or self.close_when_idle:
            return False

        self.scan_timer.stop()
        self.rows.clear()
        self.table.setRowCount(0)
        self.video = {}
        self.keys = {}

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
                QMessageBox.warning(
                    self, "Cannot build queue", str(exc)
                )
            return False

    def add_row(self, definition):
        definition = validate_row(
            definition, self.video, self.keys
        )
        key = definition["key"]

        row = {
            "key": key,
            "start": FullHeightSpinBox(),
            "end": FullHeightSpinBox(),
            "reverse": CenteredToggle(),
            "forward": CenteredToggle(),
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

        for field, number_field, description in (
            ("reverse", "start", "Backward propagation"),
            ("forward", "end", "Forward propagation"),
        ):
            toggle = row[field]
            toggle.setToolTip(description)
            toggle.setAccessibleName(
                f"{description} for keyframe {key}"
            )
            toggle.toggled.connect(
                lambda enabled, r=row, target=number_field:
                r[target].setEnabled(enabled and not self.busy)
            )

        row["bar"].setRange(0, 100)
        row["bar"].setValue(0)
        row["bar"].setMinimumWidth(90)
        row["bar"].setFormat("%p%")

        row["state"].setMinimumWidth(130)
        row["state"].setAlignment(Qt.AlignmentFlag.AlignCenter)

        row["remove"] = self.button(
            "×",
            lambda checked=False, r=row: self.remove_row(r),
        )
        row["synth"] = self.button(
            "Synth",
            lambda checked=False, r=row: self.run_rows([r]),
            True,
        )
        row["synth"].setStyleSheet(
            "QPushButton { padding: 4px 10px; }"
        )
        row["remove"].setStyleSheet(
            "QPushButton { padding: 4px 8px; }"
        )

        index = self.table.rowCount()
        self.table.insertRow(index)
        self.table.setRowHeight(index, ROW_HEIGHT)

        item = QTableWidgetItem(f"{key:0{self.padding}d}")
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setToolTip(str(self.keys[key]))
        self.table.setItem(index, 3, item)

        for column, field in (
            (0, "remove"),
            (1, "start"),
            (2, "reverse"),
            (4, "forward"),
            (5, "end"),
            (6, "folder"),
            (7, "state"),
            (8, "bar"),
            (9, "synth"),
        ):
            self.table.setCellWidget(index, column, row[field])

        self.rows.append(row)
        row["start"].setEnabled(
            row["reverse"].isChecked() and not self.busy
        )
        row["end"].setEnabled(
            row["forward"].isChecked() and not self.busy
        )

    def remove_row(self, row):
        if self.busy or self.close_when_idle:
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
        if self.busy:
            return

        try:
            if not self.rows:
                raise ValueError(
                    "Build a queue before saving the project."
                )

            data = {
                "format": APP_NAME,
                "version": 1,
                "project_dir": self.path_value(self.project_dir),
                "video_dir": self.path_value(self.video_dir),
                "keyframe_dir": self.path_value(self.keyframe_dir),
                "quality": self.quality.currentText(),
                "max_width": self.resolution.currentData(),
                "rows": [
                    validate_row(
                        self.definition(row), self.video, self.keys
                    )
                    for row in self.rows
                ],
            }

            path = self.project_file
            if save_as or path is None:
                selected, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save project",
                    str(ROOT / "project.reezsynth.json"),
                    "ReEzSynth project (*.json)",
                )
                if not selected:
                    return
                path = Path(selected)

            path.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",
            )
            self.project_file = path
            self.status.setText(f"Project saved: {path}")

        except Exception as exc:
            QMessageBox.warning(
                self, "Cannot save project", str(exc)
            )

    def open_project(self):
        if self.busy:
            return

        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Open ReEzSynth project",
            "",
            "ReEzSynth project (*.json)",
        )
        if not selected:
            return

        try:
            data = json.loads(
                Path(selected).read_text(encoding="utf-8")
            )
            if (
                data.get("format") != APP_NAME
                or data.get("version") != 1
            ):
                raise ValueError("Unsupported project format.")

            if data["quality"] not in {"Preview", "Standard"}:
                raise ValueError("Unknown quality preset.")
            if data["max_width"] not in {0, 512, 960}:
                raise ValueError("Unknown processing size.")

            video, keys, padding, _ = build_plan(
                data["video_dir"], data["keyframe_dir"]
            )
            definitions = [
                validate_row(row, video, keys)
                for row in data["rows"]
            ]

            if len({row["key"] for row in definitions}) != len(definitions):
                raise ValueError(
                    "Project contains duplicate keyframe rows."
                )

            self.loading_project = True
            self.scan_timer.stop()

            self.project_dir.setText(data["project_dir"])
            self.video_dir.setText(data["video_dir"])
            self.keyframe_dir.setText(data["keyframe_dir"])
            self.quality.setCurrentText(data["quality"])
            self.resolution.setCurrentIndex(
                self.resolution.findData(data["max_width"])
            )

            self.video = video
            self.keys = keys
            self.padding = padding
            self.rows.clear()
            self.table.setRowCount(0)

            for definition in definitions:
                self.add_row(definition)

            self.project_file = Path(selected)
            self.summary.setText(
                f"{len(video)} source frames | "
                f"{len(self.rows)} saved jobs"
            )
            self.status.setText(f"Project loaded: {selected}")
            self.set_busy(False)

        except Exception as exc:
            QMessageBox.warning(
                self, "Cannot open project", str(exc)
            )
        finally:
            self.loading_project = False

    # ------------------------------------------------------------------
    # Queue preparation
    # ------------------------------------------------------------------

    def run_rows(self, rows):
        if self.busy or self.process is not None or self.close_when_idle:
            return

        shared = self.reuse_worker.isChecked()
        worker_script = ROOT / (
            "reezsynth_shared_worker.py"
            if shared
            else "reezsynth_jobs.py"
        )

        try:
            if not worker_script.is_file():
                raise ValueError(
                    f"Worker script not found: {worker_script}"
                )

            if not rows:
                raise ValueError("There are no jobs to render.")

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
                    raise ValueError(
                        "Two selected jobs use the same output folder."
                    )
                folders.add(folder_key)

                key = definition["key"]
                start = (
                    definition["start"]
                    if definition["reverse"]
                    else key
                )
                end = (
                    definition["end"]
                    if definition["forward"]
                    else key
                )

                frames = [
                    [number, str(path)]
                    for number, path in video.items()
                    if start <= number <= end
                ]

                planned.append(
                    (row, definition, frames, str(keys[key]))
                )

            project_root = Path(
                self.path_value(self.project_dir)
            )
            batch = project_root / "renders" / datetime.now().strftime(
                "batch_%Y%m%d_%H%M%S_%f"
            )
            batch.mkdir(parents=True, exist_ok=False)

            records = []

            for row, definition, frames, style in planned:
                destination = (
                    batch / definition["folder"]
                ).resolve()

                if not destination.is_relative_to(batch.resolve()):
                    raise ValueError(
                        "Output directory escapes the batch directory."
                    )

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
                    json.dumps(job, indent=2),
                    encoding="utf-8",
                )

                records.append({
                    "row": row,
                    "job_path": job_path,
                    "output": destination,
                    "weight": max(1, len(frames) - 1),
                })

        except Exception as exc:
            QMessageBox.warning(
                self, "Cannot start queue", str(exc)
            )
            return

        self.scan_timer.stop()
        self.shutdown_timer.stop()
        self.shutdown_process = None

        self.queue_generation += 1
        self.batch = batch
        self.pending = records
        self.current = None
        self.cancelled = False
        self.shared_this_run = shared
        self.session_closing = False
        self.session_error = None
        self.job_sent = False
        self.completed_work = 0
        self.total_work = sum(
            record["weight"] for record in records
        )

        self.overall.setValue(0)
        self.log.clear()
        self.open_output.setEnabled(True)

        for record in records:
            record["row"]["state"].setText("Queued")
            record["row"]["bar"].setValue(0)

        self.set_busy(True)
        self.start_next()

    def schedule_next(self):
        generation = self.queue_generation

        def advance():
            if (
                generation == self.queue_generation
                and self.busy
                and not self.cancelled
                and not self.close_when_idle
            ):
                self.start_next()

        QTimer.singleShot(0, advance)

    def start_next(self):
        if (
            not self.busy
            or self.cancelled
            or self.close_when_idle
            or self.session_closing
            or self.session_error is not None
            or self.finalizing_process
            or self.current is not None
        ):
            return

        if not self.pending:
            if self.shared_this_run:
                self.begin_worker_shutdown()
            else:
                self.overall.setValue(100)
                self.end_queue(
                    "Queue complete — all workers exited"
                )
            return

        self.current = self.pending.pop(0)
        self.job_sent = False

        row = self.current["row"]
        row["state"].setText("Starting")
        self.status.setText(f"Starting keyframe {row['key']}")

        mode = (
            "shared worker"
            if self.shared_this_run
            else "isolated worker"
        )
        self.log.appendPlainText(
            f"\n=== Keyframe {row['key']} - {mode} ===\n"
            f"Output: {self.current['output']}"
        )

        if self.shared_this_run:
            if self.process is None:
                self.start_worker(
                    ROOT / "reezsynth_shared_worker.py"
                )
            elif self.process.state() == QProcess.ProcessState.Running:
                self.send_current_job()
            else:
                self.fail_worker(
                    "Shared worker ended before the next job."
                )
        else:
            if self.process is not None:
                self.fail_worker(
                    "Previous isolated worker has not been finalized."
                )
                return

            self.start_worker(
                ROOT / "reezsynth_jobs.py",
                str(self.current["job_path"]),
            )

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    def worker_alive(self):
        return (
            self.process is not None
            and self.process.state()
            != QProcess.ProcessState.NotRunning
        )

    def start_worker(self, script, *arguments):
        self.reset_streams()

        process = QProcess(self)
        self.process = process
        process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )
        process.setWorkingDirectory(str(ROOT))

        # Each callback carries its originating process. Signals from
        # an old process cannot operate on a replacement worker.
        process.readyReadStandardOutput.connect(
            lambda p=process: self.read_stream("out", process=p)
        )
        process.readyReadStandardError.connect(
            lambda p=process: self.read_stream("err", process=p)
        )
        process.started.connect(
            lambda p=process: self.worker_started(p)
        )
        process.finished.connect(
            lambda code, status, p=process:
            self.worker_finished(p, code, status)
        )
        process.errorOccurred.connect(
            lambda error, p=process:
            self.process_error(p, error)
        )

        process.start(
            sys.executable,
            [
                "-X",
                "utf8",
                "-u",
                str(script),
                *arguments,
            ],
        )

    def worker_started(self, process):
        if process is not self.process:
            return

        if self.cancelled or self.close_when_idle or self.session_error:
            process.kill()
            return

        self.log.appendPlainText(
            f"[Worker] Started process {process.processId()}."
        )

        if self.shared_this_run:
            self.send_current_job()

    def send_current_job(self):
        if (
            self.current is None
            or self.job_sent
            or self.cancelled
            or self.close_when_idle
            or self.session_closing
            or self.session_error is not None
        ):
            return

        if (
            self.process is None
            or self.process.state() != QProcess.ProcessState.Running
        ):
            self.fail_worker(
                "Shared worker is not running."
            )
            return

        command = {
            "action": "run",
            "job": str(self.current["job_path"].resolve()),
        }
        payload = (
            json.dumps(command) + "\n"
        ).encode("utf-8")

        if self.process.write(payload) != len(payload):
            self.fail_worker(
                "Could not send the job to the shared worker."
            )
            return

        self.job_sent = True

    def begin_worker_shutdown(self):
        if self.session_closing:
            return

        self.session_closing = True
        self.status.setText(
            "Renders complete — releasing worker resources..."
        )
        self.log.appendPlainText(
            "[Session] All renders complete. "
            "Requesting cleanup and waiting for worker exit."
        )

        if (
            self.process is None
            or self.process.state() != QProcess.ProcessState.Running
        ):
            self.fail_worker(
                "Shared worker ended before shutdown."
            )
            return

        payload = (
            json.dumps({"action": "quit"}) + "\n"
        ).encode("utf-8")

        if self.process.write(payload) != len(payload):
            self.fail_worker(
                "Could not send the worker shutdown command."
            )
            return

        # Buffered writes are sent before QProcess closes the channel.
        self.process.closeWriteChannel()
        self.shutdown_process = self.process
        self.shutdown_timer.start()

    def worker_shutdown_timeout(self):
        if (
            not self.busy
            or not self.session_closing
            or self.shutdown_process is not self.process
            or not self.worker_alive()
        ):
            return

        seconds = SHUTDOWN_TIMEOUT_MS // 1000
        self.session_error = (
            f"Worker shutdown exceeded {seconds} seconds; "
            "forced termination was required."
        )
        self.log.appendPlainText(
            "[Session warning] " + self.session_error
        )
        self.status.setText(
            "Cleanup timed out — terminating worker..."
        )

        # Stay busy until the process exit signal arrives.
        self.process.kill()

    def fail_worker(self, message):
        if self.session_error is None:
            self.session_error = message
            self.log.appendPlainText(
                "[Worker error] " + message
            )

        self.shutdown_timer.stop()
        self.shutdown_process = None

        if self.finalizing_process:
            # The exit handler will inspect session_error after
            # it finishes draining the final output.
            return

        if self.worker_alive():
            self.status.setText(
                "Worker error — waiting for process exit..."
            )
            self.process.kill()

        elif self.process is not None:
            self.worker_finished(
                self.process,
                -1,
                QProcess.ExitStatus.CrashExit,
            )

        else:
            if self.current is not None:
                self.current["row"]["state"].setText("Failed")
            self.end_queue("Worker queue failed. See log.")
            self.tabs.setCurrentWidget(self.log)

    def process_error(self, process, error):
        if process is not self.process:
            return

        if not self.cancelled:
            self.log.appendPlainText(
                "[Worker error] " + process.errorString()
            )

        if error == QProcess.ProcessError.FailedToStart:
            self.session_error = (
                "Worker could not start: " + process.errorString()
            )
            # FailedToStart does not require a finished signal.
            self.worker_finished(
                process,
                -1,
                QProcess.ExitStatus.CrashExit,
            )

        elif error != QProcess.ProcessError.Crashed:
            # Crashed is followed by finished. Other I/O failures
            # require stopping the worker rather than continuing.
            if not self.cancelled:
                self.fail_worker(process.errorString())

    def worker_finished(self, process, exit_code, exit_status):
        if process is not self.process or self.finalizing_process:
            return

        self.shutdown_timer.stop()
        self.shutdown_process = None
        self.finalizing_process = True

        try:
            self.read_stream("out", final=True, process=process)
            self.read_stream("err", final=True, process=process)
        finally:
            self.finalizing_process = False

        normal_exit = (
            exit_code == 0
            and exit_status == QProcess.ExitStatus.NormalExit
        )
        record = self.current

        # Detach before completing the queue or scheduling another job.
        # Any late signal from this QProcess is now ignored.
        self.process = None
        process.deleteLater()

        if self.cancelled:
            self.log.appendPlainText(
                "[Worker] Process exited after cancellation."
            )
            if record is not None:
                record["row"]["state"].setText("Stopped")
            self.end_queue(
                "Queue stopped — worker exited; "
                "output may be incomplete"
            )
            return

        if self.shared_this_run:
            all_jobs_done = (
                self.current is None
                and not self.pending
            )
            successful = (
                normal_exit
                and self.session_closing
                and self.session_error is None
                and all_jobs_done
            )

            if successful:
                self.log.appendPlainText(
                    "[Session] Worker exited normally. "
                    "Queue cleanup complete."
                )
                self.overall.setValue(100)
                self.end_queue(
                    "Queue complete — worker exited"
                )

            elif all_jobs_done:
                self.log.appendPlainText(
                    "[Session warning] Renders completed, but worker "
                    "shutdown was abnormal or unexpected. "
                    "The worker has now exited."
                )
                self.overall.setValue(100)
                self.end_queue(
                    "Renders complete — worker shutdown warning. "
                    "See log."
                )
                self.tabs.setCurrentWidget(self.log)

            else:
                if record is not None:
                    record["row"]["state"].setText("Failed")
                self.end_queue(
                    "Shared worker failed or exited early. See log."
                )
                self.tabs.setCurrentWidget(self.log)

            return

        successful = (
            normal_exit
            and self.session_error is None
            and record is not None
            and (record["output"] / "COMPLETE.txt").is_file()
        )

        if not successful:
            if record is not None:
                record["row"]["state"].setText("Failed")
                message = (
                    f"Queue halted: keyframe "
                    f"{record['row']['key']} failed. See log."
                )
            else:
                message = "Worker exited unexpectedly. See log."

            self.end_queue(message)
            self.tabs.setCurrentWidget(self.log)
            return

        self.log.appendPlainText(
            "[Worker] Isolated worker exited normally."
        )
        self.complete_current_job()
        self.schedule_next()

    # ------------------------------------------------------------------
    # Output and progress
    # ------------------------------------------------------------------

    def reset_streams(self):
        self.decoders = {
            name: codecs.getincrementaldecoder("utf-8")(
                errors="replace"
            )
            for name in ("out", "err")
        }
        self.buffers = {"out": "", "err": ""}
        self.closed_streams = set()

    def read_stream(self, name, final=False, process=None):
        if process is None:
            process = self.process

        if (
            process is None
            or process is not self.process
            or name in self.closed_streams
        ):
            return

        if final:
            self.closed_streams.add(name)

        getter = (
            process.readAllStandardOutput
            if name == "out"
            else process.readAllStandardError
        )
        text = self.decoders[name].decode(
            bytes(getter()), final=final
        )
        self.buffers[name] += text.replace("\r", "\n")

        while "\n" in self.buffers[name]:
            line, self.buffers[name] = (
                self.buffers[name].split("\n", 1)
            )
            self.consume_line(name, line)

        if final and self.buffers[name]:
            line = self.buffers[name]
            self.buffers[name] = ""
            self.consume_line(name, line)

    def consume_line(self, name, line):
        if not line.strip():
            return

        if (
            self.shared_this_run
            and name == "out"
            and line.startswith(SESSION_PREFIX)
        ):
            if self.cancelled or self.session_error is not None:
                return

            try:
                message = json.loads(
                    line[len(SESSION_PREFIX):]
                )
                if not isinstance(message, dict):
                    raise ValueError(
                        "Invalid shared-worker event."
                    )
                if message.get("event") != "job_done":
                    raise ValueError(
                        "Unknown shared-worker event."
                    )
                if self.current is None or not self.job_sent:
                    raise ValueError(
                        "Received completion without an active job."
                    )

                reported = Path(message["job"]).resolve()
                expected = self.current["job_path"].resolve()
                if reported != expected:
                    raise ValueError(
                        "Worker completed an unexpected job."
                    )

                marker = (
                    self.current["output"] / "COMPLETE.txt"
                )
                if not marker.is_file():
                    raise ValueError(
                        "Worker did not write the completion marker."
                    )

            except (ValueError, TypeError, KeyError, OSError) as exc:
                self.fail_worker(str(exc))
                return

            self.complete_current_job()

            if not self.finalizing_process:
                self.schedule_next()
            return

        if name == "out" and line.startswith(PREFIX):
            try:
                message = json.loads(line[len(PREFIX):])
                percent = max(
                    0, min(99, int(message["percent"]))
                )
                stage = str(message["stage"])
            except (ValueError, KeyError, TypeError, OverflowError):
                self.log.appendPlainText(line)
                return

            if (
                self.current is not None
                and not self.cancelled
                and self.session_error is None
            ):
                row = self.current["row"]
                percent = max(row["bar"].value(), percent)
                row["bar"].setValue(percent)
                row["state"].setText(stage)
                self.status.setText(
                    f"Keyframe {row['key']}: {stage}"
                )
                self.update_overall(percent)
            return

        self.log.appendPlainText(line)

    def complete_current_job(self):
        record = self.current
        if record is None:
            return

        record["row"]["state"].setText("Complete")
        record["row"]["bar"].setValue(100)
        self.completed_work += record["weight"]
        self.current = None
        self.job_sent = False
        self.update_overall()

    def update_overall(self, percent=0):
        active = (
            self.current["weight"] * percent / 100
            if self.current is not None
            else 0
        )
        value = int(
            100
            * (self.completed_work + active)
            / max(1, self.total_work)
        )
        self.overall.setValue(min(99, value))

    # ------------------------------------------------------------------
    # Stop, completion, and window close
    # ------------------------------------------------------------------

    def end_queue(self, message):
        # Callers must wait for process finalization before unlocking.
        if self.process is not None:
            return

        self.shutdown_timer.stop()
        self.shutdown_process = None

        # Invalidate callbacks scheduled by this queue.
        self.queue_generation += 1

        for record in self.pending:
            record["row"]["state"].setText("Not run")
        self.pending.clear()
        self.current = None
        self.job_sent = False

        self.status.setText(message)
        self.set_busy(False)

        if self.close_when_idle:
            QTimer.singleShot(0, self.close)

    def stop_queue(self):
        if not self.busy and self.process is None:
            return

        self.cancelled = True
        self.queue_generation += 1
        self.shutdown_timer.stop()
        self.shutdown_process = None

        self.status.setText(
            "Stopping queue — waiting for worker exit..."
        )
        self.stop.setEnabled(False)

        self.log.appendPlainText(
            "[Session] Stop requested. Any active worker will be "
            "terminated; Python cleanup may be skipped."
        )

        if self.worker_alive():
            self.process.kill()

        elif self.process is not None:
            self.worker_finished(
                self.process,
                -1,
                QProcess.ExitStatus.CrashExit,
            )

        else:
            if self.current is not None:
                self.current["row"]["state"].setText("Stopped")
            self.end_queue("Queue stopped — no worker running")

    def set_busy(self, busy):
        was_busy = self.busy
        self.busy = busy

        if busy and not was_busy:
            self.queue_started_at = time.perf_counter()

        editable = not busy and not self.close_when_idle

        for widget in self.locked:
            widget.setEnabled(editable)

        for row in self.rows:
            for field in (
                "reverse", "forward", "folder", "remove", "synth"
            ):
                row[field].setEnabled(editable)

            row["start"].setEnabled(
                editable and row["reverse"].isChecked()
            )
            row["end"].setEnabled(
                editable and row["forward"].isChecked()
            )

        self.run_all.setEnabled(editable and bool(self.rows))
        self.stop.setEnabled(
            busy and not self.cancelled
        )

        if (
            not busy
            and was_busy
            and self.queue_started_at is not None
        ):
            elapsed = (
                time.perf_counter() - self.queue_started_at
            )
            mode = (
                "shared"
                if self.shared_this_run
                else "isolated"
            )
            self.log.appendPlainText(
                f"\n[Timing] Worker queue ({mode}): "
                f"{elapsed:.3f}s\n"
                f"[Timing] Result: {self.status.text()}"
            )
            self.queue_started_at = None

    def open_outputs(self):
        if self.batch is not None:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.batch))
            )

    def closeEvent(self, event):
        active = self.busy or self.process is not None

        if active:
            event.ignore()

            if self.close_when_idle:
                return

            answer = QMessageBox.question(
                self,
                "Queue running",
                "Stop the queue and close?\n\n"
                "Completed files will remain on disk. "
                "The active render may be incomplete. "
                "Unsaved project edits will not be saved.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if answer != QMessageBox.StandardButton.Yes:
                return

            # The confirmation dialog runs a nested event loop, so the
            # worker may have finished while the dialog was open.
            self.close_when_idle = True
            self.scan_timer.stop()
            self.set_busy(self.busy)

            if self.busy or self.process is not None:
                self.stop_queue()
            else:
                QTimer.singleShot(0, self.close)

            return

        self.scan_timer.stop()
        self.shutdown_timer.stop()
        self.preferences.sync()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(THEME)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
