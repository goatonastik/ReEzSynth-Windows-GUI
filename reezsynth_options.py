"""Frontend options, presets and optional automation. No engine imports."""
import json
import os
import sys
from reezsynth_widget_style import ConstrainedQueueSpinBox, QueueDoubleSpinBox, QueueSpinBox, PyramidLevelsSpinBox
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QSettings, QSignalBlocker, QTimer, QUrl
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from reezsynth_config import (APPLICATION, GROUPS, LIMITS, SPIN_RULES, PREVIEW, RENDER, STANDARD, HIGHEST, quality_profile,
    WEIGHTS, PresetStore, atomic_json, discover_pairs, install_optional_flow_files,
    optional_flow_status, validate_application,
    validate_group, validate_render, validate_weights)
from reezsynth_project_controls import (project_naming, project_naming_state, set_project_naming,
    update_naming_preview)
from reezsynth_preview import LivePreviewWindow
from reezsynth_video_plan import validate_blend_options, validate_grouped_selection
from reezsynth_engines import LEGACY, FUOUM, default_runtime, engine_revision
from reezsynth_engine_setup import (readiness_command, rebuild_command,
                                    version_summary)
from reezsynth_iterations import SCHEDULE_FIELDS, parse_schedule
from reezsynth_modulation import VIDEO_MODES


PERSIST_GROUP_ORDER = tuple(group for group in GROUPS if group != 'render') + ('render',)
assert set(PERSIST_GROUP_ORDER) == set(GROUPS) and len(PERSIST_GROUP_ORDER) == len(GROUPS)

# Still-image synthesis supplies its own guide pairs and weights.  These video
# controls remain persisted so switching back to video restores the user's
# setup, but they do not participate in an image job.
VIDEO_ONLY_RENDER_FIELDS = (
    'edge_method', 'do_mask', 'pre_mask', 'feather', 'custom_edge_guides',
    'memory_efficient_raft', 'flow_arch', 'flow_model', 'temporal_nnf',
    'sparse_features', 'fuoum_sparse_anchor_weight', 'fuoum_flow_engine',
    'fuoum_neuflow_model', 'fuoum_raft_model', 'fuoum_bidirectional_flow',
    'stream_frames', 'modulation_guide', 'modulation_dir',
)


class IterationScheduleEdit(QLineEdit):
    """Keep JSON arrays separate from the user's editable comma-separated text."""
    def schedule(self):
        return parse_schedule(self.text())

    def set_schedule(self, value):
        self.setText(', '.join(str(item) for item in value))

LABELS = dict(edg_wgt="Edge guide", img_wgt="Video weight", pos_wgt="Mapping (position guide)",
    memory_efficient_raft="Memory-efficient RAFT correlation (CUDA) [Trentonom0r3 only]",
    key_wgt="Key weight", mask_wgt="Mask guide weight [Trentonom0r3 only]",
    wrp_wgt="Deflicker (warped-style guide)", uniformity="Diversity (uniformity)", patchsize="Patch size (odd)",
    pyramidlevels="Pyramid levels", searchvoteiters="Search/vote iterations",
    patchmatchiters="Patch-match iterations", extrapass3x3="Extra 3x3 polishing pass",
    edge_method="Edge method", do_mask="Use masks [Trentonom0r3 only]", pre_mask="Mask inputs before synthesis [Trentonom0r3 only]",
    custom_edge_guides="Use custom edge-guide frames [Trentonom0r3 only]",
    flow_arch="Alternative flow architecture [Trentonom0r3 only]", flow_model="Flow model (Trentonom0r3 only; video)", ebsynth_backend="EbSynth backend selection [Trentonom0r3 only]",
    feather="Mask feather size (zero or odd) [Trentonom0r3 only]", discover="Discover matching input subfolders",
    keys_prefix="Keyframe folder prefix", video_prefix="Video folder prefix",
    auto_start="Start automatically when inputs are ready", wait_for_mask="Wait for masks before automatic start",
    parallel="Enable parallel rendering", parallel_limit="Maximum simultaneous renders (0 = GPU-aware automatic)",
    sound_enabled="Enable completion sounds", sound_each="Play after each render",
    sound_queue="Play when the queue completes", sound_file="Custom WAV sound (blank = bundled sound)")
LABELS["preview_limit"] = "Maximum live previews"
LABELS.update(searchvote_schedule='Search/vote schedule (coarse to fine)',
              patchmatch_schedule='Patch-match schedule (coarse to fine)',
              modulation_guide='Video modulation', modulation_dir='Modulation frame directory')
LABELS.update(engine='Synthesis engine', temporal_nnf='Temporal NNF propagation [FuouM only]',
              fuoum_backend='Synthesis backend [FuouM only]',
              stream_frames='Store clip frames on disk to limit RAM',
              fuoum_flow_engine='Optical flow engine (FuouM only)',
              fuoum_bidirectional_flow='Estimate both flow directions [FuouM only]',
              fuoum_raft_model='RAFT checkpoint (FuouM only)',
              fuoum_neuflow_model='NeuFlow checkpoint (FuouM only)',
              sparse_features='Sparse feature guides [FuouM only]',
              fuoum_vote_mode='Voting mode [FuouM only]', fuoum_cost_function='Patch cost [FuouM only]',
              fuoum_stop_threshold='Early-stop threshold [FuouM only]',
              fuoum_search_pruning_threshold='Search-pruning threshold [FuouM only]',
              fuoum_sparse_anchor_weight='Sparse-guide weight [FuouM only]',
              fuoum_source='FuouM source folder (blank = project default) [FuouM only]',
              fuoum_python='FuouM Python executable (blank = project default) [FuouM only]')
for _shared in ('do_mask', 'pre_mask', 'feather', 'mask_wgt', 'custom_edge_guides'):
    LABELS[_shared] = LABELS[_shared].replace(' [Trentonom0r3 only]', '')


def control_value(widget):
    if isinstance(widget, IterationScheduleEdit):
        return widget.text()
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QComboBox):
        return widget.currentText()
    if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        return widget.value()
    return widget.text()


def set_control(widget, value):
    if isinstance(widget, IterationScheduleEdit):
        widget.set_schedule(value)
    elif isinstance(widget, QCheckBox):
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
        self.saved_groups = {}
        self.persistence_error_status = None
        self.preset_error_status = None
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
            self.errors.extend(self.store.errors)
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
        self.engine_note = QLabel('FuouM supports masks, custom edges, raw pass exports, grouped direction modes, '
                                 'and RAFT/NeuFlow video. CuPy blending and compiled memory-efficient RAFT '
                                 'are Trentonom0r3-only. Disabled settings are retained for that engine and excluded from FuouM jobs.')
        self.engine_note.setWordWrap(True)
        self.engine_note.hide()
        advanced_layout.addWidget(self.engine_note)
        self.export_widgets = {}
        for name, label in (("maps", "Export numerical error / selection maps (.npy)"),
                            ("flow", "Export flow visualizations (.png)"),
                            ("flow_vectors", "Export numerical flow vectors (.npy)")):
            widget = QCheckBox(label)
            widget.setToolTip("Applies to independent and grouped video. Saved under auxiliary/ with a metadata manifest.")
            if name == 'flow_vectors':
                widget.setToolTip('Saves floating-point dx/dy arrays under flow_vectors/. Metadata identifies source/target frames and processed pixel units. FuouM exports both directions when enabled.')
            widget.toggled.connect(self.changed)
            self.export_widgets[name] = widget
            advanced_layout.addWidget(widget)
            window.locked.append(widget)
        video_box = QGroupBox('Rendered video export')
        video_form = QFormLayout(video_box)
        self.video_export_enabled = QCheckBox('Assemble render.mp4 after saving frames')
        self.video_export_fps = QDoubleSpinBox()
        self.video_export_fps.setRange(.1, 240)
        self.video_export_fps.setDecimals(3)
        self.video_export_fps.setValue(24)
        self.video_export_fps.setSuffix(' FPS')
        self.video_export_audio = QLineEdit()
        self.video_export_audio.setPlaceholderText('Optional audio file')
        audio_row = QWidget()
        audio_layout = QHBoxLayout(audio_row)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.addWidget(self.video_export_audio, 1)
        audio_button = QPushButton('Select...')
        audio_button.clicked.connect(self.choose_video_audio)
        audio_layout.addWidget(audio_button)
        video_form.addRow(self.video_export_enabled)
        video_form.addRow('Frame rate', self.video_export_fps)
        video_form.addRow('Audio (optional)', audio_row)
        advanced_layout.addWidget(video_box)
        self.video_export_enabled.toggled.connect(self.refresh_video_export_controls)
        self.video_export_enabled.toggled.connect(self.changed)
        self.video_export_fps.valueChanged.connect(self.changed)
        self.video_export_audio.textChanged.connect(self.changed)
        window.locked.extend([self.video_export_enabled, self.video_export_fps,
                              self.video_export_audio, audio_button])
        self.video_export_audio_button = audio_button
        self.refresh_video_export_controls()
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
                elif name == 'modulation_dir':
                    row = QWidget()
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.addWidget(widget, 1)
                    self.modulation_browse = QPushButton('Select...')
                    self.modulation_browse.clicked.connect(self.choose_modulation_directory)
                    row_layout.addWidget(self.modulation_browse)
                    window.locked.append(self.modulation_browse)
                    fields.addRow(LABELS[name], row)
                    widget.setPlaceholderText('Numbered 8-bit grayscale maps matching source frames')
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
                elif name == 'fuoum_bidirectional_flow':
                    widget.setToolTip('Estimates both directions independently for image, coordinate and NNF warping. Roughly doubles flow computation on a cold cache. Off preserves existing flow behavior. Video only.')
                elif name == 'stream_frames':
                    widget.setToolTip('Video only. Stores decoded source/intermediate/result arrays in a temporary folder beside the output, with a 64 MiB / 8-array read cache. Uses extra disk space and I/O; does not reduce per-frame GPU allocation.')
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
        self.add_engine_setup_controls(settings_layout)
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
        # The active synthesis tab is the current mode.  Keep the shared
        # Rendering page truthful when Image Synthesis is selected without
        # changing the stored video-only values.
        window.tabs.currentChanged.connect(self.refresh_engine_controls)
        self.refresh_engine_controls()

    def make_control(self, name, default):
        if name in SCHEDULE_FIELDS:
            widget = IterationScheduleEdit()
            widget.set_schedule(default)
            widget.setPlaceholderText('Blank = scalar; e.g. 12, 8, 4')
            widget.setToolTip('1–32 comma-separated integers from 1 to 1000, coarse to fine. '
                              'Aligned to the finest level: smaller pyramids drop the first entries; '
                              'larger pyramids repeat the first count at additional coarse levels. '
                              'Blank uses the scalar at every level. Quality presets clear schedules.')
            widget.textChanged.connect(self.changed)
        elif isinstance(default, bool):
            widget = QCheckBox()
            widget.setChecked(default)
            widget.toggled.connect(self.changed)
        elif name == 'modulation_guide':
            widget = QComboBox()
            widget.addItems(VIDEO_MODES)
            widget.setToolTip('Video only: multiply the selected guide group by the target-frame grayscale map / 255. '
                              'White preserves weight; black removes local guide cost. All guides includes mask/sparse guides when present. '
                              'This changes matching, not output compositing. Image Synthesis has separate per-guide maps. '
                              'Legacy modulation requires explicit CUDA; its CPU backend ignores maps.')
            widget.currentTextChanged.connect(self.changed)
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
        elif name == 'fuoum_backend':
            widget = QComboBox()
            widget.addItems(['cuda', 'torch'])
            widget.setToolTip('cuda: existing native extension (default). torch: experimental repaired '
                              'PyTorch search, also on CUDA. Different matching and greater memory/time '
                              'requirements; not a CPU fallback. Presets retain this choice.')
            widget.currentTextChanged.connect(self.changed)
        elif name == 'fuoum_vote_mode':
            widget = QComboBox()
            widget.addItems(['weighted', 'plain'])
            widget.currentTextChanged.connect(self.changed)
        elif name in ('fuoum_flow_engine', 'fuoum_neuflow_model', 'fuoum_raft_model'):
            widget = QComboBox()
            widget.addItems({'fuoum_flow_engine': ['RAFT', 'NeuFlow'],
                            'fuoum_raft_model': ['sintel', 'kitti'],
                            'fuoum_neuflow_model': ['neuflow_sintel', 'neuflow_mixed', 'neuflow_things']}[name])
            widget.currentTextChanged.connect(self.changed)
        elif name == 'fuoum_cost_function':
            widget = QComboBox()
            widget.addItems(['ssd', 'ncc'])
            widget.currentTextChanged.connect(self.changed)
        elif isinstance(default, (int, float)):
            widget = (PyramidLevelsSpinBox() if name == 'pyramidlevels' else
                      ConstrainedQueueSpinBox(SPIN_RULES[name]) if name in SPIN_RULES else
                      QueueSpinBox() if isinstance(default, int) else QueueDoubleSpinBox())
            low, high = LIMITS.get(name, (0, 64 if name == "parallel_limit" else 10000))
            widget.setRange(low, high)
            if name == 'pyramidlevels':
                widget.setSpecialValueText('Automatic')
                widget.setToolTip('Automatic uses all pyramid levels supported by the input size and patch size.')
            elif name == 'patchsize':
                widget.setToolTip('Odd sizes from 3 to 99. Processed style and target dimensions must each be at least twice the patch size plus one pixel.')
            elif name == 'parallel_limit':
                widget.setSpecialValueText('Automatic')
                widget.setToolTip('Automatic admits workers using current NVIDIA GPU memory and conservative per-job estimates. Positive values are hard caps and remain GPU-memory-aware when telemetry is available.')
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
        ready = bool(status['models']) and (architecture != 'FLOW_DIFF' or
                (status.get('dependencies', status['timm']) and status.get('backbones', True)))
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
            elif not status.get('dependencies', True):
                missing.append('pinned FlowDiffuser dependency set')
            if not status.get('backbones', True):
                missing.append('offline Twin-SVT backbones')
            detail = 'Missing: ' + ' and '.join(missing) + '.'
        box = self.widgets['render']['flow_arch']
        box.blockSignals(True)
        box.setCurrentText('RAFT')
        box.blockSignals(False)
        self.refresh_flow_model_choices()
        QMessageBox.warning(self.w, 'Optional flow files are not installed',
            f'{detail}\n\nUse Settings > Optional flow components to install the required files, then select this architecture again.')

    def add_optional_flow_controls(self, layout):
        box = QGroupBox('Optional flow components [Trentonom0r3 only]')
        form = QFormLayout(box)
        self.ef_flow_status = QLabel()
        self.flow_diff_status = QLabel()
        self.ef_flow_status.setWordWrap(True)
        self.flow_diff_status.setWordWrap(True)
        ef_install = QPushButton('Install EF-RAFT checkpoint files...')
        flow_install = QPushButton('Install FlowDiffuser checkpoint...')
        timm_install = QPushButton('Install FlowDiffuser dependencies/backbones')
        ef_install.clicked.connect(lambda: self.install_optional_flow_checkpoints('EF_RAFT'))
        flow_install.clicked.connect(lambda: self.install_optional_flow_checkpoints('FLOW_DIFF'))
        timm_install.clicked.connect(self.install_flowdiffuser_timm)
        form.addRow('EF-RAFT', self.ef_flow_status)
        form.addRow('', ef_install)
        form.addRow('FlowDiffuser', self.flow_diff_status)
        form.addRow('', flow_install)
        form.addRow('', timm_install)
        layout.insertWidget(9, box)
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
                                      '\nDependency set: ' + ('ready' if flow.get('dependencies') else 'missing/incompatible') +
                                      '\nOffline backbones: ' + ('ready' if flow.get('backbones') else 'missing'))

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
        status = optional_flow_status()['FLOW_DIFF']
        if status.get('dependencies') and status.get('backbones'):
            QMessageBox.information(self.w, 'FlowDiffuser dependency', 'The pinned dependencies and offline backbones are already installed.')
            return
        if QMessageBox.question(self.w, 'Install FlowDiffuser dependency?',
                'Install the tested FlowDiffuser dependency set and two pinned Twin-SVT backbones?\n\n'
                'This downloads about 500 MB. A separate FlowDiffuser checkpoint is also required.',
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
        self.timm_process.start(sys.executable, ['-B', str(Path(__file__).parent / 'setup_flowdiffuser.py')])

    def finished_install_flowdiffuser_timm(self, code, _status):
        if not getattr(self, 'timm_install_pending', False):
            return
        self.timm_install_pending = False
        self.refresh_engine_controls()
        self.refresh_optional_flow_status()
        ready = optional_flow_status()['FLOW_DIFF']
        success = code == 0 and ready.get('dependencies') and ready.get('backbones')
        message = ('FlowDiffuser dependencies and backbones were installed successfully.'
                   if success
                   else 'FlowDiffuser installation failed. See Diagnostics for details.')
        (QMessageBox.information if success else QMessageBox.warning)(self.w, 'FlowDiffuser dependency', message)

    def flowdiffuser_timm_install_error(self, _error):
        if not getattr(self, 'timm_install_pending', False):
            return
        self.w.log.appendPlainText('Could not start the FlowDiffuser timm installer.')
        self.finished_install_flowdiffuser_timm(-1, None)

    def installation_active(self):
        return bool(getattr(self, 'timm_install_pending', False) or
                    getattr(self, 'engine_action_pending', False))

    def add_engine_setup_controls(self, layout):
        box = QGroupBox('Included engine setup and maintenance')
        form = QFormLayout(box)
        self.engine_setup_status = QLabel(version_summary(self.application()) +
            '\nReadiness: not checked in this session.')
        self.engine_setup_status.setWordWrap(True)
        check = QPushButton('Check included engines')
        legacy = QPushButton('Rebuild Legacy RAFT extension...')
        fuoum = QPushButton('Rebuild FuouM native extension...')
        check.clicked.connect(self.check_included_engines)
        legacy.clicked.connect(lambda: self.rebuild_engine_component('legacy'))
        fuoum.clicked.connect(lambda: self.rebuild_engine_component('fuoum'))
        form.addRow(self.engine_setup_status)
        form.addRow('', check)
        form.addRow('', legacy)
        form.addRow('', fuoum)
        note = QLabel('Both engines are included by standard setup. Checks are read-only. Rebuilds require the matching CUDA toolkit and Visual Studio 2022; pinned source revisions and existing environments are never replaced automatically.')
        note.setWordWrap(True)
        form.addRow(note)
        layout.insertWidget(8, box)
        self.engine_setup_buttons = (check, legacy, fuoum)
        self.w.locked.extend(self.engine_setup_buttons)

    def check_included_engines(self):
        program, arguments = readiness_command(self.application())
        self.start_engine_action('readiness check', program, arguments)

    def rebuild_engine_component(self, component):
        if self.installation_active() or self.w.busy:
            QMessageBox.information(self.w, 'Engine maintenance busy',
                                    'Wait for the current render or component operation to finish.')
            return
        label = 'Legacy RAFT extension' if component == 'legacy' else 'FuouM native extension'
        program, arguments = rebuild_command(component, self.application())
        if not Path(program).is_file():
            QMessageBox.warning(self.w, 'Cannot rebuild engine', f'Python executable not found: {program}')
            return
        if QMessageBox.question(self.w, f'Rebuild {label}?',
                f'Recompile and install the {label} for the currently configured runtime?\n\n'
                'This can take several minutes and requires the matching CUDA toolkit and Visual Studio 2022. '
                'It does not update or replace engine source revisions.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.start_engine_action(label + ' rebuild', program, arguments)

    def start_engine_action(self, label, program, arguments):
        if self.installation_active() or self.w.busy:
            QMessageBox.information(self.w, 'Engine maintenance busy',
                                    'Wait for the current render or component operation to finish.')
            return
        self.engine_action_pending = True
        self.engine_action_label = label
        self.engine_process = QProcess(self)
        self.engine_process.setWorkingDirectory(str(Path(__file__).parent))
        self.engine_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.engine_process.readyReadStandardOutput.connect(self.read_engine_action)
        self.engine_process.finished.connect(self.finished_engine_action)
        self.engine_process.errorOccurred.connect(self.engine_action_error)
        for button in (*self.engine_setup_buttons, *self.optional_flow_buttons):
            button.setEnabled(False)
        for control in (self.widgets['render']['engine'],
                        self.widgets['application']['fuoum_source'],
                        self.widgets['application']['fuoum_python']):
            control.setEnabled(False)
        self.engine_setup_status.setText(version_summary(self.application()) + f'\nRunning: {label}...')
        self.w.log.appendPlainText(f'\n[Engine maintenance] Starting {label}.')
        self.engine_process.start(str(program), [str(value) for value in arguments])

    def read_engine_action(self):
        if not getattr(self, 'engine_process', None):
            return
        text = bytes(self.engine_process.readAllStandardOutput()).decode('utf-8', 'replace').rstrip()
        if text:
            self.w.log.appendPlainText(text)

    def finished_engine_action(self, code, status):
        if not getattr(self, 'engine_action_pending', False):
            return
        self.read_engine_action()
        self.engine_action_pending = False
        process = self.engine_process
        self.engine_process = None
        normal = status == QProcess.ExitStatus.NormalExit
        success = code == 0 and normal
        label = self.engine_action_label
        self.engine_setup_status.setText(version_summary(self.application()) +
            f"\nLast operation: {label} {'passed' if success else 'failed'}; see Diagnostics.")
        self.w.log.appendPlainText(
            f"[Engine maintenance] {label} {'passed' if success else f'failed (exit {code})'}.")
        for button in (*self.engine_setup_buttons, *self.optional_flow_buttons):
            button.setEnabled(not self.w.busy)
        self.refresh_engine_controls()
        (QMessageBox.information if success else QMessageBox.warning)(
            self.w, 'Engine maintenance',
            f"{label.capitalize()} {'completed successfully.' if success else 'failed. See Diagnostics for details.'}")
        process.deleteLater()

    def engine_action_error(self, error):
        if not getattr(self, 'engine_action_pending', False):
            return
        self.w.log.appendPlainText('[Engine maintenance] Could not run component command: ' +
                                   self.engine_process.errorString())
        if error == QProcess.ProcessError.FailedToStart:
            self.finished_engine_action(-1, QProcess.ExitStatus.CrashExit)

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
        self.report_preset_errors()

    def report_preset_errors(self):
        if self.store and self.store.errors:
            self.preset_error_status = (f'{len(self.store.errors)} preset entry/collection(s) unavailable. '
                                       'Valid presets remain usable; see Diagnostics.')
            self.w.status.setText(self.preset_error_status)
        else:
            if self.preset_error_status == self.w.status.text():
                self.w.status.clear()
            self.preset_error_status = None

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
            return dict(options=dict(RENDER), quality='Standard', exports={}, video_export={})
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
            return w.image_synthesis.settings_state()
        if group == "directories":
            return {name: getattr(w, name).text() for name in ("project_dir", "keyframe_dir", "video_dir", "mask_dir", "edge_dir")}
        if group == 'output':
            return project_naming_state(w)
        if group == 'grouped':
            return dict(selection=w.grouped.selection_state(), blend_options=w.grouped.blend_options_state())
        if group == "render":
            result = dict(options={n: control_value(v) for n, v in self.widgets[group].items()},
                quality=w.quality.currentText(),
                exports={name: widget.isChecked() for name, widget in self.export_widgets.items()},
                video_export=dict(enabled=self.video_export_enabled.isChecked(),
                    fps=self.video_export_fps.value(), audio=self.video_export_audio.text()))
            result['engine_revision'] = engine_revision(result['options']['engine'])
            # Last-used setup retains resolution and Blend / Flow controls.
            # Output location and naming belong exclusively to the output group.
            if include_related:
                result.update(w.processing_state(),
                    blend_options=w.grouped.blend_options_state())
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
                video_export = data['video_export']
                self.video_export_enabled.setChecked(video_export['enabled'])
                self.video_export_fps.setValue(video_export['fps'])
                self.video_export_audio.setText(video_export['audio'])
                if restore_related:
                    self.w.set_processing_size(data["processing_size"], data['max_width'])
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
        try:
            self._restore()
        except Exception as exc:
            self.errors.append(f"Startup settings could not be restored: {exc}")
        finally:
            self.loading = False
            # Restoring folders does not arm unattended rendering on application startup.
            self.auto_armed = False
            for message in self.errors:
                self.w.log.appendPlainText(message)
            self.changed()

    def _restore(self):
        # Old QSettings values have already been restored by the GUI. They migrate
        # into the separate last-used file unless an explicit policy says otherwise.
        defaults = {group: self.default_group(group) for group in GROUPS}
        self.saved_groups = {group: validate_group(group, data) for group, data in defaults.items()}
        last, policy = {}, {}
        if self.app_path.exists():
            try:
                data = json.loads(self.app_path.read_text(encoding="utf-8"))
                if data.get("version") != 1 or not isinstance(data.get("startup"), dict):
                    raise ValueError("Invalid startup policy file.")
                policy = data["startup"]
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                self.errors.append(f"Startup policy file could not be restored: {exc}")
        if self.last_path.exists():
            try:
                data = json.loads(self.last_path.read_text(encoding="utf-8"))
                if data.get("version") != 1 or not isinstance(data.get("groups"), dict):
                    raise ValueError("Invalid last-used file.")
                last = data["groups"]
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                self.errors.append(f"Last-used settings could not be restored: {exc}")
        # Older last-used files stored output controls only inside render. Migrate
        # that raw payload once, before applying any groups. An explicit output
        # policy or an existing output group always takes precedence, even if the
        # canonical group is invalid and must fall back to its safe defaults.
        if 'output' not in last and policy.get('output', 'last') == 'last':
            legacy_render = last.get('render')
            if isinstance(legacy_render, dict) and 'output_naming' in legacy_render:
                last['output'] = legacy_render['output_naming']
        rejected = {}
        def unavailable(group, mode):
            # A broken preset must not replace a good last-used group with
            # defaults on the next debounced persistence cycle.
            if group in last:
                try:
                    candidate = validate_group(group, last[group])
                except (ValueError, TypeError, KeyError) as exc:
                    self.errors.append(f'Last-used fallback for {group} was rejected: {exc}')
                    rejected[group] = last[group]
                else:
                    self.errors.append(f'Startup preset unavailable for {group}: {mode}; using last-used settings for this group.')
                    return candidate
            self.errors.append(f'Startup preset unavailable for {group}: {mode}; using defaults for this group.')
            return defaults[group]

        for group in GROUPS:
            mode = policy.get(group, "last")
            box = self.policy_boxes[group]
            index = box.findData(mode)
            if index < 0:
                box.addItem("Missing " + str(mode), mode)
                box.setCurrentIndex(box.count() - 1)
                candidate = unavailable(group, mode)
            else:
                box.setCurrentIndex(index)
                if mode == "defaults":
                    candidate = defaults[group]
                elif mode.startswith("preset:"):
                    if self.store is None:
                        candidate = unavailable(group, mode)
                    else:
                        try:
                            candidate = self.store.groups[group][mode[7:]]
                        except (KeyError, TypeError) as exc:
                            candidate = unavailable(group, mode)
                else:
                    candidate = last.get(group, self.snapshot(group, include_related=(group == 'render')))
            try:
                validated = validate_group(group, candidate)
                self.apply(group, validated, restore_related=(group == 'render'))
            except (ValueError, TypeError, KeyError) as exc:
                if group in last and mode == 'last':
                    rejected[group] = last[group]
                self.errors.append(f"Could not restore {group}: {exc}; using defaults for this group.")
                validated = self.saved_groups[group]
                self.apply(group, validated, restore_related=(group == 'render'))
            self.saved_groups[group] = validated
        if rejected:
            try:
                atomic_json(self.directory / 'last-used.rejected.json', dict(version=1, groups=rejected))
            except OSError as exc:
                self.errors.append(f"Rejected settings could not be preserved: {exc}")
        if "render" not in last and policy.get("render", "last") == "last":
            for name, value in quality_profile(self.w.quality.currentText()).items():
                set_control(self.widgets["render"][name], value)

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
        image_mode = self.w.tabs.currentWidget() is getattr(self.w, 'image_synthesis', None)
        video_editable = editable and not image_mode
        engine_pending = getattr(self, 'engine_action_pending', False)
        widgets['engine'].setEnabled(editable and not engine_pending)
        for name in VIDEO_ONLY_RENDER_FIELDS:
            widgets[name].setEnabled(video_editable)
        if 'modulation_guide' in widgets:
            widgets['modulation_guide'].setEnabled(video_editable)
            enabled = video_editable and widgets['modulation_guide'].currentText() != 'Off'
            widgets['modulation_dir'].setEnabled(enabled)
            self.modulation_browse.setEnabled(enabled)
        for schedule, scalar in zip(SCHEDULE_FIELDS, ('searchvoteiters', 'patchmatchiters')):
            if schedule in widgets:
                widgets[schedule].setEnabled(editable)
                widgets[scalar].setEnabled(editable and not widgets[schedule].text().strip())
        for name in ('temporal_nnf', 'sparse_features'):
            widgets[name].setEnabled(video_editable and fuoum)
        # These configure the native synthesis call for both video and still
        # images. The remaining FuouM fields are flow/sparse-video controls.
        for name in ('fuoum_backend', 'fuoum_vote_mode', 'fuoum_cost_function',
                     'fuoum_stop_threshold', 'fuoum_search_pruning_threshold'):
            widgets[name].setEnabled(editable and fuoum)
        for name in ('fuoum_sparse_anchor_weight', 'fuoum_flow_engine', 'fuoum_neuflow_model',
                     'fuoum_raft_model', 'fuoum_bidirectional_flow'):
            widgets[name].setEnabled(video_editable and fuoum)
        widgets['fuoum_neuflow_model'].setEnabled(video_editable and fuoum and widgets['fuoum_flow_engine'].currentText() == 'NeuFlow')
        widgets['fuoum_raft_model'].setEnabled(video_editable and fuoum and widgets['fuoum_flow_engine'].currentText() == 'RAFT')
        widgets['flow_model'].setEnabled(video_editable and not fuoum and widgets['flow_model'].count() > 1)
        widgets['fuoum_sparse_anchor_weight'].setEnabled(video_editable and fuoum and widgets['sparse_features'].isChecked())
        memory_efficient = widgets['memory_efficient_raft']
        compatible_memory_efficient = widgets['flow_arch'].currentText() == 'RAFT'
        if memory_efficient.isChecked() and not compatible_memory_efficient:
            with QSignalBlocker(memory_efficient):
                memory_efficient.setChecked(False)
        memory_efficient.setEnabled(video_editable and not fuoum and compatible_memory_efficient)
        for name in ('flow_arch', 'ebsynth_backend'):
            widgets[name].setEnabled((video_editable if name == 'flow_arch' else editable) and not fuoum)
        for widget in self.widgets['weights'].values():
            widget.setEnabled(video_editable)
        for field in (self.w.mask_dir, self.w.edge_dir):
            field.parentWidget().setEnabled(video_editable)
        for widget in self.export_widgets.values():
            widget.setEnabled(video_editable)
        for name, path in default_runtime().items():
            if name in self.widgets.get('application', {}):
                self.widgets['application'][name].setPlaceholderText(path)
                self.widgets['application'][name].setEnabled(editable and fuoum and not engine_pending)
        for button in getattr(self, 'optional_flow_buttons', ()):
            button.setEnabled(editable and not fuoum and not self.installation_active())
        for button in getattr(self, 'engine_setup_buttons', ()):
            button.setEnabled(editable and not self.installation_active())
        if hasattr(self.w, 'grouped'):
            self.w.grouped.refresh_engine_controls(fuoum)

    def choose_modulation_directory(self):
        field = self.widgets['render']['modulation_dir']
        path = QFileDialog.getExistingDirectory(self.w, 'Modulation frame directory', field.text())
        if path:
            field.setText(path)

    def persist(self):
        if self.loading:
            return
        self.save_timer.stop()
        groups = dict(self.saved_groups)
        failures = []
        # Render's last-used payload retains related Blend / Flow controls for
        # compatibility. Output is captured only in its dedicated group.
        for group in PERSIST_GROUP_ORDER:
            try:
                state = self.snapshot(group, include_related=(group == 'render'))
                if group == 'render':
                    state['blend_options'] = groups['grouped']['blend_options']
                groups[group] = validate_group(group, state)
            except (ValueError, TypeError, KeyError) as exc:
                failures.append((group, str(exc)))
        for group, message in failures:
            label = 'Rendering' if group == 'render' else group.capitalize()
            detail = f'{label} settings were not saved: {message} Previous saved values were kept.'
            self.w.log.appendPlainText(detail)
            self.w.status.setText(detail)
            self.persistence_error_status = detail
        try:
            atomic_json(self.last_path, dict(version=1, groups=groups))
            atomic_json(self.app_path, dict(version=1,
                startup={g: b.currentData() for g, b in self.policy_boxes.items()}))
        except (OSError, ValueError) as exc:
            detail = f"Settings could not be saved: {exc} Previous saved values were kept."
            self.w.log.appendPlainText(detail)
            self.w.status.setText(detail)
            self.persistence_error_status = detail
            return
        self.saved_groups = groups
        if not failures:
            if self.persistence_error_status == self.w.status.text():
                self.w.status.clear()
            self.persistence_error_status = None

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
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self.w, "Cannot remove preset", str(exc))

    def import_presets(self):
        path, _ = QFileDialog.getOpenFileName(self.w, "Import presets", "", "Preset library (*.json *.yaml *.yml)")
        if not path:
            return
        try:
            imported = PresetStore(path)
            # JSON can stringify YAML keys, promoting rejected names or collapsing
            # distinct entries. Check the raw collections, including unknown groups.
            for group, presets in imported.document['groups'].items():
                if not isinstance(group, str) or (isinstance(presets, dict) and
                        any(not isinstance(name, str) for name in presets)):
                    raise ValueError("Preset group and preset names must be strings.")
            if QMessageBox.question(self.w, "Replace preset library?", "Replace the local preset library with this file?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            target = self.directory / "presets.json"
            atomic_json(target, imported.document)
            self.store = PresetStore(target)
            self.refresh_presets()
            for message in self.store.errors:
                self.w.log.appendPlainText(message)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self.w, "Cannot import presets", str(exc))

    def export_presets(self):
        if not self.store:
            return
        path, _ = QFileDialog.getSaveFileName(self.w, "Export presets", "reezsynth-presets.json", "Preset library (*.json *.yaml *.yml)")
        if path:
            try:
                self.store.write(self.store.groups, path)
            except (OSError, ValueError, TypeError) as exc:
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
        if self.installation_active():
            self.auto_timer.start()
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

    def render(self, effective=False):
        options = validate_group('render', self.snapshot('render'))['options']
        if effective and options['engine'] == FUOUM:
            options = dict(options, memory_efficient_raft=False, flow_arch='RAFT', ebsynth_backend='cuda')
            options['flow_model'] = options['fuoum_raft_model']
        return validate_render(options)

    def weights(self):
        return validate_weights(self.snapshot("weights"))

    def project_data(self):
        from reezsynth_video_export import validate_video_export
        return dict(render_options=self.render(), guide_weights=self.weights(), mask_dir=self.w.mask_dir.text(), edge_dir=self.w.edge_dir.text(),
            engine_revision=engine_revision(self.render()['engine']),
            image_synthesis=self.w.image_synthesis.settings(),
            exports=self.snapshot("render")["exports"],
            video_export=validate_video_export(self.snapshot('render')['video_export']),
            blend_options=self.w.grouped.blend_options(), grouped_video=self.w.grouped.selection())

    def load_project(self, data):
        render = dict(RENDER, **quality_profile(data["quality"]))
        render.update(data.get("render_options", {}))
        self.apply("render", dict(options=render, quality=data["quality"],
                                 engine_revision=data.get('engine_revision'),
                                 exports=data.get("exports"), video_export=data.get('video_export')))
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

    def choose_video_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self.w, 'Optional rendered-video audio', self.video_export_audio.text(),
            'Audio files (*.wav *.mp3 *.m4a *.aac *.flac *.ogg);;All files (*)')
        if path:
            self.video_export_audio.setText(path)

    def refresh_video_export_controls(self, *_):
        enabled = self.video_export_enabled.isChecked() and not self.w.busy
        self.video_export_fps.setEnabled(enabled)
        self.video_export_audio.setEnabled(enabled)
        self.video_export_audio_button.setEnabled(enabled)

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
