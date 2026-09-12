"""Frontend options, presets and optional automation. No engine imports."""
import json
import os
import sys
from reezsynth_widget_style import QueueDoubleSpinBox, QueueSpinBox, PyramidLevelsSpinBox
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QSettings, QTimer, QUrl
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from reezsynth_config import (APPLICATION, GROUPS, LIMITS, PREVIEW, RENDER, STANDARD, HIGHEST, quality_profile,
    WEIGHTS, PresetStore, atomic_json, discover_pairs, install_optional_flow_files,
    optional_flow_status, validate_application,
    validate_group, validate_render, validate_weights)
from reezsynth_project_controls import (project_naming, set_project_naming,
    update_naming_preview)
from reezsynth_preview import LivePreviewWindow
from reezsynth_video_plan import validate_blend_options, validate_grouped_selection
from reezsynth_engines import LEGACY, FUOUM, default_runtime, engine_revision

LABELS = dict(edg_wgt="Edge guide", img_wgt="Video weight", pos_wgt="Mapping (position guide)",
    memory_efficient_raft="Memory-efficient RAFT correlation (CUDA)",
    key_wgt="Key weight", mask_wgt="Mask guide weight",
    wrp_wgt="Deflicker (warped-style guide)", uniformity="Diversity (uniformity)", patchsize="Patch size (odd)",
    pyramidlevels="Pyramid levels", searchvoteiters="Search/vote iterations",
    patchmatchiters="Patch-match iterations", extrapass3x3="Extra 3x3 polishing pass",
    edge_method="Edge method", do_mask="Use masks", pre_mask="Mask inputs before synthesis",
    custom_edge_guides="Use custom edge-guide frames",
    flow_arch="Flow architecture (video only)", flow_model="Flow model (video only)", ebsynth_backend="EbSynth backend",
    feather="Mask feather size (zero or odd)", discover="Discover matching input subfolders",
    keys_prefix="Keyframe folder prefix", video_prefix="Video folder prefix",
    auto_start="Start automatically when inputs are ready", wait_for_mask="Wait for masks before automatic start",
    parallel="Enable parallel rendering", parallel_limit="Maximum simultaneous renders (0 = unlimited)",
    sound_enabled="Enable completion sounds", sound_each="Play after each render",
    sound_queue="Play when the queue completes", sound_file="Custom WAV sound (blank = bundled sound)")
LABELS["preview_limit"] = "Maximum live previews"
LABELS.update(engine='Synthesis engine', temporal_nnf='Temporal NNF propagation (FuouM)',
              sparse_features='Sparse feature guides (FuouM)',
              fuoum_source='FuouM source folder (blank = project default)',
              fuoum_python='FuouM Python executable (blank = project default)')


def control_value(widget):
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QComboBox):
        return widget.currentText()
    if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        return widget.value()
    return widget.text()


def set_control(widget, value):
    if isinstance(widget, QCheckBox):
        widget.setChecked(value)
    elif isinstance(widget, QComboBox):
        widget.setCurrentText(value)
    elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        widget.setValue(value)
    else:
        widget.setText(value)


class Options(QObject):
    def __init__(self, window, page, form, settings_page, settings_layout):
        super().__init__(window)
        self.w = window
        self.loading = True
        self.default_project = window.project_dir.text()
        self.last_auto = None
        self.auto_armed = False
        self.widgets = {}
        self.preset_boxes = {}
        self.policy_boxes = {}
        self.sound = None
        self.errors = []
        preferences = window.preferences
        if preferences.format() == QSettings.Format.IniFormat:
            self.directory = Path(preferences.fileName()).parent / "configuration"
        else:
            self.directory = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ReEzSynth"
        self.last_path = self.directory / "last-used.json"
        self.app_path = self.directory / "application.json"
        self.store = None
        try:
            self.store = PresetStore(self.directory / "presets.json")
        except (OSError, ValueError) as exc:
            self.errors.append(f"Presets could not be loaded: {exc}. Import a valid file to recover.")
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(150)
        self.save_timer.timeout.connect(self.persist)
        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.setInterval(700)
        self.auto_timer.timeout.connect(self.maybe_start)
        self.discovery_timer = QTimer(self)
        self.discovery_timer.setSingleShot(True)
        self.discovery_timer.setInterval(700)
        self.discovery_timer.timeout.connect(self.discover)

        window.mask_dir = window.path_row(form, "Masks (optional)")
        window.edge_dir = window.path_row(form, "Custom edge guides (optional)")
        window.directory_layout.insertLayout(0, self.preset_bar("directories", "Directory presets"))
        window.output_group.layout().insertLayout(0, self.preset_bar("output", "Output presets"))
        window.image_synthesis.layout.insertLayout(1, self.preset_bar('image', 'Image presets'))
        window.grouped.layout().insertLayout(1, self.preset_bar('grouped', 'Blend / Flow presets'))
        advanced = QGroupBox("Rendering controls")
        advanced_layout = QVBoxLayout(advanced)
        self.engine_note = QLabel('FuouM supports image synthesis and RAFT video with normal grouped blending. '
                                 'Masks, custom edge sequences, video auxiliary exports and CuPy blending '
                                 'are currently available with Trentonom0r3/Ezsynth. Engine selection applies to the next queue.')
        self.engine_note.setWordWrap(True)
        self.engine_note.hide()
        advanced_layout.addWidget(self.engine_note)
        self.export_widgets = {}
        for name, label in (("maps", "Export numerical error / selection maps (.npy)"),
                            ("flow", "Export flow visualizations (.png)")):
            widget = QCheckBox(label)
            widget.setToolTip("Applies to independent and grouped video. Saved under auxiliary/ with a metadata manifest.")
            widget.toggled.connect(self.changed)
            self.export_widgets[name] = widget
            advanced_layout.addWidget(widget)
            window.locked.append(widget)
        columns = QHBoxLayout()
        control_forms = {}
        for group, defaults, title in (("weights", WEIGHTS, "Guide weights"), ("render", RENDER, "Synthesis")):
            box = QGroupBox(title)
            layout = QVBoxLayout(box)
            layout.addLayout(self.preset_bar(group, title + " presets"))
            fields = QFormLayout()
            control_forms[group] = fields
            if group == 'render':
                self.render_fields = fields
            self.widgets[group] = {}
            if group == 'render':
                fields.addRow('Quality', window.quality)
            for name, default in defaults.items():
                widget = self.make_control(name, default)
                self.widgets[group][name] = widget
                if name == 'do_mask':
                    widget.setText('Masks')
                    widget.setToolTip('Uncheck to ignore masks for synthesis and compositing; the folder stays remembered.')
                    mask_row = window.mask_dir.parentWidget()
                    row_index, _ = form.getWidgetPosition(mask_row)
                    old_label = form.labelForField(mask_row)
                    form.removeWidget(old_label)
                    old_label.hide()
                    old_label.deleteLater()
                    form.setWidget(row_index, QFormLayout.ItemRole.LabelRole, widget)
                elif name in ('key_wgt', 'img_wgt', 'mask_wgt'):
                    field = {'key_wgt': window.keyframe_dir, 'img_wgt': window.video_dir,
                             'mask_wgt': window.mask_dir}[name]
                    widget.setFixedWidth(90)
                    widget.setAccessibleName(LABELS[name])
                    widget.setToolTip(LABELS[name])
                    field.parentWidget().layout().insertWidget(1, widget)
                else:
                    fields.addRow(LABELS[name], widget)
                if name == 'key_wgt':
                    widget.setMinimum(0.001)
                    widget.setToolTip('Style-to-guide ratio: guide weights are divided by this value. Default 1 preserves Ezsynth behavior.')
                elif name == 'memory_efficient_raft':
                    widget.setToolTip('Video only. Uses the compiled alt_cuda_corr extension at full resolution, without the large all-pairs table. Requires the optional extension installation. No slow fallback or image resizing. Other render stages still need GPU memory.')
                elif name == 'custom_edge_guides':
                    widget.setToolTip('Uses numbered edge-guide frames from Custom edge guides instead of computing Classic, PST, or PAGE edges.')
                elif name == 'flow_model':
                    widget.setToolTip('Choices follow the selected flow architecture. Optional architectures need their own model files. Image Synthesis does not use optical flow.')
                elif name == 'flow_arch':
                    widget.setToolTip('RAFT is bundled and supported by default. EF-RAFT and FlowDiffuser need their optional dependencies and weights before a queue can start.')
                elif name == 'ebsynth_backend':
                    widget.setToolTip('Controls native EbSynth synthesis. CUDA is the working default; Auto lets its DLL choose, while CPU avoids its CUDA backend. Video optical flow may still use PyTorch CUDA when available.')
                elif name == 'mask_wgt':
                    widget.setToolTip('Additional mask correspondence guide when masks are enabled. Zero disables this guide; mask compositing remains controlled by Enable masks.')
                elif name in ('pos_wgt', 'wrp_wgt', 'uniformity'):
                    widget.setToolTip('Ezsynth control with a related purpose to the EbSynth Beta setting; numerical equivalence is not guaranteed.')
            layout.addLayout(fields)
            if group == 'weights':
                window.directory_layout.addWidget(box)
            else:
                columns.addWidget(box)
        edge_row = control_forms['weights'].takeRow(self.widgets['weights']['edg_wgt'])
        diversity_row = control_forms['render'].takeRow(self.widgets['render']['uniformity'])
        control_forms['weights'].addRow(diversity_row.labelItem.widget(), diversity_row.fieldItem.widget())
        control_forms['render'].insertRow(0, edge_row.labelItem.widget(), edge_row.fieldItem.widget())
        self.refresh_flow_model_choices()
        self.widgets['render']['flow_arch'].currentTextChanged.connect(self.refresh_flow_model_choices)
        self.widgets['render']['flow_arch'].currentTextChanged.connect(self.optional_flow_arch_changed)
        advanced_layout.addLayout(columns)
        advanced_layout.addWidget(QLabel("Preview, Standard, and Highest reset synthesis parameters only; guide weights are independent.\n"
            "Flow model and EbSynth backend are saved with rendering presets. Use Blend / Flow for grouped video."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(advanced)
        window.tabs.insertTab(1, scroll, "Rendering")
        self.widgets["application"] = {"reuse_queue_worker": window.reuse_worker}
        settings_layout.insertLayout(0, self.preset_bar("application", "Application presets"))
        fields = QFormLayout()
        for name, default in APPLICATION.items():
            if name == "reuse_queue_worker":
                continue
            widget = self.make_control(name, default)
            self.widgets["application"][name] = widget
            fields.addRow(LABELS[name], widget)
        settings_layout.insertLayout(1, fields)
        settings_layout.insertWidget(2, QLabel("Parallel mode uses separate workers and more GPU memory.\n"
            "Disabled by default; worker reuse applies to sequential queues."))
        sound_pick = QPushButton("Choose completion sound...")
        sound_pick.clicked.connect(self.choose_sound)
        settings_layout.insertWidget(3, sound_pick)
        window.locked.append(sound_pick)
        startup = QGroupBox("On startup")
        startup_form = QFormLayout(startup)
        for group in GROUPS:
            box = QComboBox()
            box.currentIndexChanged.connect(self.changed)
            self.policy_boxes[group] = box
            startup_form.addRow(group.capitalize(), box)
            window.locked.append(box)
        settings_layout.insertWidget(4, startup)
        file_buttons = QHBoxLayout()
        for label, callback in (("Import presets...", self.import_presets), ("Export presets...", self.export_presets)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            file_buttons.addWidget(button)
            window.locked.append(button)
        settings_layout.insertLayout(5, file_buttons)
        location = QLabel(f"Presets: {self.directory / 'presets.json'}\nLast used: {self.last_path}")
        location.setWordWrap(True)
        settings_layout.insertWidget(6, location)
        reset = QPushButton("Reset all settings to defaults")
        reset.setToolTip("Restores every section's built-in Default values. Saved projects and custom presets are not deleted.")
        reset.clicked.connect(self.reset_all)
        settings_layout.insertWidget(7, reset)
        window.locked.append(reset)
        self.add_optional_flow_controls(settings_layout)
        # The settings page is already a tab; the toolbar opens live output previews.
        preview_button = QPushButton("Previews")
        window.preview_window = LivePreviewWindow(window)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_index = window.tabs.indexOf(settings_page)
        window.tabs.removeTab(settings_index)
        settings_scroll.setWidget(settings_page)
        window.tabs.insertTab(settings_index, settings_scroll, "Settings")
        preview_button.clicked.connect(window.preview_window.show)
        page.itemAt(0).layout().addWidget(preview_button)
        window.preview_button = preview_button
        for field in (window.project_dir, window.keyframe_dir, window.video_dir, window.mask_dir, window.edge_dir):
            field.textChanged.connect(self.changed)
        window.project_dir.textChanged.connect(self.discovery_changed)
        for field in (window.keyframe_dir, window.video_dir, window.mask_dir, window.edge_dir):
            field.textChanged.connect(self.inputs_changed)
        window.quality.currentTextChanged.connect(self.quality_changed)
        window.resolution.currentIndexChanged.connect(self.changed)
        window.processing_width.valueChanged.connect(self.changed)
        window.processing_height.valueChanged.connect(self.changed)
        window.batch_name_pattern.textChanged.connect(self.changed)
        window.job_name_pattern.textChanged.connect(self.changed)
        window.output_location.currentIndexChanged.connect(self.changed)
        window.batch_enabled.toggled.connect(self.changed)
        window.custom_output.textChanged.connect(self.changed)
        window.mask_dir.textChanged.connect(window.schedule_scan)
        self.widgets["application"]["discover"].toggled.connect(self.discovery_changed)
        for name in ("keys_prefix", "video_prefix"):
            self.widgets["application"][name].textChanged.connect(self.discovery_changed)
        self.widgets["application"]["auto_start"].toggled.connect(self.inputs_changed)
        self.widgets["application"]["wait_for_mask"].toggled.connect(self.inputs_changed)
        self.widgets["application"]["auto_start"].setToolTip(
            "Runs after input edits, directory preset selection, or enabling this option. "
            "Restoring startup settings and opening a saved project do not start rendering.")
        self.refresh_presets()

    def make_control(self, name, default):
        if isinstance(default, bool):
            widget = QCheckBox()
            widget.setChecked(default)
            widget.toggled.connect(self.changed)
        elif name == 'engine':
            widget = QComboBox()
            widget.addItems([LEGACY, FUOUM])
            widget.currentTextChanged.connect(self.changed)
            widget.currentTextChanged.connect(self.refresh_engine_controls)
        elif name == "edge_method":
            widget = QComboBox()
            widget.addItems(["Classic", "PST", "PAGE"])
            widget.currentTextChanged.connect(self.changed)
        elif name == "flow_model":
            widget = QComboBox()
            widget.addItems(["sintel", "kitti"])
            widget.currentTextChanged.connect(self.changed)
        elif name == "flow_arch":
            widget = QComboBox()
            widget.addItems(["RAFT", "EF_RAFT", "FLOW_DIFF"])
            widget.currentTextChanged.connect(self.changed)
        elif name == "ebsynth_backend":
            widget = QComboBox()
            widget.addItems(["cuda", "auto", "cpu"])
            widget.currentTextChanged.connect(self.changed)
        elif isinstance(default, (int, float)):
            widget = (PyramidLevelsSpinBox() if name == 'pyramidlevels' else
                      QueueSpinBox() if isinstance(default, int) else QueueDoubleSpinBox())
            low, high = LIMITS.get(name, (0, 64 if name == "parallel_limit" else 10000))
            widget.setRange(low, high)
            if name == 'pyramidlevels':
                widget.setSpecialValueText('Automatic')
                widget.setToolTip('Automatic uses all pyramid levels supported by the input size and patch size.')
            elif name == 'patchsize':
                widget.setToolTip('Odd sizes from 3 to 99. Processed style and target dimensions must each be at least twice the patch size plus one pixel.')
            if isinstance(widget, QDoubleSpinBox):
                # Preserve practical native float inputs through presets and
                # last-used settings instead of silently rounding to millis.
                widget.setDecimals(6)
                widget.setSingleStep(0.1)
            widget.setValue(default)
            widget.valueChanged.connect(self.changed)
        else:
            widget = QLineEdit(default)
            widget.textChanged.connect(self.changed)
        self.w.locked.append(widget)
        return widget

    def refresh_flow_model_choices(self, *_):
        """Keep the model selection valid when its architecture changes."""
        render = self.widgets.get('render', {})
        architecture = render.get('flow_arch')
        model = render.get('flow_model')
        if architecture is None or model is None:
            return
        choices = {
            'RAFT': ['sintel', 'kitti'],
            'EF_RAFT': ['25000_ours-sintel', 'ours_sintel', 'ours-things'],
            'FLOW_DIFF': ['FlowDiffuser-things'],
        }[architecture.currentText()]
        if architecture.currentText() != 'RAFT':
            installed = optional_flow_status()[architecture.currentText()]['models']
            if installed:
                choices = installed
        previous = model.currentText()
        model.blockSignals(True)
        model.clear()
        model.addItems(choices)
        model.setCurrentText(previous if previous in choices else choices[0])
        model.blockSignals(False)
        model.setEnabled(len(choices) > 1)
        self.changed()

    def optional_flow_arch_changed(self, architecture):
        if self.loading or architecture == 'RAFT':
            return
        status = optional_flow_status()[architecture]
        ready = bool(status['models']) and (architecture != 'FLOW_DIFF' or status['timm'])
        if ready:
            return
        if architecture == 'EF_RAFT':
            detail = ('No EF-RAFT checkpoint files are installed.' if not status['models']
                      else 'The selected EF-RAFT checkpoint is not installed.')
        else:
            missing = []
            if not status['models']:
                missing.append('FlowDiffuser-things.pth checkpoint')
            if not status['timm']:
                missing.append('timm Python package')
            detail = 'Missing: ' + ' and '.join(missing) + '.'
        box = self.widgets['render']['flow_arch']
        box.blockSignals(True)
        box.setCurrentText('RAFT')
        box.blockSignals(False)
        self.refresh_flow_model_choices()
        QMessageBox.warning(self.w, 'Optional flow files are not installed',
            f'{detail}\n\nUse Settings > Optional flow components to install the required files, then select this architecture again.')

    def add_optional_flow_controls(self, layout):
        box = QGroupBox('Optional flow components')
        form = QFormLayout(box)
        self.ef_flow_status = QLabel()
        self.flow_diff_status = QLabel()
        self.ef_flow_status.setWordWrap(True)
        self.flow_diff_status.setWordWrap(True)
        ef_install = QPushButton('Install EF-RAFT checkpoint files...')
        flow_install = QPushButton('Install FlowDiffuser checkpoint...')
        timm_install = QPushButton('Install FlowDiffuser timm package')
        ef_install.clicked.connect(lambda: self.install_optional_flow_checkpoints('EF_RAFT'))
        flow_install.clicked.connect(lambda: self.install_optional_flow_checkpoints('FLOW_DIFF'))
        timm_install.clicked.connect(self.install_flowdiffuser_timm)
        form.addRow('EF-RAFT', self.ef_flow_status)
        form.addRow('', ef_install)
        form.addRow('FlowDiffuser', self.flow_diff_status)
        form.addRow('', flow_install)
        form.addRow('', timm_install)
        layout.insertWidget(8, box)
        self.optional_flow_buttons = (ef_install, flow_install, timm_install)
        self.w.locked.extend(self.optional_flow_buttons)
        self.refresh_optional_flow_status()

    def refresh_optional_flow_status(self):
        status = optional_flow_status()
        ef = status['EF_RAFT']
        flow = status['FLOW_DIFF']
        self.ef_flow_status.setText('Installed: ' + (', '.join(ef['models']) or 'none') +
                                    '\nMissing: ' + (', '.join(ef['missing']) or 'none'))
        self.flow_diff_status.setText('Installed: ' + (', '.join(flow['models']) or 'none') +
                                      '\ntimm package: ' + ('installed' if flow['timm'] else 'missing'))

    def install_optional_flow_checkpoints(self, architecture):
        title = 'Install EF-RAFT checkpoints' if architecture == 'EF_RAFT' else 'Install FlowDiffuser checkpoint'
        paths, _ = QFileDialog.getOpenFileNames(self.w, title, '', 'PyTorch checkpoints (*.pth)')
        if not paths:
            return
        try:
            copied = install_optional_flow_files(architecture, paths)
            self.refresh_optional_flow_status()
            QMessageBox.information(self.w, title, 'Installed:\n' + '\n'.join(str(path) for path in copied))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.w, title, str(exc))

    def install_flowdiffuser_timm(self):
        if optional_flow_status()['FLOW_DIFF']['timm']:
            QMessageBox.information(self.w, 'FlowDiffuser dependency', 'The timm package is already installed.')
            return
        if QMessageBox.question(self.w, 'Install FlowDiffuser dependency?',
                'Install timm 0.6.12 into this ReEzSynth Python environment?\n\n'
                'FlowDiffuser is optional and requires a separate checkpoint. This downloads a Python package.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.timm_process = QProcess(self)
        self.timm_install_pending = True
        for button in self.optional_flow_buttons:
            button.setEnabled(False)
        self.timm_process.readyReadStandardOutput.connect(
            lambda: self.w.log.appendPlainText(bytes(self.timm_process.readAllStandardOutput()).decode('utf-8', 'replace').rstrip()))
        self.timm_process.readyReadStandardError.connect(
            lambda: self.w.log.appendPlainText(bytes(self.timm_process.readAllStandardError()).decode('utf-8', 'replace').rstrip()))
        self.timm_process.finished.connect(self.finished_install_flowdiffuser_timm)
        self.timm_process.errorOccurred.connect(self.flowdiffuser_timm_install_error)
        self.timm_process.start(sys.executable, ['-m', 'pip', 'install', 'timm==0.6.12'])

    def finished_install_flowdiffuser_timm(self, code, _status):
        if not getattr(self, 'timm_install_pending', False):
            return
        self.timm_install_pending = False
        for button in self.optional_flow_buttons:
            button.setEnabled(True)
        self.refresh_optional_flow_status()
        message = ('timm was installed successfully.' if code == 0 and optional_flow_status()['FLOW_DIFF']['timm']
                   else 'timm installation failed. See Diagnostics for pip output.')
        (QMessageBox.information if code == 0 else QMessageBox.warning)(self.w, 'FlowDiffuser dependency', message)

    def flowdiffuser_timm_install_error(self, _error):
        if not getattr(self, 'timm_install_pending', False):
            return
        self.w.log.appendPlainText('Could not start the FlowDiffuser timm installer.')
        self.finished_install_flowdiffuser_timm(-1, None)

    def installation_active(self):
        return bool(getattr(self, 'timm_install_pending', False))

    def preset_bar(self, group, label):
        layout = QHBoxLayout()
        layout.addWidget(QLabel(label))
        box = QComboBox()
        self.preset_boxes[group] = box
        box.activated.connect(lambda index, g=group: self.select_preset(g))
        layout.addWidget(box, 1)
        self.w.locked.append(box)
        for text, callback in (("+", self.save_preset), ("-", self.remove_preset)):
            button = QPushButton(text)
            button.setMaximumWidth(35)
            button.clicked.connect(lambda checked=False, g=group, cb=callback: cb(g))
            layout.addWidget(button)
            self.w.locked.append(button)
        return layout

    def refresh_presets(self):
        for group in GROUPS:
            names = sorted(self.store.groups[group], key=str.casefold) if self.store else []
            box = self.preset_boxes[group]
            previous = box.currentText()
            box.clear()
            box.addItem("Default", "__default__")
            for name in names:
                if name.casefold() != 'default':
                    box.addItem(name, name)
            box.setCurrentIndex(max(0, box.findText(previous)))
            if group in self.policy_boxes:
                policy = self.policy_boxes[group]
                value = policy.currentData() or "last"
                policy.blockSignals(True)
                policy.clear()
                policy.addItem("Restore last used", "last")
                policy.addItem("Use defaults", "defaults")
                for name in names:
                    policy.addItem("Preset: " + name, "preset:" + name)
                index = policy.findData(value)
                if index < 0 and value.startswith("preset:"):
                    policy.addItem("Missing " + value, value)
                    index = policy.count() - 1
                policy.setCurrentIndex(max(0, index))
                policy.blockSignals(False)

    def default_group(self, group):
        """Recommended built-in defaults, kept available even if preset storage fails."""
        if group == 'directories':
            return dict(project_dir=self.default_project, keyframe_dir='', video_dir='', mask_dir='', edge_dir='')
        if group == 'output':
            from reezsynth_project_controls import validate_project_naming
            return validate_project_naming(None)
        if group == 'weights':
            return dict(WEIGHTS)
        if group == 'render':
            return dict(options=dict(RENDER), quality='Standard', exports={})
        if group == 'grouped':
            return dict(selection=validate_grouped_selection(), blend_options=validate_blend_options())
        if group == 'application':
            return dict(APPLICATION)
        if group == 'image':
            return {}
        raise ValueError('Unknown preset group.')

    def snapshot(self, group, include_related=False):
        w = self.w
        if group == 'image':
            return w.image_synthesis.settings()
        if group == "directories":
            return {name: getattr(w, name).text() for name in ("project_dir", "keyframe_dir", "video_dir", "mask_dir", "edge_dir")}
        if group == 'output':
            return project_naming(w)
        if group == 'grouped':
            return dict(selection=w.grouped.selection(), blend_options=w.grouped.blend_options())
        if group == "render":
            result = dict(options={n: control_value(v) for n, v in self.widgets[group].items()},
                quality=w.quality.currentText(),
                exports={name: widget.isChecked() for name, widget in self.export_widgets.items()})
            result['engine_revision'] = engine_revision(result['options']['engine'])
            # Last-used setup retains related window controls. Named render presets
            # intentionally omit them so selecting a quality/render preset cannot
            # change output, resolution, or Blend / Flow choices.
            if include_related:
                result.update(processing_size=w.processing_size(), max_width=w.processing_max_width(),
                    output_naming=project_naming(w), blend_options=w.grouped.blend_options())
            return result
        return {name: control_value(widget) for name, widget in self.widgets[group].items()}

    def apply(self, group, data, restore_related=False):
        data = validate_group(group, data)
        previous = self.loading
        self.loading = True
        try:
            if group == 'image':
                self.w.image_synthesis.set_settings(data)
            elif group == "directories":
                for name, value in data.items():
                    getattr(self.w, name).setText(value)
            elif group == 'output':
                set_project_naming(self.w, data)
            elif group == 'grouped':
                self.w.grouped.set_selection(data['selection'])
                self.w.grouped.set_blend_options(data['blend_options'])
            elif group == "render":
                self.w.quality.setCurrentText(data["quality"])
                for name, value in data["options"].items():
                    set_control(self.widgets[group][name], value)
                for name, value in data["exports"].items():
                    self.export_widgets[name].setChecked(value)
                if restore_related:
                    self.w.set_processing_size(data["processing_size"], data['max_width'])
                    set_project_naming(self.w, data["output_naming"])
                    self.w.grouped.set_blend_options(data["blend_options"])
            else:
                for name, value in data.items():
                    set_control(self.widgets[group][name], value)
        finally:
            self.loading = previous
        self.changed()
        if group == "directories" and not self.loading:
            self.inputs_changed()
            self.w.schedule_scan()
        elif group == "application" and not self.loading:
            self.inputs_changed()
            self.discovery_changed()

    def restore(self):
        # Old QSettings values have already been restored by the GUI. They migrate
        # into the separate last-used file unless an explicit policy says otherwise.
        defaults = {group: self.default_group(group) for group in GROUPS}
        last, policy = {}, {}
        try:
            if self.app_path.exists():
                data = json.loads(self.app_path.read_text(encoding="utf-8"))
                if data.get("version") != 1 or not isinstance(data.get("startup"), dict):
                    raise ValueError("Invalid startup policy file.")
                policy = data["startup"]
            if self.last_path.exists():
                data = json.loads(self.last_path.read_text(encoding="utf-8"))
                if data.get("version") != 1 or not isinstance(data.get("groups"), dict):
                    raise ValueError("Invalid last-used file.")
                last = data["groups"]
            for group in GROUPS:
                mode = policy.get(group, "last")
                box = self.policy_boxes[group]
                index = box.findData(mode)
                if index < 0:
                    self.errors.append(f"Startup preset unavailable for {group}: {mode}; using defaults for this group.")
                    box.addItem("Missing " + str(mode), mode)
                    box.setCurrentIndex(box.count() - 1)
                    self.apply(group, defaults[group])
                    continue
                box.setCurrentIndex(index)
                try:
                    if mode == "defaults":
                        self.apply(group, defaults[group])
                    elif mode.startswith("preset:"):
                        self.apply(group, self.store.groups[group][mode[7:]])
                    elif group in last:
                        self.apply(group, last[group], restore_related=(group == 'render'))
                except (ValueError, TypeError, KeyError) as exc:
                    self.errors.append(f"Could not restore {group}: {exc}; using defaults for this group.")
                    self.apply(group, defaults[group])
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.errors.append(f"Startup settings could not be restored: {exc}")
        if "render" not in last and policy.get("render", "last") == "last":
            for name, value in quality_profile(self.w.quality.currentText()).items():
                set_control(self.widgets["render"][name], value)
        self.loading = False
        # Restoring folders does not arm unattended rendering on application startup.
        self.auto_armed = False
        for message in self.errors:
            self.w.log.appendPlainText(message)
        self.changed()

    def changed(self, *_):
        if not self.loading and not self.w.loading_project:
            self.save_timer.start()
            self.refresh_engine_controls()

    def refresh_engine_controls(self, *_):
        widgets = self.widgets.get('render', {})
        if not all(name in widgets for name in ('engine', 'temporal_nnf', 'sparse_features')):
            return
        fuoum = widgets['engine'].currentText() == FUOUM
        self.engine_note.setVisible(fuoum)
        editable = not self.w.busy and not self.w.close_when_idle
        for name in ('temporal_nnf', 'sparse_features'):
            self.render_fields.setRowVisible(widgets[name], fuoum)
            widgets[name].setEnabled(editable and fuoum)
        # Keep selected unsupported values editable so they can be cleared. Loading a
        # project never silently changes its settings; preflight reports incompatibility.
        for name in ('do_mask', 'pre_mask', 'custom_edge_guides', 'memory_efficient_raft'):
            widgets[name].setEnabled(editable and (not fuoum or widgets[name].isChecked()))
        for name in ('flow_arch', 'ebsynth_backend'):
            default = 'RAFT' if name == 'flow_arch' else 'cuda'
            widgets[name].setEnabled(editable and (not fuoum or widgets[name].currentText() != default))
        for widget in self.export_widgets.values():
            widget.setEnabled(editable and (not fuoum or widget.isChecked()))
        for name, path in default_runtime().items():
            if name in self.widgets.get('application', {}):
                self.widgets['application'][name].setPlaceholderText(path)

    def persist(self):
        if self.loading:
            return
        self.save_timer.stop()
        try:
            groups = {group: self.snapshot(group, include_related=(group == 'render')) for group in GROUPS}
            atomic_json(self.last_path, dict(version=1, groups=groups))
            atomic_json(self.app_path, dict(version=1,
                startup={g: b.currentData() for g, b in self.policy_boxes.items()}))
        except (OSError, ValueError) as exc:
            self.w.log.appendPlainText(f"Settings could not be saved: {exc}")

    def quality_changed(self, quality):
        if not self.loading:
            for name, value in quality_profile(quality).items():
                set_control(self.widgets["render"][name], value)
            self.changed()

    def reset_all(self):
        if self.w.busy or self.w.close_when_idle:
            return
        answer = QMessageBox.question(
            self.w, "Reset all settings?",
            "Restore the built-in Default values for directories, output naming, "
            "weights, Rendering, Blend / Flow, application settings, and Image Synthesis?\n\n"
            "Saved project files and custom preset files are not deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        previous = self.loading
        self.loading = True
        try:
            for group in GROUPS:
                self.apply(group, self.default_group(group))
            for box in self.policy_boxes.values():
                box.setCurrentIndex(box.findData('defaults'))
        finally:
            self.loading = previous
        self.w.queue_summary.setText('')
        self.w.summary.setText('Settings restored to Default values. Select source and keyframe folders to rebuild the queue.')
        self.persist()

    def select_preset(self, group):
        name = self.preset_boxes[group].currentData()
        if name == '__default__':
            self.apply(group, self.default_group(group))
        elif name and self.store:
            self.apply(group, self.store.groups[group][name])

    def save_preset(self, group):
        if self.store is None:
            QMessageBox.warning(self.w, "Presets unavailable", "Import a valid preset file first; the original file was preserved.")
            return
        name, ok = QInputDialog.getText(self.w, "Save preset", "Preset name:",
            text="" if self.preset_boxes[group].currentData() == '__default__' else self.preset_boxes[group].currentData() or "")
        if not ok:
            return
        try:
            name = name.strip()
            if name.casefold() == 'default':
                raise ValueError("Default is a built-in preset and cannot be replaced.")
            existing = self.store.existing(group, name)
            if existing and QMessageBox.question(self.w, "Overwrite preset?",
                    f"'{existing}' already exists. Overwrite it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            self.store.save(group, name, self.snapshot(group), overwrite=bool(existing))
            self.refresh_presets()
            self.preset_boxes[group].setCurrentText(name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.w, "Cannot save preset", str(exc))

    def remove_preset(self, group):
        name = self.preset_boxes[group].currentData()
        if name == '__default__':
            QMessageBox.information(self.w, "Built-in preset", "Default is always available and cannot be removed.")
            return
        if not name or not self.store:
            return
        if QMessageBox.question(self.w, "Remove preset?", f"Remove '{name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.remove(group, name)
            self.refresh_presets()
        except OSError as exc:
            QMessageBox.warning(self.w, "Cannot remove preset", str(exc))

    def import_presets(self):
        path, _ = QFileDialog.getOpenFileName(self.w, "Import presets", "", "Preset library (*.json *.yaml *.yml)")
        if not path:
            return
        try:
            groups = PresetStore.read(path)
            if QMessageBox.question(self.w, "Replace preset library?", "Replace the local preset library with this file?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            target = self.directory / "presets.json"
            atomic_json(target, dict(format="ReEzSynth-presets", version=1, groups=groups))
            self.store = PresetStore(target)
            self.refresh_presets()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.w, "Cannot import presets", str(exc))

    def export_presets(self):
        if not self.store:
            return
        path, _ = QFileDialog.getSaveFileName(self.w, "Export presets", "reezsynth-presets.json", "Preset library (*.json *.yaml *.yml)")
        if path:
            try:
                self.store.write(self.store.groups, path)
            except OSError as exc:
                QMessageBox.warning(self.w, "Cannot export presets", str(exc))

    def discovery_changed(self, *_):
        if not self.loading and not self.w.loading_project and not self.w.busy:
            self.discovery_timer.start()

    def discover(self):
        if self.w.busy or self.w.close_when_idle or not self.application()["discover"]:
            return
        if QApplication.activeModalWidget() is not None:
            self.discovery_timer.start()
            return
        try:
            config = validate_application(self.application())
            pairs = discover_pairs(self.w.project_dir.text(), config["keys_prefix"], config["video_prefix"])
            if not pairs:
                self.w.status.setText("No matching keyframe/video subfolders found.")
                return
            index = 0
            if len(pairs) > 1:
                labels = [f"{k} | {v}" for k, v in pairs]
                selected, ok = QInputDialog.getItem(self.w, "Choose input folders", "Matching pairs:", labels, 0, False)
                if not ok:
                    return
                index = labels.index(selected)
            data = self.snapshot("directories")
            data.update(keyframe_dir=str(pairs[index][0]), video_dir=str(pairs[index][1]))
            self.apply("directories", data)
        except (OSError, ValueError) as exc:
            self.w.status.setText(f"Cannot discover folders: {exc}")

    def inputs_changed(self, *_):
        if self.loading or self.w.loading_project or self.w.busy or self.w.close_when_idle:
            return
        self.auto_armed = True
        self.auto_timer.start()

    def maybe_start(self):
        if self.loading or self.w.loading_project or self.w.busy or self.w.close_when_idle or not self.auto_armed:
            return
        if QApplication.activeModalWidget() is not None:
            self.auto_timer.start()
            return
        app = self.application()
        if not app["auto_start"]:
            return
        if not self.w.video_dir.text().strip() or not self.w.keyframe_dir.text().strip():
            return
        if app["wait_for_mask"] and not self.w.mask_dir.text().strip():
            return
        try:
            from reezsynth_jobs import build_plan, validate_masks
            video, keys, _, _ = build_plan(self.w.video_dir.text(), self.w.keyframe_dir.text())
            masks = {}
            if app["wait_for_mask"] or self.render()["do_mask"]:
                masks = validate_masks(self.w.mask_dir.text(), video)
            # Include file identity to permit a new input set at the same location.
            signature = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in [*video.values(), *keys.values(), *masks.values()])
            signature += (self.w.mask_dir.text(), self.w.project_dir.text())
            if signature == self.last_auto:
                return
            if not self.w.rebuild_queue():
                return
            self.last_auto = signature
            self.auto_armed = False
            self.w.run_rows(list(self.w.rows))
        except (OSError, ValueError) as exc:
            self.w.status.setText(f"Automatic start waiting: {exc}")

    def application(self):
        return self.snapshot("application")

    def render(self):
        return validate_render(self.snapshot("render")["options"])

    def weights(self):
        return validate_weights(self.snapshot("weights"))

    def project_data(self):
        return dict(render_options=self.render(), guide_weights=self.weights(), mask_dir=self.w.mask_dir.text(), edge_dir=self.w.edge_dir.text(),
                    engine_revision=engine_revision(self.render()['engine']),
                    image_synthesis=self.w.image_synthesis.settings(),
                    exports=self.snapshot("render")["exports"],
                    blend_options=self.w.grouped.blend_options(), grouped_video=self.w.grouped.selection())

    def load_project(self, data):
        render = dict(RENDER, **quality_profile(data["quality"]))
        render.update(data.get("render_options", {}))
        self.apply("render", dict(options=render, quality=data["quality"],
                                 engine_revision=data.get('engine_revision'),
                                 exports=data.get("exports")))
        self.w.grouped.set_blend_options(data.get("blend_options"))
        self.apply("weights", data.get("guide_weights", {}))
        self.apply('image', data.get('image_synthesis', {}))
        self.w.mask_dir.setText(data.get("mask_dir", ""))
        self.w.edge_dir.setText(data.get("edge_dir", ""))
        self.auto_timer.stop()
        self.auto_armed = False

    def choose_sound(self):
        path, _ = QFileDialog.getOpenFileName(self.w, "Completion sound", "", "WAV sound (*.wav)")
        if path:
            self.widgets["application"]["sound_file"].setText(path)

    def notify(self, each=False):
        app = self.application()
        if not app["sound_enabled"] or not app["sound_each" if each else "sound_queue"]:
            return
        path = Path(app["sound_file"]) if app["sound_file"] else Path(__file__).with_name("assets") / "complete.wav"
        if not path.is_file():
            self.w.log.appendPlainText(f"Completion sound not found: {path}")
            return
        try:
            # Lazy import keeps multimedia out of startup and worker tests.
            from PySide6.QtMultimedia import QSoundEffect
            if self.sound is None:
                self.sound = QSoundEffect(self)
            self.sound.setSource(QUrl.fromLocalFile(str(path.resolve())))
            self.sound.setVolume(0.5)
            self.sound.play()
        except (ImportError, RuntimeError) as exc:
            self.w.log.appendPlainText(f"Completion sound unavailable: {exc}")

    def close(self):
        self.auto_timer.stop()
        self.discovery_timer.stop()
        self.persist()
