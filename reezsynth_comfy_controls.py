"""First Keyframe Generator / ComfyUI tab: context, readiness, and safe intake."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from reezsynth_comfy_client import normalize_local_endpoint, parse_system_stats
from reezsynth_comfy_candidate import prepare_job_candidate, save_job_candidate
from reezsynth_comfy_jobs import load_job
from reezsynth_comfy_processing import (
    PreviewRequest, prepare_preview, preview_dark_strokes, save_enforced_candidate,
)
from reezsynth_keyframe_candidates import import_candidate
from reezsynth_keyframe_protection import AlphaPolicy, EditIntent


def _owned_project_job(directory, project):
    job = load_job(directory)
    try:
        selected = Path(project).expanduser().resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ValueError("Choose an existing project before loading its ComfyUI job.") from exc
    if job.directory.parent.parent.resolve(strict=True) != selected:
        raise ValueError("This ComfyUI job belongs to a different project.")
    return job


def _small_view(content):
    with Image.open(BytesIO(content)) as image:
        image.thumbnail((500, 500), Image.Resampling.LANCZOS)
        with BytesIO() as stream:
            image.save(stream, format="PNG")
            return stream.getvalue()


def _prepare_owned_for_project(directory, project):
    job = _owned_project_job(directory, project)
    result = prepare_job_candidate(job.directory)
    return result, {
        "Enforced native candidate": _small_view(result.image_png),
        "Raw model output (includes padding)": _small_view(result.raw_output_png),
    }


def _save_owned_for_project(directory, project, preview):
    job = _owned_project_job(directory, project)
    return save_job_candidate(job.directory, preview)


class _WorkSignals(QObject):
    finished = Signal(int, str, object, object)


class _ImageWork(QRunnable):
    def __init__(self, token, kind, function, *args):
        super().__init__()
        self.token, self.kind, self.function, self.args = token, kind, function, args
        self.signals = _WorkSignals()

    def run(self):
        try:
            value, error = self.function(*self.args), None
        except (OSError, ValueError, SyntaxError) as exc:
            value, error = None, str(exc)
        except Exception as exc:
            value, error = None, f"Preview processing failed: {type(exc).__name__}: {exc}"
        self.signals.finished.emit(self.token, self.kind, value, error)


class ComfyKeyframeTab(QWidget):
    """Keep ComfyUI optional and never start or modify an external server."""

    def __init__(self, main_window, preferences):
        super().__init__(main_window)
        self.main_window = main_window
        self.preferences = preferences
        self.network = QNetworkAccessManager(self)
        self.network.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self.reply: QNetworkReply | None = None
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._connection_timeout)
        self.image_pool = QThreadPool(self)
        self.image_pool.setMaxThreadCount(1)
        self._worker = None
        self._work_token = 0
        self._input_revision = 0
        self.current_result = None
        self.owned_result = None
        self._owned_revision = 0
        self._owned_preview_project = None
        self._preview_project = None
        self._display_images = {}

        layout = QVBoxLayout(self)
        introduction = QLabel(
            "Prepare a keyframe from a source frame or refine an existing drawing. "
            "This first stage checks a ComfyUI server and stores candidate images "
            "for review without changing synthesis keyframes."
        )
        introduction.setWordWrap(True)
        layout.addWidget(introduction)

        server_row = QHBoxLayout()
        self.address = QLineEdit(
            str(preferences.value("comfyui/address", "http://127.0.0.1:8188"))
        )
        self.address.setAccessibleName("Local ComfyUI address")
        self.check_button = QPushButton("Check connection")
        self.check_button.clicked.connect(self.check_connection)
        server_row.addWidget(QLabel("ComfyUI on this PC"))
        server_row.addWidget(self.address, 1)
        server_row.addWidget(self.check_button)
        layout.addLayout(server_row)
        self.connection_status = QLabel("Not connected. No backend starts automatically.")
        self.connection_status.setTextFormat(Qt.TextFormat.PlainText)
        self.connection_status.setWordWrap(True)
        layout.addWidget(self.connection_status)

        owned_row = QHBoxLayout()
        self.owned_job = QLineEdit()
        self.owned_job.setAccessibleName("Completed ReEzSynth ComfyUI job folder")
        self.owned_job.setPlaceholderText("Project/.reezsynth-candidates/comfy-job-...")
        self.owned_job.textChanged.connect(self._owned_inputs_changed)
        self._bound_project_field = None
        self.bind_project_field(getattr(main_window, "project_dir", None))
        browse_owned = QPushButton("Browse job...")
        browse_owned.clicked.connect(self._browse_owned_job)
        owned_row.addWidget(QLabel("Completed job"))
        owned_row.addWidget(self.owned_job, 1)
        owned_row.addWidget(browse_owned)
        layout.addLayout(owned_row)
        owned_actions = QHBoxLayout()
        self.owned_preview_button = QPushButton("Preview completed job")
        self.owned_preview_button.clicked.connect(self.preview_owned_job)
        self.owned_save_button = QPushButton("Save unreviewed result")
        self.owned_save_button.setEnabled(False)
        self.owned_save_button.clicked.connect(self.save_owned_job)
        owned_actions.addWidget(self.owned_preview_button)
        owned_actions.addWidget(self.owned_save_button)
        owned_actions.addStretch()
        layout.addLayout(owned_actions)
        self.owned_status = QLabel("Choose a completed job created by this project.")
        self.owned_status.setTextFormat(Qt.TextFormat.PlainText)
        self.owned_status.setWordWrap(True)
        layout.addWidget(self.owned_status)

        form = QFormLayout()
        self.form = form
        self.mode = QComboBox()
        self.mode.addItem("Generate new keyframe", "generate")
        self.mode.addItem("Modify existing keyframe", "modify")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        form.addRow("Mode", self.mode)
        self.frame_number = QSpinBox()
        self.frame_number.setRange(0, 2147483647)
        frame_row = QHBoxLayout()
        frame_row.addWidget(self.frame_number)
        from_project = QPushButton("Use project frame")
        from_project.clicked.connect(self.use_project_frame)
        frame_row.addWidget(from_project)
        frame_row.addStretch()
        form.addRow("Frame number", frame_row)

        self.source = QLineEdit()
        self.drawing = QLineEdit()
        self.generated = QLineEdit()
        self._path_row(form, "Original source frame", self.source)
        self.drawing_row = self._path_row(form, "Existing drawing", self.drawing)
        self._path_row(form, "Candidate PNG", self.generated, png_only=True)
        self.intent = QComboBox()
        self.intent.addItem("Stroke refinement", EditIntent.REFINE_STROKES.value)
        self.intent.addItem("Selected-region detail or shading", EditIntent.REGION_DETAIL.value)
        self.intent.addItem("Custom edit", EditIntent.CUSTOM.value)
        self.intent_row = form.rowCount()
        form.addRow("Edit intention", self.intent)
        self.edit_mask = QLineEdit()
        self.protection_mask = QLineEdit()
        self.edit_mask_row = self._path_row(form, "Editable area mask (8-bit grayscale PNG)",
                                            self.edit_mask, png_only=True)
        self.protection_mask_row = self._path_row(
            form, "Protect area mask (8-bit grayscale PNG)", self.protection_mask,
            png_only=True,
        )
        self.radius = QSpinBox()
        self.radius.setRange(0, 64)
        self.radius.setValue(0)
        self.radius_row = form.rowCount()
        form.addRow("Protect band (native pixels)", self.radius)
        self.alpha_policy = QComboBox()
        self.alpha_policy.addItem("Keep drawing transparency", AlphaPolicy.PRESERVE.value)
        self.alpha_policy.addItem("Allow transparency edits inside selected area",
                                  AlphaPolicy.EDIT.value)
        self.alpha_row = form.rowCount()
        form.addRow("Transparency", self.alpha_policy)
        layout.addLayout(form)
        intent_note = QLabel(
            "Edit intention is saved with the candidate for future generation. "
            "For these previews, your masks and transparency choice control the result; "
            "protect white or colored accents explicitly."
        )
        intent_note.setWordWrap(True)
        layout.addWidget(intent_note)
        self._mode_changed()
        for field in (self.source, self.drawing, self.generated,
                      self.edit_mask, self.protection_mask):
            field.textChanged.connect(self._inputs_changed)
        for choice in (self.mode, self.intent, self.alpha_policy):
            choice.currentIndexChanged.connect(self._inputs_changed)
        for spinner in (self.frame_number, self.radius):
            spinner.valueChanged.connect(self._inputs_changed)

        native_note = QLabel(
            "Candidates must match the source's original pixel dimensions. "
            "Preview display size never changes the stored image."
        )
        native_note.setWordWrap(True)
        layout.addWidget(native_note)

        action_row = QHBoxLayout()
        self.import_button = QPushButton("Import candidate for review")
        self.import_button.clicked.connect(self.import_for_review)
        action_row.addWidget(self.import_button)
        self.propose_button = QPushButton("Preview suggested dark strokes")
        self.propose_button.clicked.connect(self.preview_strokes)
        action_row.addWidget(self.propose_button)
        self.enforce_button = QPushButton("Preview protected result")
        self.enforce_button.clicked.connect(self.preview_enforced)
        action_row.addWidget(self.enforce_button)
        self.save_button = QPushButton("Save enforced candidate")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_enforced)
        action_row.addWidget(self.save_button)
        action_row.addStretch()
        layout.addLayout(action_row)
        self._mode_changed()
        self.candidate_status = QLabel("No candidate imported.")
        self.candidate_status.setTextFormat(Qt.TextFormat.PlainText)
        self.candidate_status.setWordWrap(True)
        layout.addWidget(self.candidate_status)
        view_row = QHBoxLayout()
        self.view = QComboBox()
        self.view.currentIndexChanged.connect(self._show_view)
        self.background = QComboBox()
        self.background.addItems(["Checkerboard", "Light", "Dark"])
        self.background.currentIndexChanged.connect(self._show_view)
        view_row.addWidget(QLabel("View"))
        view_row.addWidget(self.view, 1)
        view_row.addWidget(QLabel("Transparency background"))
        view_row.addWidget(self.background)
        layout.addLayout(view_row)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.preview.setText("Candidate preview")
        layout.addWidget(self.preview, 1)

    def _path_row(self, form, title, field, *, png_only=False):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(field, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: self._browse_image(field, png_only))
        row_layout.addWidget(browse)
        form.addRow(title, row)
        return row

    def _browse_image(self, field, png_only):
        selected, _ = QFileDialog.getOpenFileName(
            self, "Select image", field.text(),
            "PNG images (*.png)" if png_only else "Images (*.png *.jpg *.jpeg)",
        )
        if selected:
            field.setText(selected)

    def _browse_owned_job(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select completed job folder",
                                                  self.owned_job.text())
        if chosen:
            self.owned_job.setText(chosen)

    def bind_project_field(self, field):
        """Connect after MainWindow creates its project field."""
        if (not isinstance(field, (QLineEdit, QComboBox))
                or not hasattr(field, "textChanged")
                or field is self._bound_project_field):
            return
        if self._bound_project_field is not None:
            self._bound_project_field.textChanged.disconnect(self._owned_inputs_changed)
        field.textChanged.connect(self._owned_inputs_changed)
        self._bound_project_field = field

    def _owned_inputs_changed(self, *_):
        was_displayed = self.owned_result is not None
        self._owned_revision += 1
        self.owned_result = None
        self._owned_preview_project = None
        self.owned_save_button.setEnabled(False)
        if was_displayed:
            self._display_images = {}
            self.view.clear()
            self.preview.clear()
            self.preview.setText("Preview needs rebuilding for this job.")
        self.owned_status.setText("Job changed. Preview it again before saving.")

    def preview_owned_job(self):
        if self._worker is not None:
            return
        try:
            project = self.main_window.path_value(self.main_window.project_dir)
        except ValueError as exc:
            self.owned_status.setText(str(exc))
            return
        directory = self.owned_job.text().strip()
        if not directory:
            self.owned_status.setText("Choose a completed job folder first.")
            return
        self.owned_result = None
        self._owned_preview_project = project
        self._start_work("owned_preview", _prepare_owned_for_project, directory, project)

    def save_owned_job(self):
        if self.owned_result is None or self._worker is not None:
            return
        try:
            project = self.main_window.path_value(self.main_window.project_dir)
        except ValueError as exc:
            self.owned_status.setText(str(exc))
            return
        if project != self._owned_preview_project:
            self.owned_status.setText("Project changed since preview; preview the job again.")
            self.owned_save_button.setEnabled(False)
            return
        self._start_work("owned_save", _save_owned_for_project,
                         self.owned_job.text().strip(), project, self.owned_result)

    def _mode_changed(self):
        modifying = self.mode.currentData() == "modify"
        self.form.setRowVisible(self.drawing_row, modifying)
        for row in (self.intent_row, self.edit_mask_row, self.protection_mask_row,
                    self.radius_row, self.alpha_row):
            self.form.setRowVisible(row, modifying)
        if hasattr(self, "propose_button"):
            for button in (self.propose_button, self.enforce_button, self.save_button):
                button.setVisible(modifying)

    def _inputs_changed(self, *_):
        self._input_revision += 1
        self.current_result = None
        self.owned_result = None
        self._preview_project = None
        self.save_button.setEnabled(False)
        self.owned_save_button.setEnabled(False)
        self.owned_status.setText("Inputs changed. Preview the completed job again if needed.")
        self._display_images = {}
        self.view.clear()
        self.preview.clear()
        self.preview.setText("Preview needs rebuilding for these inputs.")
        self.candidate_status.setText("Inputs changed. Build a new preview before saving.")

    def _start_work(self, kind, function, *args):
        if self._worker is not None:
            return
        if kind in {"preview", "proposal", "owned_preview"}:
            if kind == "owned_preview":
                self.current_result = None
            else:
                self.owned_result = None
            self._display_images = {}
            self.view.clear()
            self.preview.clear()
            self.preview.setText("Preparing preview...")
        self._work_token += 1
        self._work_revision = self._input_revision
        self._work_owned_revision = self._owned_revision
        worker = _ImageWork(self._work_token, kind, function, *args)
        worker.signals.finished.connect(self._work_finished)
        self._worker = worker
        self.enforce_button.setEnabled(False)
        self.propose_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.owned_preview_button.setEnabled(False)
        self.owned_save_button.setEnabled(False)
        if kind.startswith("owned_"):
            self.owned_status.setText("Checking the local ComfyUI server and reading its completed job..." if kind == "owned_preview"
                                      else "Saving unreviewed result...")
        else:
            self.candidate_status.setText(f"{kind.capitalize()} in progress...")
        self.image_pool.start(worker)

    def preview_strokes(self):
        if not self.drawing.text().strip():
            self.candidate_status.setText("Choose an existing drawing first.")
            return
        self.current_result = None
        self._start_work("proposal", preview_dark_strokes, self.drawing.text().strip())

    def preview_enforced(self):
        if self.mode.currentData() != "modify":
            self.candidate_status.setText("Protected preview applies to Modify Existing Keyframe.")
            return
        project = None
        if self.main_window.project_dir.text().strip():
            try:
                project = self.main_window.path_value(self.main_window.project_dir)
            except ValueError as exc:
                self.candidate_status.setText(str(exc))
                return
        request = PreviewRequest(
            self.frame_number.value(), self.source.text().strip(), self.drawing.text().strip(),
            self.generated.text().strip(), self.edit_mask.text().strip(),
            self.protection_mask.text().strip(), self.intent.currentData(),
            self.alpha_policy.currentData(), self.radius.value(),
        )
        self.current_result = None
        self._preview_project = project
        self._start_work("preview", prepare_preview, request)

    def save_enforced(self):
        if self.current_result is None or self._worker is not None:
            return
        try:
            project = self.main_window.path_value(self.main_window.project_dir)
        except ValueError as exc:
            self.candidate_status.setText(str(exc))
            return
        if self._preview_project is not None and project != self._preview_project:
            self.candidate_status.setText("Project changed since preview; rebuild it before saving.")
            return
        self._start_work("save", save_enforced_candidate, project, self.current_result)

    def _work_finished(self, token, kind, value, error):
        if token != self._work_token:
            return
        self._worker = None
        self.enforce_button.setEnabled(True)
        self.propose_button.setEnabled(True)
        self.import_button.setEnabled(True)
        self.owned_preview_button.setEnabled(True)
        self.save_button.setEnabled(self.current_result is not None)
        self.owned_save_button.setEnabled(self.owned_result is not None)
        if error:
            (self.owned_status if kind.startswith("owned_")
             else self.candidate_status).setText(error)
            self.save_button.setEnabled(self.current_result is not None)
            self.owned_save_button.setEnabled(self.owned_result is not None)
            return
        if kind == "owned_preview" and self._work_owned_revision != self._owned_revision:
            self.owned_status.setText("Job changed during preview; preview it again.")
            return
        if kind not in {"save", "owned_save", "owned_preview"} and self._work_revision != self._input_revision:
            self.candidate_status.setText("Inputs changed during processing; rebuild preview.")
            return
        if kind == "proposal":
            self._display_images = {"Suggested dark strokes (preview only)": value}
            self._set_views()
            self.candidate_status.setText(
                "Suggested dark strokes are only a preview. White and colored accents "
                "may need protection too. Supply and inspect both masks explicitly."
            )
        elif kind == "preview":
            self.owned_result = None
            self.owned_save_button.setEnabled(False)
            self.current_result = value
            self._display_images = value.views
            self._set_views("Enforced preview")
            self.save_button.setEnabled(True)
            self.candidate_status.setText(
                f"Frame {value.request.frame_number}, {value.width} x {value.height} native pixels: "
                f"{value.report.protected_pixels} protected, "
                f"{value.report.protected_mismatches} protected mismatches. "
                "Inspect the masks and image before saving; geometry outside protection "
                "has not been verified."
            )
        elif kind == "save":
            self.save_button.setEnabled(False)
            self.candidate_status.setText(
                f"Unreviewed enforced candidate saved: {value.image_path}. "
                "Numbered synthesis keyframes were not changed."
            )
        elif kind == "owned_preview":
            self.current_result = None
            self.save_button.setEnabled(False)
            self.owned_result, self._display_images = value
            self._set_views("Enforced native candidate")
            self.owned_save_button.setEnabled(True)
            self.owned_status.setText(
                "Native completed-job result ready for review. The saved result "
                "will remain unreviewed and unassigned to a frame."
            )
        elif kind == "owned_save":
            self.owned_result = None
            self.owned_save_button.setEnabled(False)
            self.owned_status.setText(
                f"Unreviewed result saved: {value.image_path}. "
                "Choose and approve its target frame separately."
            )

    def _set_views(self, selected=None):
        self.view.blockSignals(True)
        self.view.clear()
        self.view.addItems(list(self._display_images))
        if selected:
            self.view.setCurrentText(selected)
        self.view.blockSignals(False)
        self._show_view()

    def _show_view(self, *_):
        payload = self._display_images.get(self.view.currentText())
        if not payload:
            return
        image = QImage.fromData(payload)
        if image.isNull():
            self.preview.setText("Preview unavailable.")
            return
        factor = min(500 / image.width(), 500 / image.height())
        width = max(1, round(image.width() * factor))
        height = max(1, round(image.height() * factor))
        scaled = QPixmap.fromImage(image).scaled(
            width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        display = QPixmap(scaled.size())
        painter = QPainter(display)
        if self.background.currentText() == "Checkerboard":
            for y in range(0, display.height(), 16):
                for x in range(0, display.width(), 16):
                    shade = "#e8e8e8" if ((x // 16 + y // 16) % 2) else "#bdbdbd"
                    painter.fillRect(x, y, min(16, display.width()-x),
                                     min(16, display.height()-y), QColor(shade))
        else:
            painter.fillRect(display.rect(), QColor("#ffffff" if self.background.currentText() == "Light"
                                                    else "#1e1e1e"))
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        self.preview.setPixmap(display)

    def use_project_frame(self):
        number = self.frame_number.value()
        source = self.main_window.video.get(number)
        if source is None:
            QMessageBox.information(
                self, "Frame not available",
                f"Frame {number} is not in the scanned source sequence."
            )
            return
        self.source.setText(str(source))
        drawing = self.main_window.keys.get(number)
        self.drawing.setText(str(drawing) if drawing is not None else "")

    def check_connection(self):
        try:
            endpoint = normalize_local_endpoint(self.address.text())
        except ValueError as exc:
            self.connection_status.setText(str(exc))
            return
        self.preferences.setValue("comfyui/address", endpoint)
        self.cancel_pending_check()
        request = QNetworkRequest(QUrl(endpoint + "/system_stats"))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        self.reply = self.network.get(request)
        reply = self.reply
        reply.finished.connect(lambda: self._connection_finished(reply))
        self.timeout.start(5000)
        self.check_button.setEnabled(False)
        self.connection_status.setText("Checking local ComfyUI...")

    def _connection_timeout(self):
        if self.reply is not None:
            self.cancel_pending_check()
            self.connection_status.setText("Connection check timed out after five seconds.")

    def _connection_finished(self, reply):
        if reply is not self.reply:
            return
        self.timeout.stop()
        self.reply = None
        self.check_button.setEnabled(True)
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if reply.error() != QNetworkReply.NetworkError.NoError or status != 200:
                raise ValueError(
                    "Could not reach a local ComfyUI server. Check its address and "
                    "that it is running."
                )
            info = parse_system_stats(bytes(reply.readAll()))
            devices = ", ".join(info.devices) if info.devices else "device not reported"
            self.connection_status.setText(
                f"Connected to local ComfyUI {info.version} ({devices}). "
                "No generation job has been started."
            )
        except ValueError as exc:
            self.connection_status.setText(str(exc))
        finally:
            reply.deleteLater()

    def cancel_pending_check(self):
        self.timeout.stop()
        if self.reply is not None:
            reply = self.reply
            self.reply = None
            reply.abort()
            reply.deleteLater()
        self.check_button.setEnabled(True)

    def import_for_review(self):
        if self._worker is not None:
            return
        self.current_result = None
        self.owned_result = None
        self._preview_project = None
        self.save_button.setEnabled(False)
        self.owned_save_button.setEnabled(False)
        self._display_images = {}
        self.view.clear()
        self.preview.clear()
        self.preview.setText("Candidate preview")
        self.candidate_status.setText("Importing candidate...")
        try:
            project = self.main_window.path_value(self.main_window.project_dir)
            record = import_candidate(
                project, self.frame_number.value(), self.source.text().strip(),
                self.generated.text().strip(), mode=self.mode.currentData(),
                drawing_image=(self.drawing.text().strip()
                               if self.mode.currentData() == "modify" else None),
            )
        except (OSError, ValueError) as exc:
            self.candidate_status.setText(f"Candidate was not imported: {exc}")
            QMessageBox.warning(self, "Cannot import candidate", str(exc))
            return
        self.candidate_status.setText(
            f"Unreviewed candidate for frame {self.frame_number.value()}: "
            f"{record.image_path}\n{record.width} x {record.height} native pixels. "
            "Synthesis keyframes were not changed."
        )
        self._display_images = {"Raw candidate": record.image_path.read_bytes()}
        self._set_views()
