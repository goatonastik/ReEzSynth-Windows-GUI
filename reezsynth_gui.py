import json
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent


# ---------- Render worker: runs in a separate Python process ----------

def render_job(job_path):
    import cv2
    import numpy as np
    import torch

    from ezsynth.aux_classes import RunConfig
    from ezsynth.main_ez import EzsynthBase

    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    output = Path(job["output"])

    def natural_key(path):
        return [
            (0, int(part)) if part.isdigit() else (1, part.lower())
            for part in re.split(r"(\d+)", path.name)
        ]

    paths = sorted(
        [
            path for path in Path(job["input"]).iterdir()
            if path.is_file()
            and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
        ],
        key=natural_key,
    )

    if len(paths) < 2:
        raise ValueError("Select a folder containing at least two image frames.")

    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch CUDA is unavailable in this environment.")

    print("GPU:", torch.cuda.get_device_name(0), flush=True)
    print("Input frames:", len(paths), flush=True)
    print("First frame:", paths[0].name, flush=True)
    print("Last frame:", paths[-1].name, flush=True)
    print("Style is assigned to the FIRST frame.", flush=True)

    # Preserve the exact frame order for troubleshooting.
    (output / "input_manifest.json").write_text(
        json.dumps([str(path) for path in paths], indent=2),
        encoding="utf-8",
    )

    frames = []
    original_shape = None
    target_size = None

    for index, path in enumerate(paths):
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Could not decode image: {path}")

        if original_shape is None:
            original_shape = image.shape
            height, width = image.shape[:2]
            limit = job["max_width"]
            scale = min(1.0, limit / width) if limit else 1.0
            target_size = (
                max(1, round(width * scale)),
                max(1, round(height * scale)),
            )

        if image.shape != original_shape:
            raise ValueError(f"Input frame dimensions differ: {path.name}")

        if image.shape[1::-1] != target_size:
            image = cv2.resize(
                image, target_size, interpolation=cv2.INTER_AREA
            )

        frames.append(image)

        if index % 50 == 0:
            print(f"Loaded {index + 1}/{len(paths)} frames", flush=True)

    if min(target_size) < 128:
        raise ValueError(
            "For this prototype, processing width and height must both "
            "be at least 128 pixels."
        )

    style = cv2.imread(job["style"])
    if style is None:
        raise ValueError("Could not decode the style image.")

    if style.shape != original_shape:
        raise ValueError(
            "The style image must match the original input frame dimensions."
        )

    if style.shape[1::-1] != target_size:
        style = cv2.resize(
            style, target_size, interpolation=cv2.INTER_AREA
        )

    presets = {
        "Preview": (5, 3, 4, 3, False),
        "Standard": (7, 6, 12, 6, True),
    }
    patch, levels, votes, matches, polish = presets[job["quality"]]

    config = RunConfig(
        patchsize=patch,
        pyramidlevels=levels,
        searchvoteiters=votes,
        patchmatchiters=matches,
        extrapass3x3=polish,
        use_gpu=False,
        use_poisson_cupy=False,
    )

    print("Processing resolution:", target_size, flush=True)
    print("Quality:", job["quality"], flush=True)
    print("Initializing engine...", flush=True)

    runner = EzsynthBase(
        style_frs=[style],
        style_idxes=[0],
        img_frs_seq=frames,
        cfg=config,
        edge_method="Classic",
        raft_flow_model_name="sintel",
        flow_arch="RAFT",
        do_mask=False,
    )

    # Requires the backend-forwarding edits made during diagnostics.
    runner.eb.backend = runner.eb.backends["cuda"]

    print("Requested EbSynth backend: CUDA", flush=True)
    print("Starting forward synthesis...", flush=True)

    results, errors = runner.run_sequences()

    if len(results) != len(frames):
        raise RuntimeError(
            f"Output count mismatch: {len(results)} vs {len(frames)}"
        )

    print("Saving output frames...", flush=True)

    for index, image in enumerate(results):
        if image.shape != frames[index].shape:
            raise RuntimeError(f"Unexpected dimensions at output {index}.")
        if not np.isfinite(image).all():
            raise RuntimeError(f"Invalid pixel values at output {index}.")

        image = np.clip(image, 0, 255).astype(np.uint8)
        path = output / f"output_{index:06d}.png"

        if not cv2.imwrite(str(path), image):
            raise OSError(f"Could not save {path}")

    (output / "COMPLETE.txt").write_text(
        f"Successfully saved {len(results)} frames.\n",
        encoding="utf-8",
    )

    print(f"COMPLETE: {len(results)} frames saved to {output}", flush=True)


# ---------- GUI: no engine imports required to open the window ----------

def launch_gui():
    from PySide6.QtCore import QProcess, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QApplication, QComboBox, QFileDialog, QFormLayout,
        QHBoxLayout, QLabel, QLineEdit, QMainWindow,
        QMessageBox, QPlainTextEdit, QProgressBar,
        QPushButton, QVBoxLayout, QWidget,
    )

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("ReEzSynth-Windows-GUI — Prototype")
            self.resize(950, 700)
            self.last_output = None

            self.process = QProcess(self)
            self.process.setProcessChannelMode(
                QProcess.ProcessChannelMode.MergedChannels
            )
            self.process.readyReadStandardOutput.connect(self.read_logs)
            self.process.finished.connect(self.finished)
            self.process.errorOccurred.connect(self.process_error)

            panel = QWidget()
            layout = QVBoxLayout(panel)
            self.setCentralWidget(panel)

            description = QLabel(
                "Single-keyframe forward synthesis • Classic edges • RAFT Sintel\n"
                "The style image must correspond to the FIRST input frame.\n"
                "Prototype: all frames are loaded into RAM; start with a short clip."
            )
            description.setWordWrap(True)
            layout.addWidget(description)

            form = QFormLayout()
            layout.addLayout(form)

            self.inputs = QLineEdit()
            self.style = QLineEdit()
            self.outputs = QLineEdit(str(ROOT / "reezsynth_outputs"))

            self.controls = []
            self.add_path_row(form, "Input frame folder", self.inputs, False)
            self.add_path_row(form, "Style image", self.style, True)
            self.add_path_row(form, "Output parent folder", self.outputs, False)

            self.quality = QComboBox()
            self.quality.addItems(["Preview", "Standard"])
            form.addRow("Quality", self.quality)

            self.resolution = QComboBox()
            self.resolution.addItem("Preview — maximum width 512", 512)
            self.resolution.addItem("Maximum width 960", 960)
            self.resolution.addItem("Original resolution — high memory usage", 0)
            form.addRow("Processing size", self.resolution)

            self.controls.extend([self.quality, self.resolution])

            buttons = QHBoxLayout()
            self.start_button = QPushButton("Render")
            self.stop_button = QPushButton("Stop")
            self.open_button = QPushButton("Open Output Folder")

            self.stop_button.setEnabled(False)
            self.open_button.setEnabled(False)

            self.start_button.clicked.connect(self.start_render)
            self.stop_button.clicked.connect(self.stop_render)
            self.open_button.clicked.connect(self.open_output)

            for button in (
                self.start_button, self.stop_button, self.open_button
            ):
                buttons.addWidget(button)
            layout.addLayout(buttons)

            self.status = QLabel("Ready")
            layout.addWidget(self.status)

            self.progress = QProgressBar()
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.progress.setTextVisible(False)
            layout.addWidget(self.progress)

            self.logs = QPlainTextEdit()
            self.logs.setReadOnly(True)
            self.logs.setMaximumBlockCount(5000)
            layout.addWidget(self.logs)

            self.cancelled = False

        def add_path_row(self, form, label, field, is_file):
            row = QWidget()
            box = QHBoxLayout(row)
            box.setContentsMargins(0, 0, 0, 0)
            browse = QPushButton("Browse")

            def choose():
                if is_file:
                    selected, _ = QFileDialog.getOpenFileName(
                        self, label, "",
                        "Images (*.png *.jpg *.jpeg)"
                    )
                else:
                    selected = QFileDialog.getExistingDirectory(
                        self, label
                    )
                if selected:
                    field.setText(selected)

            browse.clicked.connect(choose)
            box.addWidget(field)
            box.addWidget(browse)
            form.addRow(label, row)
            self.controls.extend([field, browse])

        def set_busy(self, busy):
            self.start_button.setEnabled(not busy)
            self.stop_button.setEnabled(busy)
            for control in self.controls:
                control.setEnabled(not busy)
            self.progress.setRange(0, 0 if busy else 1)
            if not busy:
                self.progress.setValue(0)

        def start_render(self):
            try:
                if not self.inputs.text().strip():
                    raise ValueError("Choose an input folder.")
                if not self.style.text().strip():
                    raise ValueError("Choose a style image.")
                if not self.outputs.text().strip():
                    raise ValueError("Choose an output parent folder.")

                source = Path(self.inputs.text().strip()).resolve()
                style = Path(self.style.text().strip()).resolve()
                parent = Path(self.outputs.text().strip()).resolve()

                if not source.is_dir():
                    raise ValueError("Input folder does not exist.")
                if not style.is_file():
                    raise ValueError("Style image does not exist.")

                destination = parent / datetime.now().strftime(
                    "render_%Y%m%d_%H%M%S_%f"
                )
                destination.mkdir(parents=True, exist_ok=False)

                job = {
                    "input": str(source),
                    "style": str(style),
                    "output": str(destination),
                    "quality": self.quality.currentText(),
                    "max_width": self.resolution.currentData(),
                }

                job_path = destination / "job.json"
                job_path.write_text(
                    json.dumps(job, indent=2), encoding="utf-8"
                )

                self.last_output = destination
                self.open_button.setEnabled(True)
                self.cancelled = False
                self.logs.clear()
                self.status.setText("Rendering…")
                self.set_busy(True)

                self.process.setWorkingDirectory(str(ROOT))
                self.process.start(
                    sys.executable,
                    ["-u", str(Path(__file__).resolve()),
                     "--worker", str(job_path)],
                )

            except Exception as exc:
                QMessageBox.warning(self, "Cannot start render", str(exc))

        def read_logs(self):
            data = bytes(self.process.readAllStandardOutput())
            text = data.decode("utf-8", errors="replace").replace("\r", "\n")
            self.logs.appendPlainText(text.rstrip())

        def stop_render(self):
            self.cancelled = True
            self.status.setText("Stopping…")
            self.stop_button.setEnabled(False)
            self.process.kill()

        def finished(self, exit_code, exit_status):
            self.read_logs()
            self.set_busy(False)

            if self.cancelled:
                self.status.setText("Stopped — output may be incomplete")
            elif (
                exit_code == 0
                and exit_status == QProcess.ExitStatus.NormalExit
                and self.last_output
                and (self.last_output / "COMPLETE.txt").exists()
            ):
                self.status.setText("Render complete")
                self.progress.setValue(1)
            else:
                self.status.setText("Render failed — see log")

        def process_error(self, error):
            self.logs.appendPlainText(self.process.errorString())
            if error == QProcess.ProcessError.FailedToStart:
                self.set_busy(False)
                self.status.setText("Worker failed to start")

        def open_output(self):
            if self.last_output:
                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(self.last_output))
                )

        def closeEvent(self, event):
            if self.process.state() != QProcess.ProcessState.NotRunning:
                answer = QMessageBox.question(
                    self,
                    "Render running",
                    "Stop the render and close? Unsaved results will be lost.",
                )
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
                self.process.kill()
                if not self.process.waitForFinished(5000):
                    event.ignore()
                    return
            event.accept()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        try:
            render_job(sys.argv[2])
        except Exception:
            traceback.print_exc()
            sys.exit(1)
    else:
        sys.exit(launch_gui())