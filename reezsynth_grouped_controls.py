"""Grouped-video controls, separate from independent keyframe row ranges."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout, QWidget)

from reezsynth_video_plan import validate_blend_options, validate_grouped_selection


class GroupedVideoControls(QWidget):
    def __init__(self, window):
        super().__init__()
        self.w = window
        layout = QVBoxLayout(self)
        note = QLabel("Render one video using multiple styled keyframes. Choose input folders on Video / Keyframes.\n"
                      "The range and selection here are separate from the independent-job table.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        layout.addLayout(form)
        self.full_range = QCheckBox("Use full source range")
        self.full_range.setChecked(True)
        form.addRow(self.full_range)
        self.start = QSpinBox()
        self.end = QSpinBox()
        for widget in (self.start, self.end):
            widget.setRange(0, 2147483647)
        endpoints = QHBoxLayout()
        endpoints.addWidget(QLabel("First frame"))
        endpoints.addWidget(self.start)
        endpoints.addWidget(QLabel("Last frame (inclusive)"))
        endpoints.addWidget(self.end)
        form.addRow("Grouped range", endpoints)
        self.keys = QListWidget()
        form.addRow("Styled keyframes", self.keys)
        self.folder = QLineEdit("grouped_video")
        form.addRow("Output subfolder", self.folder)
        self.mode = QComboBox()
        self.mode.addItem("Blend between keyframes", "none")
        self.mode.addItem("Forward only between keyframes", "forward")
        self.mode.addItem("Reverse only between keyframes", "reverse")
        form.addRow("Propagation mode", self.mode)
        mode_note = QLabel("Before the first selected keyframe, propagation runs backward; after the last, it runs forward.")
        mode_note.setWordWrap(True)
        form.addRow(mode_note)
        self.gpu = QCheckBox("Use GPU for blending (requires CuPy)")
        form.addRow(self.gpu)
        self.solver = QComboBox()
        self.solver.addItems(["LSQR", "LSMR"])
        form.addRow("CPU Poisson solver", self.solver)
        self.poisson_gpu = QCheckBox("Use CuPy Poisson reconstruction (LSMR)")
        form.addRow(self.poisson_gpu)
        self.maxiter = QSpinBox()
        self.maxiter.setRange(0, 2147483647)
        self.maxiter.setSpecialValueText("Automatic")
        self.maxiter.setToolTip("Applies to LSMR. Zero selects the solver's automatic iteration limit.")
        form.addRow("LSMR iteration limit", self.maxiter)
        self.run = QPushButton("Render Grouped Video")
        layout.addWidget(self.run)
        self.state = QLabel("Select at least two keyframes to render a grouped video.")
        self.bar = QProgressBar()
        layout.addWidget(self.state)
        layout.addWidget(self.bar)
        self.row = dict(key="grouped video", label="Grouped video", state=self.state, bar=self.bar)
        self.editors = [self.full_range, self.start, self.end, self.keys, self.folder,
                        self.mode, self.gpu, self.solver, self.poisson_gpu, self.maxiter, self.run]
        window.locked.extend(self.editors)
        self.run.clicked.connect(lambda: window.run_rows([], grouped=True))
        for widget in (self.full_range, self.gpu, self.poisson_gpu):
            widget.toggled.connect(self.changed)
        for widget in (self.mode, self.solver):
            widget.currentIndexChanged.connect(self.changed)
        for widget in (self.start, self.end, self.maxiter):
            widget.valueChanged.connect(self.changed)
        self.keys.itemChanged.connect(self.changed)
        self.folder.textChanged.connect(self.changed)
        self.update_enabled()

    def changed(self, *_):
        self.update_enabled()
        if hasattr(self.w, "options"):
            self.w.options.changed()

    def update_enabled(self):
        editable = not self.w.busy and not self.w.close_when_idle
        for widget in self.editors:
            widget.setEnabled(editable)
        self.start.setEnabled(editable and not self.full_range.isChecked())
        self.end.setEnabled(editable and not self.full_range.isChecked())
        blending = editable and self.mode.currentData() == "none"
        for widget in (self.gpu, self.solver, self.poisson_gpu, self.maxiter):
            widget.setEnabled(blending)
        self.poisson_gpu.setEnabled(blending and self.gpu.isChecked())
        if not self.gpu.isChecked():
            blocker = QSignalBlocker(self.poisson_gpu)
            self.poisson_gpu.setChecked(False)
            del blocker
        self.solver.setEnabled(blending and not self.poisson_gpu.isChecked())
        self.maxiter.setEnabled(blending and (self.poisson_gpu.isChecked() or self.solver.currentText() == "LSMR"))
        self.run.setEnabled(editable and len(self.w.keys) >= 2)

    def sync_inputs(self):
        blocker = QSignalBlocker(self.keys)
        self.keys.clear()
        for number, path in sorted(self.w.keys.items()):
            item = QListWidgetItem(f"{number}: {path.name}")
            item.setData(Qt.ItemDataRole.UserRole, number)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(str(path))
            self.keys.addItem(item)
        del blocker
        if self.w.video:
            self.start.setValue(min(self.w.video))
            self.end.setValue(max(self.w.video))
        self.full_range.setChecked(True)
        self.update_enabled()

    def selection(self):
        selected = [self.keys.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.keys.count()) if self.keys.item(i).checkState() == Qt.CheckState.Checked]
        return validate_grouped_selection(dict(start=None if self.full_range.isChecked() else self.start.value(),
            end=None if self.full_range.isChecked() else self.end.value(),
            keyframes=selected, folder=self.folder.text()))

    def blend_options(self):
        return validate_blend_options(dict(only_mode=self.mode.currentData(), use_gpu=self.gpu.isChecked(),
            use_lsqr=self.solver.currentText() == "LSQR", use_poisson_cupy=self.poisson_gpu.isChecked(),
            poisson_maxiter=self.maxiter.value() or None))

    def set_blend_options(self, data):
        data = validate_blend_options(data)
        self.mode.setCurrentIndex(self.mode.findData(data["only_mode"]))
        self.gpu.setChecked(data["use_gpu"])
        self.poisson_gpu.setChecked(data["use_poisson_cupy"])
        self.solver.setCurrentText("LSQR" if data["use_lsqr"] else "LSMR")
        self.maxiter.setValue(data["poisson_maxiter"] or 0)
        self.update_enabled()

    def set_selection(self, data):
        data = validate_grouped_selection(data)
        self.sync_inputs()
        self.folder.setText(data["folder"])
        self.full_range.setChecked(data["start"] is None)
        if data["start"] is not None:
            self.start.setValue(data["start"])
            self.end.setValue(data["end"])
        selected = data["keyframes"]
        if selected is not None:
            available = set(self.w.keys)
            if set(selected) - available:
                raise ValueError("Saved grouped keyframes are missing from the input folders.")
            for index in range(self.keys.count()):
                item = self.keys.item(index)
                item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in selected else Qt.CheckState.Unchecked)
        self.update_enabled()
