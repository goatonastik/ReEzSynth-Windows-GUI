"""External EbSynth Beta project editor. Beta itself is never bundled or modified."""

from __future__ import annotations

import ntpath
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from reezsynth_beta_project import Interval, Project, read, to_bytes


def rebase_paths(project: Project, old_directory: Path, new_directory: Path) -> Project:
    """Keep relative Beta paths pointed at the same files after Save As."""
    old_base = ntpath.normpath(str(old_directory.resolve()))
    new_base = ntpath.normpath(str(new_directory.resolve()))

    def relocate(value: str) -> str:
        if ntpath.isabs(value):
            return value
        absolute = ntpath.normpath(ntpath.join(old_base, value))
        try:
            return ntpath.relpath(absolute, new_base)
        except ValueError:  # Different Windows drives.
            return absolute

    return replace(
        project,
        video=relocate(project.video),
        mask=relocate(project.mask),
        keys=relocate(project.keys),
        intervals=tuple(replace(row, output=relocate(row.output))
                        for row in project.intervals),
    )


class BetaProjectTab(QWidget):
    """Edit an EBS05 project, then open it in a user-selected Beta executable."""

    COLUMNS = ("Keyframe", "Back on", "First", "Forward on", "Last", "Output pattern")
    WEIGHTS = (
        ("Keyframe weight", "key_weight"),
        ("Video weight", "video_weight"),
        ("Mask weight", "mask_weight"),
        ("Mapping", "mapping"),
        ("Deflicker", "deflicker"),
        ("Diversity", "diversity"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_path: Path | None = None
        self.project: Project | None = None
        self.preferences = QSettings("ReEzSynth", "ReEzSynth-Windows-GUI")

        layout = QVBoxLayout(self)
        note = QLabel(
            "Uses your own EbSynth Beta installation. ReEzSynth creates a Beta project "
            "and opens it in Beta; start and monitor synthesis in Beta for now."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        exe_row = QHBoxLayout()
        self.exe = QLineEdit(str(self.preferences.value("beta/executable", "")))
        self.exe.setPlaceholderText("Select EbSynth.exe")
        self.exe.editingFinished.connect(
            lambda: self.preferences.setValue("beta/executable", self.exe.text().strip()))
        exe_row.addWidget(QLabel("Beta executable"))
        exe_row.addWidget(self.exe, 1)
        browse_exe = QPushButton("Browse...")
        browse_exe.clicked.connect(self.browse_exe)
        exe_row.addWidget(browse_exe)
        layout.addLayout(exe_row)

        actions = QHBoxLayout()
        for title, handler in (
            ("Open .ebs...", self.open_dialog),
            ("Save copy as...", self.save_as),
            ("Open in Beta", self.launch_beta),
        ):
            button = QPushButton(title)
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.project_label = QLabel("No Beta project loaded")
        self.project_label.setWordWrap(True)
        layout.addWidget(self.project_label)

        form = QFormLayout()
        self.video = QLineEdit()
        self.keys = QLineEdit()
        self.mask = QLineEdit()
        self.mask_enabled = QCheckBox("Use mask")
        self.fields = {}
        form.addRow("Video pattern", self.video)
        form.addRow("Keyframe pattern", self.keys)
        form.addRow("Mask pattern", self.mask)
        form.addRow("Mask", self.mask_enabled)
        for title, name in self.WEIGHTS:
            field = QLineEdit()
            self.fields[name] = field
            form.addRow(title, field)
        self.detail = QSpinBox()
        self.detail.setRange(1, 4)
        self.gpu = QCheckBox("Use GPU")
        self.fps = QLineEdit()
        form.addRow("Detail", self.detail)
        form.addRow("GPU", self.gpu)
        form.addRow("Frame rate", self.fps)
        layout.addLayout(form)

        self.rows = QTableWidget(0, len(self.COLUMNS))
        self.rows.setHorizontalHeaderLabels(self.COLUMNS)
        self.rows.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.rows, 1)
        row_actions = QHBoxLayout()
        for title, handler in (("Add keyframe", self.add_row),
                               ("Remove selected keyframe", self.remove_row)):
            button = QPushButton(title)
            button.clicked.connect(handler)
            row_actions.addWidget(button)
        row_actions.addStretch()
        layout.addLayout(row_actions)

    def browse_exe(self):
        selected, _ = QFileDialog.getOpenFileName(
            self, "Select your EbSynth Beta executable", self.exe.text(),
            "Windows executable (*.exe)")
        if selected:
            self.exe.setText(selected)
            self.preferences.setValue("beta/executable", selected)

    def open_dialog(self):
        selected, _ = QFileDialog.getOpenFileName(
            self, "Open EbSynth Beta project", "", "EbSynth project (*.ebs)")
        if selected:
            try:
                self.load_project(Path(selected))
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Cannot open Beta project", str(exc))

    def load_project(self, path: Path):
        project = read(path)
        self.project = project
        self.project_path = path.resolve()
        self.project_label.setText(str(self.project_path))
        self.video.setText(project.video)
        self.keys.setText(project.keys)
        self.mask.setText(project.mask)
        self.mask_enabled.setChecked(project.mask_enabled)
        for _, name in self.WEIGHTS:
            self.fields[name].setText(str(getattr(project, name)))
        self.detail.setValue(project.detail)
        self.gpu.setChecked(project.gpu)
        self.fps.setText(str(project.fps))
        self.rows.setRowCount(0)
        for interval in project.intervals:
            self.append_interval(interval)

    def append_interval(self, interval: Interval):
        index = self.rows.rowCount()
        self.rows.insertRow(index)
        for column, value in ((0, interval.key), (2, interval.backward_stop),
                              (4, interval.forward_stop), (5, interval.output)):
            self.rows.setItem(index, column, QTableWidgetItem(str(value)))
        for column, enabled in ((1, interval.backward_enabled),
                                (3, interval.forward_enabled)):
            item = QTableWidgetItem()
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            self.rows.setItem(index, column, item)

    def add_row(self):
        if self.project is None:
            QMessageBox.information(self, "Open a project", "Open a Beta project first.")
            return
        self.append_interval(Interval(0, True, True, 0, 0,
                                      r"beta_outputs\key0\[##].png"))

    def remove_row(self):
        if self.rows.currentRow() >= 0:
            self.rows.removeRow(self.rows.currentRow())

    def current_project(self) -> Project:
        if self.project is None:
            raise ValueError("Open a Beta project first.")

        def value(row, column):
            item = self.rows.item(row, column)
            if item is None:
                raise ValueError(f"Missing value in row {row + 1}.")
            return item.text().strip()

        intervals = []
        for row in range(self.rows.rowCount()):
            intervals.append(Interval(
                int(value(row, 0)),
                self.rows.item(row, 1).checkState() == Qt.CheckState.Checked,
                self.rows.item(row, 3).checkState() == Qt.CheckState.Checked,
                int(value(row, 2)), int(value(row, 4)), value(row, 5),
            ))
        project = replace(
            self.project,
            video=self.video.text().strip(), keys=self.keys.text().strip(),
            mask=self.mask.text().strip(), mask_enabled=self.mask_enabled.isChecked(),
            intervals=tuple(intervals), detail=self.detail.value(),
            gpu=self.gpu.isChecked(), fps=float(self.fps.text().strip()),
            **{name: float(self.fields[name].text().strip())
               for _, name in self.WEIGHTS},
        )
        project.validate()
        return project

    def save_project_copy(self, destination: Path) -> Path:
        if self.project_path is None:
            raise ValueError("Open a Beta project first.")
        destination = destination.resolve()
        if destination.exists():
            raise FileExistsError(f"Project already exists: {destination}")
        project = rebase_paths(self.current_project(), self.project_path.parent,
                               destination.parent)
        encoded = to_bytes(project)
        with destination.open("xb") as stream:
            stream.write(encoded)
        self.load_project(destination)
        return destination

    def save_as(self):
        if self.project_path is None:
            QMessageBox.information(self, "Open a project", "Open a Beta project first.")
            return
        selected, _ = QFileDialog.getSaveFileName(
            self, "Save a copy of the Beta project",
            str(self.project_path.with_name(self.project_path.stem + "-copy.ebs")),
            "EbSynth project (*.ebs)")
        if not selected:
            return
        try:
            self.save_project_copy(Path(selected))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot save Beta project", str(exc))

    def launch_beta(self):
        if self.project_path is None:
            QMessageBox.information(self, "Open a project", "Open a Beta project first.")
            return
        try:
            if to_bytes(self.current_project()) != self.project_path.read_bytes():
                raise ValueError("Save a project copy before opening edited settings in Beta.")
            executable = Path(self.exe.text().strip().strip('"')).resolve()
            if not executable.is_file() or executable.suffix.lower() != ".exe":
                raise ValueError("Select an existing EbSynth Beta .exe first.")
            self.preferences.setValue("beta/executable", str(executable))
            result = QProcess.startDetached(str(executable), [str(self.project_path)],
                                            str(self.project_path.parent))
            started = result[0] if isinstance(result, tuple) else result
            if not started:
                raise OSError("Windows could not start the selected Beta executable.")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot open in Beta", str(exc))
