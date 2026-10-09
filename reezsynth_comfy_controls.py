"""First Keyframe Generator / ComfyUI tab: context, readiness, and safe intake."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from reezsynth_comfy_client import normalize_local_endpoint, parse_system_stats
from reezsynth_keyframe_candidates import import_candidate


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
        layout.addLayout(form)
        self._mode_changed()

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
        action_row.addStretch()
        layout.addLayout(action_row)
        self.candidate_status = QLabel("No candidate imported.")
        self.candidate_status.setTextFormat(Qt.TextFormat.PlainText)
        self.candidate_status.setWordWrap(True)
        layout.addWidget(self.candidate_status)
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

    def _mode_changed(self):
        modifying = self.mode.currentData() == "modify"
        self.form.setRowVisible(self.drawing_row, modifying)

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
        pixmap = QPixmap(str(record.image_path))
        if pixmap.isNull():
            self.preview.setText("Candidate saved; preview is unavailable.")
        else:
            self.preview.setPixmap(pixmap.scaled(
                500, 500, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
