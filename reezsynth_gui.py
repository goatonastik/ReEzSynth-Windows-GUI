import codecs
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QProcess,
    QSignalBlocker,
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
    QImage,
    QImageReader,
    QPainter,
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
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QStyledItemDelegate,
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
    validate_masks,
    validate_edge_guides,
    validate_video_dimensions,
    validate_row,
)
from reezsynth_config import (PROCESSING_PRESETS, validate_flow_model_available,
                              validate_processing_size, validate_processing_settings)
from reezsynth_preview import LivePreviewWindow

# ReEzSynth project controls integration v1
from reezsynth_project_controls import (
    FolderHistoryCombo,
    add_output_controls,
    create_batch_directory,
    default_job_definitions,
    project_naming,
    restore_ui_state,
    save_ui_state,
    set_project_naming,
    validate_output_folders,
    validate_project_naming,
    update_naming_preview,
)


from reezsynth_options import Options
from reezsynth_parallel import ParallelQueue
from reezsynth_config import validate_render, validate_weights, validate_application
from reezsynth_grouped_controls import GroupedVideoControls
from reezsynth_image_controls import ImageSynthesisControls
from reezsynth_image import validate_image_settings, image_job_settings
from reezsynth_serialization import read_document, write_document
from reezsynth_widget_style import COMBO_STYLE, QueueSpinBox, StepButton, QueueStyle, paint_check
from reezsynth_artifacts import validate_exports
from reezsynth_video_plan import (plan_grouped_video, check_blend_dependencies,
                                  validate_grouped_selection, validate_blend_options)


APP_NAME = "ReEzSynth-Windows-GUI"
SESSION_PREFIX = "@@REEZSYNTH_SESSION@@"
SHUTDOWN_TIMEOUT_MS = 30_000
ROW_HEIGHT = 36
STEP_COLUMN_WIDTH = 30
LOG_SEPARATOR = "=" * 96


def processing_size_parts(label):
    """Return the display's left resolution and right aspect-ratio fields."""
    if label.startswith(("512 ", "1024 ", "720p ", "1080p ")):
        return tuple(label.split(" ", 1))
    return label, ""


class ProcessingSizeItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        display = QStyleOptionViewItem(option)
        self.initStyleOption(display, index)
        label = display.text
        display.text = ""
        style = display.widget.style() if display.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, display, painter, display.widget)
        left, right = processing_size_parts(label)
        rectangle = display.rect.adjusted(8, 0, -8, 0)
        painter.save()
        painter.setPen(display.palette.text().color())
        painter.drawText(rectangle, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, left)
        if right:
            painter.drawText(rectangle, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right)
        painter.restore()


class ProcessingSizeCombo(QComboBox):
    """Show resolution left-aligned and its aspect ratio right-aligned."""
    def __init__(self):
        super().__init__()
        self.setItemDelegate(ProcessingSizeItemDelegate(self))
        self.setMinimumContentsLength(20)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

    def paintEvent(self, event):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        painter = QPainter(self)
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option, painter, self)
        rectangle = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, option,
            QStyle.SubControl.SC_ComboBoxEditField, self).adjusted(4, 0, -4, 0)
        left, right = processing_size_parts(self.currentText())
        painter.setPen(option.palette.buttonText().color())
        painter.drawText(rectangle, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, left)
        if right:
            painter.drawText(rectangle, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right)


THEME = """
QWidget {
    background: #252525;
    color: #b8b8b8;
    font-size: 12px;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTableWidget {
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
""" + COMBO_STYLE


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

        paint_check(painter, QRectF(x, y, size, size), self.isChecked(), self.isEnabled(), self.hasFocus())


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
        self.parallel_queue = None
        self.finalizing_process = False
        self.shutdown_process = None
        self.queue_generation = 0
        self.queue_count = 0
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
        restore_ui_state(self)
        self.options.restore()

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def build_interface(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)

        self.logo = QLabel("ReEzSynth")
        self.logo.setContentsMargins(0, 0, 20, 0)
        self.logo.setStyleSheet(
            "color: #009f87; font-size: 25px; font-style: italic;"
        )

        self.tabs = QTabWidget()
        self.tabs.setCornerWidget(self.logo, Qt.Corner.TopLeftCorner)
        self.save_log_button = self.button("Save Log...", self.save_log)
        self.tabs.setCornerWidget(self.save_log_button, Qt.Corner.TopRightCorner)
        layout.addWidget(self.tabs)

        video_page = QWidget()
        page = QVBoxLayout(video_page)
        self.tabs.addTab(video_page, "Video / Keyframes")

        for name in ("Image Synthesis (planned)", "Blend / Flow (planned)"):
            index = self.tabs.addTab(QWidget(), name)
            self.tabs.setTabEnabled(index, False)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
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
        directory_and_output = QHBoxLayout()
        page.addLayout(directory_and_output)
        self.directory_layout = QVBoxLayout()
        directory_and_output.addLayout(self.directory_layout, 1)
        self.directory_layout.addLayout(form)
        output_layout = QVBoxLayout()
        directory_and_output.addLayout(output_layout, 1)

        self.project_dir = self.path_row(form, "Project directory")
        self.keyframe_dir = self.path_row(form, "Keyframes")
        self.video_dir = self.path_row(form, "Video frames")
        self.project_dir.setText(str(ROOT / "reezsynth_projects"))

        self.keyframe_dir.textChanged.connect(self.schedule_scan)
        self.video_dir.textChanged.connect(self.schedule_scan)

        options = QHBoxLayout()
        self.quality = QComboBox()
        self.quality.addItems(["Preview", "Standard", "Highest"])
        self.quality.setCurrentText('Standard')
        options.addWidget(QLabel("Processing size:"))
        self.resolution = ProcessingSizeCombo()
        for identifier, label, _ in PROCESSING_PRESETS:
            self.resolution.addItem(label, identifier)
        self.resolution.setCurrentIndex(self.resolution.findData('original'))
        options.addWidget(self.resolution)
        self.processing_width = QueueSpinBox(); self.processing_width.setRange(0, 16384)
        self.processing_height = QueueSpinBox(); self.processing_height.setRange(0, 16384)
        for editor, name in ((self.processing_width, 'Width'), (self.processing_height, 'Height')):
            editor.setSpecialValueText('—')
            editor.setAccessibleName('Processing ' + name.lower())
        options.addWidget(QLabel('W:')); options.addWidget(self.processing_width)
        options.addWidget(QLabel('H:')); options.addWidget(self.processing_height)
        self.resolution.currentIndexChanged.connect(self.processing_preset_changed)
        self.processing_preset_changed()
        options.addStretch()
        page.addLayout(options)

        self.locked.extend([self.quality, self.resolution, self.processing_width, self.processing_height])
        add_output_controls(self, output_layout)

        self.summary = QLabel(
            "Select the source-frame and keyframe directories "
            "to build the queue."
        )
        self.summary.setWordWrap(True)
        page.addWidget(self.summary)

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

        status_row = QHBoxLayout()
        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        status_row.addWidget(self.status, 1)
        self.queue_summary = QLabel()
        self.queue_summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.queue_summary)
        layout.addLayout(status_row)

        self.overall = QProgressBar()
        self.overall.setRange(0, 100)
        self.overall.setValue(0)
        self.overall.setFormat("Queue: %p%")
        self.overall.setToolTip(
            "Work-weighted queue progress, not an estimated remaining time."
        )
        layout.addWidget(self.overall)

        self.grouped = GroupedVideoControls(self)
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == "Blend / Flow (planned)":
                placeholder = self.tabs.widget(index)
                self.tabs.removeTab(index)
                self.tabs.insertTab(index, self.grouped, "Blend / Flow")
                placeholder.deleteLater()
                break
        self.image_synthesis = ImageSynthesisControls(self)
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == 'Image Synthesis (planned)':
                placeholder = self.tabs.widget(index)
                self.tabs.removeTab(index)
                self.tabs.insertTab(index, self.image_synthesis, 'Image Synthesis')
                placeholder.deleteLater()
                break
        self.options = Options(self, page, form, settings_page, settings_layout)
        self.tabs.currentChanged.connect(self.refresh_processing_display)
        self.image_synthesis.target.textChanged.connect(self.refresh_processing_display)

    def button(self, text, callback, accent=False):
        button = QPushButton(text)
        button.clicked.connect(callback)
        if accent:
            button.setProperty("accent", True)
        return button

    def path_row(self, form, label):
        field = FolderHistoryCombo(
            label, FolderEdit(), self.preferences
        )
        select = self.button(
            "Select", lambda: self.choose_folder(field, label)
        )

        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(field, 1)
        select.setMaximumWidth(120)
        box.addWidget(select)

        form.addRow(label, row)
        self.locked.extend([field, select])
        return field

    def choose_folder(self, field, label):
        selected = QFileDialog.getExistingDirectory(
            self, label, field.text()
        )
        if selected:
            field.setText(selected)
            field.remember()

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

        self.grouped.sync_inputs()

        try:
            self.video, self.keys, self.padding, definitions = build_plan(
                self.path_value(self.video_dir),
                self.path_value(self.keyframe_dir),
            )

            definitions = default_job_definitions(self, definitions)

            for definition in definitions:
                self.add_row(definition)

            self.grouped.sync_inputs()
            self.summary.setText(
                f"{len(self.video)} source frames: "
                f"{min(self.video)}–{max(self.video)} | "
                f"{len(self.rows)} keyframe jobs"
            )
            self.summary.setText("Queue rebuilt. Choose rows to adjust their propagation ranges.")
            self.queue_summary.setText(
                f"{len(self.video)} source frames | {len(self.rows)} keyframe jobs"
            )
            self.set_busy(False)
            save_ui_state(self)
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

    def processing_size(self):
        identifier = self.resolution.currentData()
        if identifier == 'original' or self.processing_max_width():
            return None
        if identifier == 'custom':
            return validate_processing_size([self.processing_width.value(), self.processing_height.value()])
        presets = {key: size for key, _, size in PROCESSING_PRESETS}
        if identifier not in presets:
            raise ValueError('Select a processing size.')
        return presets[identifier]

    def processing_max_width(self):
        return {'legacy_512': 512, 'legacy_960': 960}.get(self.resolution.currentData(), 0)

    def set_processing_size(self, size, max_width=0):
        settings = validate_processing_settings(dict(processing_size=size, max_width=max_width))
        size = settings['processing_size']
        identifier = 'original' if size is None else next(
            (key for key, _, preset in PROCESSING_PRESETS if preset == tuple(size)), 'custom')
        if max_width:
            identifier = f'legacy_{max_width}'
        with QSignalBlocker(self.resolution), QSignalBlocker(self.processing_width), QSignalBlocker(self.processing_height):
            # Compatibility entries only appear when restoring a width-limited file.
            for index in reversed(range(self.resolution.count())):
                if str(self.resolution.itemData(index)).startswith('legacy_'):
                    self.resolution.removeItem(index)
            if max_width:
                self.resolution.addItem(f'Legacy max width {max_width}', identifier)
            self.resolution.setCurrentIndex(self.resolution.findData(identifier))
            if size:
                self.processing_width.setValue(size[0])
                self.processing_height.setValue(size[1])
        self.processing_preset_changed()

    def processing_preset_changed(self):
        identifier = self.resolution.currentData()
        if identifier == 'custom':
            with QSignalBlocker(self.processing_width), QSignalBlocker(self.processing_height):
                if min(self.processing_width.value(), self.processing_height.value()) < 128:
                    self.processing_width.setValue(1920)
                    self.processing_height.setValue(1080)
        self.refresh_processing_display()

    def refresh_processing_display(self, *_):
        identifier = self.resolution.currentData()
        editable = identifier == 'custom' and not self.busy and not self.close_when_idle
        for editor in (self.processing_width, self.processing_height):
            editor.setEnabled(editable)
        if identifier == 'custom':
            return
        size = next((size for key, _, size in PROCESSING_PRESETS if key == identifier), None)
        if size is None:
            image_tab = getattr(self, 'image_synthesis', None)
            if image_tab is not None and self.tabs.currentWidget() is image_tab:
                path = image_tab.target.text().strip().strip('"')
            else:
                path = next(iter(self.video.values()), '')
            dimensions = QImageReader(str(path)).size() if path else QSize()
            size = [0, 0]
            if dimensions.isValid():
                limit = self.processing_max_width()
                scale = min(1.0, limit / dimensions.width()) if limit else 1.0
                size = [max(1, round(dimensions.width() * scale)), max(1, round(dimensions.height() * scale))]
        with QSignalBlocker(self.processing_width), QSignalBlocker(self.processing_height):
            self.processing_width.setValue(size[0])
            self.processing_height.setValue(size[1])

    def save_project(self, save_as=False):
        if self.busy:
            return

        try:
            image_only = not self.rows and any(self.image_synthesis.settings()[name] for name in ('style', 'source', 'target'))
            if not self.rows and not image_only:
                raise ValueError(
                    "Build a queue before saving the project."
                )

            data = {
                "format": APP_NAME,
                "version": 1,
                "project_mode": 'image' if image_only else 'video',
                "project_dir": self.path_value(self.project_dir),
                "video_dir": self.video_dir.text() if image_only else self.path_value(self.video_dir),
                "keyframe_dir": self.keyframe_dir.text() if image_only else self.path_value(self.keyframe_dir),
                "quality": self.quality.currentText(),
                "max_width": self.processing_max_width(),
                "processing_size": self.processing_size(),
                "output_naming": project_naming(self),
                **self.options.project_data(),
                "rows": [
                    validate_row(
                        self.definition(row), self.video, self.keys
                    )
                    for row in self.rows
                ],
            }

            if image_only:
                data['grouped_video'] = None

            path = self.project_file
            if save_as or path is None:
                selected, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save project",
                    str(ROOT / "project.reezsynth.json"),
                    "ReEzSynth project (*.reezsynth.json *.reezsynth.yaml *.reezsynth.yml)",
                )
                if not selected:
                    return
                path = Path(selected)

            write_document(path, data)
            self.project_file = path
            self.status.setText(f"Project saved: {path}")
            save_ui_state(self)

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
            "ReEzSynth project (*.reezsynth.json *.reezsynth.yaml *.reezsynth.yml)",
        )
        if not selected:
            return

        try:
            data = read_document(selected)
            if (
                data.get("format") != APP_NAME
                or data.get("version") != 1
            ):
                raise ValueError("Unsupported project format.")

            if data["quality"] not in {"Preview", "Standard", "Highest"}:
                raise ValueError("Unknown quality preset.")
            processing = validate_processing_settings(data)
            if data.get('project_mode', 'video') not in ('image', 'video'):
                raise ValueError('Unknown project mode.')
            validate_image_settings(data.get('image_synthesis'))
            if data.get('project_mode') == 'image':
                if data['rows']:
                    raise ValueError('Image-only projects cannot contain video rows.')
                video, keys, padding = {}, {}, 3
            else:
                video, keys, padding, _ = build_plan(data['video_dir'], data['keyframe_dir'])
            definitions = [
                validate_row(row, video, keys)
                for row in data["rows"]
            ]

            if len({row["key"] for row in definitions}) != len(definitions):
                raise ValueError(
                    "Project contains duplicate keyframe rows."
                )

            naming = validate_project_naming(
                data.get("output_naming")
            )

            validate_render(data.get("render_options"))
            from reezsynth_engines import LEGACY, validate_revision
            validate_revision(data.get('render_options', {}).get('engine', LEGACY), data.get('engine_revision'))
            validate_weights(data.get("guide_weights"))
            validate_blend_options(data.get("blend_options"))
            validate_exports(data.get("exports"))
            from reezsynth_video_export import validate_video_export
            validate_video_export(data.get('video_export'))
            grouped_selection = validate_grouped_selection(data.get("grouped_video"))
            if grouped_selection["keyframes"] is not None and set(grouped_selection["keyframes"]) - set(keys):
                raise ValueError("Saved grouped keyframes are missing from the input folders.")
            if not all(isinstance(data.get(name, ""), str) for name in ('mask_dir', 'edge_dir')):
                raise ValueError("Mask and custom edge-guide directories must be text.")

            self.loading_project = True
            self.scan_timer.stop()

            self.project_dir.setText(data["project_dir"])
            self.video_dir.setText(data["video_dir"])
            self.keyframe_dir.setText(data["keyframe_dir"])
            self.quality.setCurrentText(data["quality"])
            self.set_processing_size(processing['processing_size'], processing['max_width'])
            set_project_naming(self, naming)
            self.options.load_project(data)

            self.video = video
            self.keys = keys
            self.padding = padding
            self.rows.clear()
            self.table.setRowCount(0)

            for definition in definitions:
                self.add_row(definition)

            self.project_file = Path(selected)
            if data.get('project_mode') == 'image':
                self.tabs.setCurrentWidget(self.image_synthesis)
            self.grouped.set_selection(grouped_selection)
            self.summary.setText(
                f"{len(video)} source frames | "
                f"{len(self.rows)} saved jobs"
            )
            self.status.setText(f"Project loaded: {selected}")
            self.summary.setText("Saved queue loaded.")
            self.queue_summary.setText(
                f"{len(video)} source frames | {len(self.rows)} keyframe jobs"
            )
            self.set_busy(False)
            save_ui_state(self)

        except Exception as exc:
            QMessageBox.warning(
                self, "Cannot open project", str(exc)
            )
        finally:
            self.loading_project = False

    # ------------------------------------------------------------------
    # Queue preparation
    # ------------------------------------------------------------------

    def run_rows(self, rows, grouped=False):
        if self.busy or self.process is not None or self.close_when_idle:
            return

        self.options.auto_timer.stop()
        self.options.auto_armed = False
        parallel = self.options.application()["parallel"]
        shared = self.reuse_worker.isChecked() and not parallel
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

            if not rows and not grouped:
                raise ValueError("There are no jobs to render.")

            video, keys, padding, _ = build_plan(
                self.path_value(self.video_dir),
                self.path_value(self.keyframe_dir),
            )

            render_options = self.options.render(effective=True)
            guide_weights = self.options.weights()
            from reezsynth_video_export import validate_video_export
            video_export = validate_video_export(
                self.options.snapshot('render')['video_export'], check_audio=True)
            application = validate_application(self.options.application())
            from reezsynth_engines import prepare_runtime, validate_capabilities, preflight_flow
            engine_runtime = prepare_runtime(render_options, application)
            validate_capabilities(render_options, blend=self.grouped.blend_options(effective=True) if grouped else None,
                                  exports=self.options.snapshot('render')['exports'])
            masks = validate_masks(self.mask_dir.text(), video) if render_options["do_mask"] else {}
            edge_guides = validate_edge_guides(self.edge_dir.text(), video) if render_options['custom_edge_guides'] else {}
            planned = []
            folders = set()
            group_plan = None
            if grouped:
                selection = self.grouped.selection()
                group_plan = plan_grouped_video(video, keys, selection, self.grouped.blend_options(effective=True))
                if engine_runtime['engine'] == 'FuouM/ReEzSynth':
                    from reezsynth_fuoum_pipeline import work_count
                    numbers = [n for n, _ in group_plan['frames']]
                    group_plan['synthesis_work'] = work_count(len(numbers),
                        [numbers.index(n) for n, _ in group_plan['styles']], group_plan['blend_options']['only_mode'])
                check_blend_dependencies(group_plan["blend_options"])
                planned.append((self.grouped.row, dict(key=group_plan["key"], folder=selection["folder"]),
                                group_plan["frames"], group_plan["style"]))

            for row in ([] if grouped else rows):
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

            validate_output_folders([
                definition["folder"]
                for _, definition, _, _ in planned
            ])

            if any(len(frames) > 1 for _, _, frames, _ in planned):
                if engine_runtime['engine'] == 'Trentonom0r3/Ezsynth':
                    validate_flow_model_available(render_options['flow_model'], render_options['flow_arch'])
                else:
                    preflight_flow(render_options, engine_runtime)

            if self.processing_size() is None and not self.processing_max_width():
                selected_video = {number: path for _, _, frames, _ in planned for number, path in frames}
                selected_keys = (dict(group_plan['styles']) if group_plan else
                                 {definition['key']: style for _, definition, _, style in planned})
                validate_video_dimensions(selected_video, selected_keys)

            project_root = Path(
                self.path_value(self.project_dir)
            )
            batch = create_batch_directory(self, project_root)

            records = []

            for row, definition, frames, style in planned:
                destination = (
                    batch / definition["folder"]
                ).resolve()

                if not destination.is_relative_to(batch.resolve()):
                    raise ValueError(
                        "Output directory escapes the batch directory."
                    )

                from reezsynth_output_location import create_unique_directory
                destination = create_unique_directory(batch, definition['folder'])

                job = {
                    "key": definition["key"],
                    "style": style,
                    "frames": frames,
                    "padding": padding,
                    "quality": self.quality.currentText(),
                    "max_width": self.processing_max_width(),
                    "processing_size": self.processing_size(),
                    "output": str(destination),
                    **(group_plan or {}),
                    "render_options": render_options,
                    "engine_runtime": engine_runtime,
                    "exports": validate_exports(self.options.snapshot("render")["exports"]),
                    "video_export": video_export,
                    "guide_weights": guide_weights,
                    "masks": [[number, str(masks[number])] for number, _ in frames] if masks else [],
                    "edge_guides": [[number, str(edge_guides[number])] for number, _ in frames] if edge_guides else [],
                }

                job_path = destination / "job.json"
                job_path.write_text(
                    json.dumps(job, indent=2),
                    encoding="utf-8",
                )

                records.append({
                    "row": row,
                    "key": definition["key"],
                    "job_path": job_path,
                    "output": destination,
                    "weight": max(1, group_plan["synthesis_work"] if group_plan else len(frames) - 1),
                    "python": engine_runtime['python'],
                })

        except Exception as exc:
            QMessageBox.warning(
                self, "Cannot start queue", str(exc)
            )
            return

        self.start_records(records, batch, shared, parallel, worker_script, application)

    def run_image(self):
        if self.busy or self.process is not None or self.close_when_idle:
            return
        self.options.auto_timer.stop()
        self.options.auto_armed = False
        try:
            from reezsynth_output_location import output_root, create_unique_directory
            from reezsynth_project_controls import _values, _format_name, BATCH_FIELDS
            settings = image_job_settings(self.image_synthesis.settings())
            validate_output_folders([settings['folder']])
            naming = project_naming(self)
            root = output_root(naming, self.path_value(self.project_dir),
                               str(Path(settings['style']).parent), str(Path(settings['target']).parent))
            options = self.options.render(effective=True)
            application = validate_application(self.options.application())
            from reezsynth_engines import prepare_runtime, validate_capabilities
            engine_runtime = prepare_runtime(options, application)
            validate_capabilities(options, image=True)
            parallel = application['parallel']
            shared = self.reuse_worker.isChecked() and not parallel
            worker_script = ROOT / ('reezsynth_shared_worker.py' if shared else 'reezsynth_jobs.py')
            if not worker_script.is_file():
                raise ValueError(f'Worker script not found: {worker_script}')
            values = _values(self)
            values.update(keyframe_dir_name=Path(settings['style']).parent.name,
                          video_dir_name=Path(settings['target']).parent.name)
            batch = create_unique_directory(root, _format_name(naming['batch_pattern'], values,
                    BATCH_FIELDS, allow_nested=False)) if naming['batch_enabled'] else root
            destination = create_unique_directory(batch, settings['folder'])
            job = dict(type='image_synthesis', image_synthesis=settings, output=str(destination),
                       quality=self.quality.currentText(), max_width=self.processing_max_width(), processing_size=self.processing_size(),
                       render_options=options, engine_runtime=engine_runtime)
            job_path = destination / 'job.json'
            job_path.write_text(json.dumps(job, indent=2), encoding='utf-8')
            records = [dict(row=self.image_synthesis.row, key='Image', job_path=job_path,
                            output=destination, weight=1, python=engine_runtime['python'])]
        except Exception as exc:
            QMessageBox.warning(self, 'Cannot synthesize image', str(exc))
            return
        self.start_records(records, batch, shared, parallel, worker_script, application)

    def start_records(self, records, batch, shared, parallel, worker_script, application):
        self.gpu_memory_error_reported = False
        self.scan_timer.stop()
        self.shutdown_timer.stop()
        self.shutdown_process = None

        self.queue_generation += 1
        self.queue_count += 1
        self.active_queue_generation = self.queue_count
        self.queue_mode = 'parallel' if parallel else ('shared' if shared else 'isolated')
        self.batch = batch
        save_ui_state(self)
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
        self.preview_window.begin(records, application.get("preview_limit", 8))

        self.overall.setValue(0)
        self.log.appendPlainText(
            f"\n{LOG_SEPARATOR}\n"
            f"QUEUE RUN {self.active_queue_generation} STARTED {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Mode: {'parallel' if parallel else ('shared worker' if shared else 'isolated workers')}\n"
            f"Jobs: {len(records)} | Output root: {batch}\n"
            + (f"Maximum simultaneous renders: {application.get('parallel_limit', 2) or 'unlimited'}\n" if parallel else '') +
            f"{LOG_SEPARATOR}"
        )
        self.open_output.setEnabled(True)

        for record in records:
            record["row"]["state"].setText("Queued")
            record["row"]["bar"].setValue(0)

        self.set_busy(True)
        if parallel:
            self.pending = []
            self.parallel_queue = ParallelQueue(self, records, worker_script, application["parallel_limit"])
            self.parallel_queue.start()
        else:
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
        self.preview_window.activate(self.current)

        row = self.current["row"]
        row["state"].setText("Starting")
        label = row.get('label', f"Keyframe {row['key']}")
        self.status.setText(f"Starting {label}")

        mode = (
            "shared worker"
            if self.shared_this_run
            else "isolated worker"
        )
        self.log.appendPlainText(
            f"\n=== {label} - {mode} ===\n"
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
            (self.current or {}).get('python', sys.executable),
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

    def check_gpu_memory_error(self, line):
        from reezsynth_errors import is_cuda_out_of_memory
        if getattr(self, 'gpu_memory_error_reported', False) or not is_cuda_out_of_memory(line):
            return
        self.gpu_memory_error_reported = True
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle('GPU out of memory')
        dialog.setText('The render failed because CUDA reported insufficient GPU memory.')
        dialog.setInformativeText(
            'For video, try enabling Memory-efficient RAFT correlation in Rendering. '
            'If it is already enabled, another allocation may still exceed available memory. '
            'Disable parallel rendering and close other GPU workloads before retrying. '
            'Reducing Processing size is another option, but also reduces output resolution. '
            'See Diagnostics for the full error. No automatic retry or resizing was performed.')
        dialog.setDetailedText(line)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # Asynchronous: worker output, shutdown timers and cancellation keep running.
        dialog.show()

    def consume_line(self, name, line):
        if not line.strip():
            return

        self.check_gpu_memory_error(line)

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
                preview = message.get("preview")
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
                    f"{row.get('label', 'Keyframe ' + str(row['key']))}: {stage}"
                )
                self.update_overall(percent)
                self.preview_window.receive(preview, self.current)
            return

        self.log.appendPlainText(line)

    def complete_current_job(self):
        record = self.current
        if record is None:
            return

        record["row"]["state"].setText("Complete")
        record["row"]["bar"].setValue(100)
        self.completed_work += record["weight"]
        self.options.notify(each=True)
        self.preview_window.finish(record)
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
        if self.process is not None or self.parallel_queue is not None:
            return

        if self.overall.value() == 100 and not self.cancelled:
            self.options.notify()
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
        self.preview_window.end()
        self.set_busy(False)
        self.log.appendPlainText(
            f"\n{LOG_SEPARATOR}\n"
            f"QUEUE RUN {getattr(self, 'active_queue_generation', self.queue_generation)} ENDED "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Result: {message}\n"
            f"{LOG_SEPARATOR}"
        )

        if self.close_when_idle:
            QTimer.singleShot(0, self.close)

    def stop_queue(self):
        if self.parallel_queue is not None:
            self.parallel_queue.stop()
            return
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
        self.refresh_processing_display()

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
        self.grouped.update_enabled()
        self.image_synthesis.set_busy(busy)
        if hasattr(self, 'options'):
            self.options.refresh_engine_controls()
            self.options.refresh_video_export_controls()
        update_naming_preview(self)
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
            mode = getattr(self, 'queue_mode', 'shared' if self.shared_this_run else 'isolated')
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

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save diagnostics log", "reezsynth-session.log", "Log files (*.log);;Text files (*.txt)"
        )
        if not path:
            return
        try:
            Path(path).write_text(self.log.toPlainText(), encoding="utf-8")
            self.statusBar().showMessage(f"Diagnostics log saved: {path}", 5000)
        except OSError as exc:
            QMessageBox.warning(self, "Cannot save diagnostics log", str(exc))

    def closeEvent(self, event):
        if self.options.installation_active():
            event.ignore()
            QMessageBox.information(
                self,
                "Optional dependency installation",
                "An optional dependency installation is still running. Wait for it to finish before closing ReEzSynth.",
            )
            return

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
        self.options.close()
        save_ui_state(self)
        self.preferences.sync()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle(QueueStyle('Fusion'))
    app.setStyleSheet(THEME)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
