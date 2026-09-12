"""Grouped-video controls, separate from independent keyframe row ranges."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QVBoxLayout, QWidget)

from reezsynth_widget_style import QueueDoubleSpinBox, QueueSpinBox

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
        self.form = form
        layout.addLayout(form)
        self.full_range = QCheckBox("Use full source range")
        self.full_range.setChecked(True)
        form.addRow(self.full_range)
        self.start = QueueSpinBox()
        self.end = QueueSpinBox()
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
        form.addRow('Propagation mode', self.mode)
        mode_note = QLabel("Before the first selected keyframe, propagation runs backward; after the last, it runs forward.")
        mode_note.setWordWrap(True)
        form.addRow(mode_note)
        self.gpu = QCheckBox("Use GPU for blending (requires CuPy) [Trentonom0r3 only]")
        form.addRow(self.gpu)
        self.solver = QComboBox()
        self.solver.addItems(["LSQR", "LSMR"])
        form.addRow("CPU Poisson solver [Trentonom0r3 only]", self.solver)
        self.poisson_gpu = QCheckBox("Use CuPy Poisson reconstruction (LSMR) [Trentonom0r3 only]")
        form.addRow(self.poisson_gpu)
        self.maxiter = QueueSpinBox()
        self.maxiter.setRange(0, 2147483647)
        self.maxiter.setSpecialValueText("Automatic")
        self.maxiter.setToolTip('Legacy: LSMR only. FuouM: LSQR/LSMR/CG/AMG. Zero uses automatic limits (AMG: 100).')
        form.addRow('Poisson iteration limit', self.maxiter)
        self.fuoum_solver = QComboBox()
        self.fuoum_solver.addItems(['lsqr', 'lsmr', 'cg', 'amg', 'seamless', 'disabled'])
        self.fuoum_solver.setToolTip('FuouM/ReEzSynth reconstruction method. AMG requires pyamg in the FuouM environment.')
        form.addRow('Poisson solver [FuouM only]', self.fuoum_solver)
        self.fuoum_grad_weight_l = QueueDoubleSpinBox()
        self.fuoum_grad_weight_ab = QueueDoubleSpinBox()
        for widget, value in ((self.fuoum_grad_weight_l, 2.5), (self.fuoum_grad_weight_ab, .5)):
            widget.setRange(0, 10000)
            widget.setDecimals(6)
            widget.setSingleStep(.1)
            widget.setValue(value)
        form.addRow('Luminance gradient weight [FuouM only]', self.fuoum_grad_weight_l)
        form.addRow('Chroma gradient weight [FuouM only]', self.fuoum_grad_weight_ab)
        self.run = QPushButton("Render Grouped Video")
        layout.addWidget(self.run)
        self.state = QLabel("Select at least two keyframes to render a grouped video.")
        self.bar = QProgressBar()
        layout.addWidget(self.state)
        layout.addWidget(self.bar)
        self.row = dict(key="grouped video", label="Grouped video", state=self.state, bar=self.bar)
        self.editors = [self.full_range, self.start, self.end, self.keys, self.folder,
                        self.mode, self.gpu, self.solver, self.poisson_gpu, self.maxiter, self.fuoum_solver,
                        self.fuoum_grad_weight_l, self.fuoum_grad_weight_ab, self.run]
        window.locked.extend(self.editors)
        self.run.clicked.connect(lambda: window.run_rows([], grouped=True))
        for widget in (self.full_range, self.gpu, self.poisson_gpu):
            widget.toggled.connect(self.changed)
        for widget in (self.mode, self.solver, self.fuoum_solver):
            widget.currentIndexChanged.connect(self.changed)
        for widget in (self.start, self.end, self.maxiter, self.fuoum_grad_weight_l, self.fuoum_grad_weight_ab):
            widget.valueChanged.connect(self.changed)
        self.keys.itemChanged.connect(self.changed)
        self.folder.textChanged.connect(self.changed)
        self.update_enabled()
        self.refresh_engine_controls(False)

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
        fuoum = (hasattr(self.w, 'options') and
                 self.w.options.widgets['render']['engine'].currentText() == 'FuouM/ReEzSynth')
        for widget in (self.gpu, self.solver, self.poisson_gpu):
            widget.setEnabled(blending and not fuoum)
        self.maxiter.setEnabled(blending)
        self.poisson_gpu.setEnabled(blending and not fuoum and self.gpu.isChecked())
        if not self.gpu.isChecked():
            blocker = QSignalBlocker(self.poisson_gpu)
            self.poisson_gpu.setChecked(False)
            del blocker
        self.solver.setEnabled(blending and not fuoum and not self.poisson_gpu.isChecked())
        iterative = self.fuoum_solver.currentText() in ('lsqr', 'lsmr', 'cg', 'amg')
        self.maxiter.setEnabled(blending and (iterative if fuoum else
                                             self.poisson_gpu.isChecked() or self.solver.currentText() == 'LSMR'))
        for widget in (self.fuoum_solver, self.fuoum_grad_weight_l, self.fuoum_grad_weight_ab):
            widget.setEnabled(blending and fuoum)
        for widget in (self.fuoum_grad_weight_l, self.fuoum_grad_weight_ab):
            widget.setEnabled(blending and fuoum and iterative)
        self.run.setEnabled(editable and len(self.w.keys) >= 2)

    def refresh_engine_controls(self, fuoum):
        for widget in (self.fuoum_solver, self.fuoum_grad_weight_l, self.fuoum_grad_weight_ab):
            self.form.setRowVisible(widget, True)
        for index in (1, 2):
            self.mode.model().item(index).setEnabled(True)
        self.update_enabled()

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

    def blend_options(self, effective=False):
        data = dict(only_mode=self.mode.currentData(), use_gpu=self.gpu.isChecked(),
            use_lsqr=self.solver.currentText() == "LSQR", use_poisson_cupy=self.poisson_gpu.isChecked(),
            poisson_maxiter=self.maxiter.value() or None, fuoum_poisson_solver=self.fuoum_solver.currentText(),
            fuoum_poisson_grad_weight_l=self.fuoum_grad_weight_l.value(),
            fuoum_poisson_grad_weight_ab=self.fuoum_grad_weight_ab.value())
        if effective and self.w.options.widgets['render']['engine'].currentText() == 'FuouM/ReEzSynth':
            data.update(use_gpu=False, use_poisson_cupy=False)
        return validate_blend_options(data)

    def set_blend_options(self, data):
        data = validate_blend_options(data)
        self.mode.setCurrentIndex(self.mode.findData(data["only_mode"]))
        self.gpu.setChecked(data["use_gpu"])
        self.poisson_gpu.setChecked(data["use_poisson_cupy"])
        self.solver.setCurrentText("LSQR" if data["use_lsqr"] else "LSMR")
        self.maxiter.setValue(data["poisson_maxiter"] or 0)
        self.fuoum_solver.setCurrentText(data['fuoum_poisson_solver'])
        self.fuoum_grad_weight_l.setValue(data['fuoum_poisson_grad_weight_l'])
        self.fuoum_grad_weight_ab.setValue(data['fuoum_poisson_grad_weight_ab'])
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
