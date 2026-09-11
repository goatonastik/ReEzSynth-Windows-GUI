"""Frontend options, presets and optional automation. No engine imports."""
import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QTimer, QUrl
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from reezsynth_config import (APPLICATION, GROUPS, LIMITS, PREVIEW, RENDER, STANDARD,
    WEIGHTS, PresetStore, atomic_json, discover_pairs, validate_application,
    validate_group, validate_render, validate_weights)
from reezsynth_project_controls import (project_naming, set_project_naming,
    update_naming_preview)

LABELS = dict(edg_wgt="Edge guide", img_wgt="Video weight", pos_wgt="Mapping (position guide)",
    key_wgt="Key weight", mask_wgt="Mask guide weight",
    wrp_wgt="Deflicker (warped-style guide)", uniformity="Diversity (uniformity)", patchsize="Patch size (odd)",
    pyramidlevels="Pyramid levels", searchvoteiters="Search/vote iterations",
    patchmatchiters="Patch-match iterations", extrapass3x3="Extra 3x3 polishing pass",
    edge_method="Edge method", do_mask="Use masks", pre_mask="Mask inputs before synthesis",
    feather="Mask feather size (zero or odd)", discover="Discover matching input subfolders",
    keys_prefix="Keyframe folder prefix", video_prefix="Video folder prefix",
    auto_start="Start automatically when inputs are ready", wait_for_mask="Wait for masks before automatic start",
    parallel="Enable parallel rendering", parallel_limit="Maximum simultaneous renders (0 = unlimited)",
    sound_enabled="Enable completion sounds", sound_each="Play after each render",
    sound_queue="Play when the queue completes", sound_file="Custom WAV sound (blank = bundled sound)")


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
        window.directory_layout.insertLayout(0, self.preset_bar("directories", "Directory presets"))
        advanced = QGroupBox("Rendering controls")
        advanced_layout = QVBoxLayout(advanced)
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
        for group, defaults, title in (("weights", WEIGHTS, "Guide weights"), ("render", RENDER, "Synthesis")):
            box = QGroupBox(title)
            layout = QVBoxLayout(box)
            layout.addLayout(self.preset_bar(group, title + " presets"))
            fields = QFormLayout()
            self.widgets[group] = {}
            for name, default in defaults.items():
                widget = self.make_control(name, default)
                self.widgets[group][name] = widget
                if name == 'do_mask':
                    widget.setText('Enable masks')
                    widget.setToolTip('Uncheck to ignore masks for synthesis and compositing; the folder stays remembered.')
                    form.addRow(widget)
                elif name in ('key_wgt', 'img_wgt', 'mask_wgt'):
                    form.addRow(LABELS[name], widget)
                else:
                    fields.addRow(LABELS[name], widget)
                if name == 'key_wgt':
                    widget.setMinimum(0.001)
                    widget.setToolTip('Style-to-guide ratio: guide weights are divided by this value. Default 1 preserves Ezsynth behavior.')
                elif name == 'mask_wgt':
                    widget.setToolTip('Additional mask correspondence guide when masks are enabled. Zero disables this guide; mask compositing remains controlled by Enable masks.')
                elif name in ('pos_wgt', 'wrp_wgt', 'uniformity'):
                    widget.setToolTip('Ezsynth control with a related purpose to the EbSynth Beta setting; numerical equivalence is not guaranteed.')
            layout.addLayout(fields)
            columns.addWidget(box)
        advanced_layout.addLayout(columns)
        advanced_layout.addWidget(QLabel("Preview / Standard reset synthesis parameters; guide weights are independent.\n"
            "RAFT Sintel and the CUDA synthesis backend remain selected. Use Blend / Flow for grouped video."))
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
        # A button reaches the existing Settings page without creating a second settings UI.
        settings_button = QPushButton("Settings")
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_index = window.tabs.indexOf(settings_page)
        window.tabs.removeTab(settings_index)
        settings_scroll.setWidget(settings_page)
        window.tabs.insertTab(settings_index, settings_scroll, "Settings")
        settings_button.clicked.connect(lambda: window.tabs.setCurrentWidget(settings_scroll))
        page.itemAt(0).layout().addWidget(settings_button)
        window.locked.append(settings_button)
        for field in (window.project_dir, window.keyframe_dir, window.video_dir, window.mask_dir):
            field.textChanged.connect(self.changed)
        window.project_dir.textChanged.connect(self.discovery_changed)
        for field in (window.keyframe_dir, window.video_dir, window.mask_dir):
            field.textChanged.connect(self.inputs_changed)
        window.quality.currentTextChanged.connect(self.quality_changed)
        window.resolution.currentIndexChanged.connect(self.changed)
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
        elif name == "edge_method":
            widget = QComboBox()
            widget.addItems(["Classic", "PST", "PAGE"])
            widget.currentTextChanged.connect(self.changed)
        elif isinstance(default, (int, float)):
            widget = QSpinBox() if isinstance(default, int) else QDoubleSpinBox()
            low, high = LIMITS.get(name, (0, 64 if name == "parallel_limit" else 10000))
            widget.setRange(low, high)
            if isinstance(widget, QDoubleSpinBox):
                widget.setDecimals(3)
                widget.setSingleStep(0.1)
            widget.setValue(default)
            widget.valueChanged.connect(self.changed)
        else:
            widget = QLineEdit(default)
            widget.textChanged.connect(self.changed)
        self.w.locked.append(widget)
        return widget

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
            box.addItem("Select preset...", None)
            for name in names:
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

    def snapshot(self, group):
        w = self.w
        if group == "directories":
            return {name: getattr(w, name).text() for name in ("project_dir", "keyframe_dir", "video_dir", "mask_dir")}
        if group == "render":
            return dict(options={n: control_value(v) for n, v in self.widgets[group].items()},
                quality=w.quality.currentText(), max_width=w.resolution.currentData(),
                output_naming=project_naming(w),
                blend_options=w.grouped.blend_options(),
                exports={name: widget.isChecked() for name, widget in self.export_widgets.items()})
        return {name: control_value(widget) for name, widget in self.widgets[group].items()}

    def apply(self, group, data):
        data = validate_group(group, data)
        previous = self.loading
        self.loading = True
        try:
            if group == "directories":
                for name, value in data.items():
                    getattr(self.w, name).setText(value)
            elif group == "render":
                self.w.quality.setCurrentText(data["quality"])
                self.w.resolution.setCurrentIndex(self.w.resolution.findData(data["max_width"]))
                set_project_naming(self.w, data["output_naming"])
                for name, value in data["options"].items():
                    set_control(self.widgets[group][name], value)
                self.w.grouped.set_blend_options(data["blend_options"])
                for name, value in data["exports"].items():
                    self.export_widgets[name].setChecked(value)
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
        defaults = {"directories": dict(project_dir=str(self.w.project_dir.text()),
                       keyframe_dir="", video_dir="", mask_dir=""),
                    "weights": WEIGHTS, "render": dict(options=RENDER, quality="Preview", max_width=512),
                    "application": APPLICATION}
        # The project default should never inherit a previous directory in defaults mode.
        defaults["directories"]["project_dir"] = self.default_project
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
                        self.apply(group, last[group])
                except (ValueError, TypeError, KeyError) as exc:
                    self.errors.append(f"Could not restore {group}: {exc}; using defaults for this group.")
                    self.apply(group, defaults[group])
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.errors.append(f"Startup settings could not be restored: {exc}")
        if "render" not in last and policy.get("render", "last") == "last":
            for name, value in (STANDARD if self.w.quality.currentText() == "Standard" else PREVIEW).items():
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

    def persist(self):
        if self.loading:
            return
        self.save_timer.stop()
        try:
            groups = {group: self.snapshot(group) for group in GROUPS}
            atomic_json(self.last_path, dict(version=1, groups=groups))
            atomic_json(self.app_path, dict(version=1,
                startup={g: b.currentData() for g, b in self.policy_boxes.items()}))
        except (OSError, ValueError) as exc:
            self.w.log.appendPlainText(f"Settings could not be saved: {exc}")

    def quality_changed(self, quality):
        if not self.loading:
            for name, value in (STANDARD if quality == "Standard" else PREVIEW).items():
                set_control(self.widgets["render"][name], value)
            self.changed()

    def select_preset(self, group):
        name = self.preset_boxes[group].currentData()
        if name and self.store:
            self.apply(group, self.store.groups[group][name])

    def save_preset(self, group):
        if self.store is None:
            QMessageBox.warning(self.w, "Presets unavailable", "Import a valid preset file first; the original file was preserved.")
            return
        name, ok = QInputDialog.getText(self.w, "Save preset", "Preset name:",
            text=self.preset_boxes[group].currentData() or "")
        if not ok:
            return
        try:
            name = name.strip()
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
        path, _ = QFileDialog.getOpenFileName(self.w, "Import presets", "", "JSON (*.json)")
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
        path, _ = QFileDialog.getSaveFileName(self.w, "Export presets", "reezsynth-presets.json", "JSON (*.json)")
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
        return dict(render_options=self.render(), guide_weights=self.weights(), mask_dir=self.w.mask_dir.text(),
                    exports=self.snapshot("render")["exports"],
                    blend_options=self.w.grouped.blend_options(), grouped_video=self.w.grouped.selection())

    def load_project(self, data):
        render = dict(RENDER, **(STANDARD if data["quality"] == "Standard" else PREVIEW))
        render.update(data.get("render_options", {}))
        self.apply("render", dict(options=render, quality=data["quality"], max_width=data["max_width"],
                                 output_naming=data.get("output_naming"), blend_options=data.get("blend_options"),
                                 exports=data.get("exports")))
        self.apply("weights", data.get("guide_weights", {}))
        self.w.mask_dir.setText(data.get("mask_dir", ""))
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
