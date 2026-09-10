import codecs
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
PROGRESS_PREFIX = "@@REEZSYNTH_PROGRESS@@"


# ---------- Worker progress protocol ----------

def report_progress(percent, stage):
    # The GUI alone sets 100%, after a successful worker exit.
    message = {
        "percent": max(0, min(99, int(percent))),
        "stage": stage,
    }
    print(
        "\n" + PROGRESS_PREFIX + json.dumps(message, ensure_ascii=True),
        flush=True,
    )


# ---------- Render worker: separate process ----------

def render_job(job_path):
    # Must be set before importing modules that import tqdm.
    os.environ["TQDM_DISABLE"] = "1"

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    report_progress(0, "Loading engine libraries...")

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

    def read_image(path):
        # Python file I/O avoids OpenCV filename-encoding issues on Windows.
        path = Path(path)
        data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
        if data.size == 0:
            raise ValueError(f"Image file is empty: {path}")

        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not decode image: {path}")
        return image

    paths = sorted(
        [
            path for path in Path(job["input"]).iterdir()
            if path.is_file()
            and path.suffix.lower() in IMAGE_EXTENSIONS
        ],
        key=natural_key,
    )

    count = len(paths)

    if count < 2:
        raise ValueError("Input folder must contain at least two image frames.")

    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch CUDA is unavailable in this environment.")

    print("GPU:", torch.cuda.get_device_name(0), flush=True)
    print("Input frames:", count, flush=True)
    print("First frame:", paths[0].name, flush=True)
    print("Last frame:", paths[-1].name, flush=True)
    print("The style image is assigned to the FIRST input frame.", flush=True)

    (output / "input_manifest.json").write_text(
        json.dumps([str(path) for path in paths], indent=2),
        encoding="utf-8",
    )

    # Loading: 0-10%.
    frames = []
    original_shape = None
    target_size = None

    for index, path in enumerate(paths):
        image = read_image(path)

        if original_shape is None:
            original_shape = image.shape
            height, width = image.shape[:2]

            limit = int(job["max_width"])
            scale = min(1.0, limit / width) if limit else 1.0

            target_size = (
                max(1, round(width * scale)),
                max(1, round(height * scale)),
            )

            if min(target_size) < 128:
                raise ValueError(
                    "For this prototype, processing width and height "
                    "must both be at least 128 pixels."
                )

        if image.shape != original_shape:
            raise ValueError(
                f"Input frame dimensions differ: {path.name}"
            )

        if image.shape[1::-1] != target_size:
            image = cv2.resize(
                image, target_size, interpolation=cv2.INTER_AREA
            )

        frames.append(image)
        report_progress(
            10 * (index + 1) / count,
            f"Loading frames: {index + 1}/{count}",
        )

    style = read_image(job["style"])

    if style.shape != original_shape:
        raise ValueError(
            "The style image must match the ORIGINAL input frame dimensions."
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

    # Initialization: holds at 10%, then reaches 15% when ready.
    report_progress(10, "Initializing edge guides, RAFT, and EbSynth...")

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

    # Uses the backend-forwarding edits from the earlier diagnostics.
    runner.eb.backend = runner.eb.backends["cuda"]
    print("Requested EbSynth backend: CUDA", flush=True)

    expected_generated = count - 1
    generated = 0
    original_run = runner.eb.run

    # Count actual completed EbSynth calls. This is valid for this
    # single-keyframe, forward-only workflow.
    def tracked_run(*args, **kwargs):
        nonlocal generated

        result = original_run(*args, **kwargs)
        generated += 1

        report_progress(
            15 + 75 * generated / expected_generated,
            f"Synthesizing frames: {generated}/{expected_generated}",
        )
        return result

    runner.eb.run = tracked_run

    # Synthesis: 15-90%.
    report_progress(
        15, f"Synthesizing frames: 0/{expected_generated}"
    )

    try:
        results, errors = runner.run_sequences()
    finally:
        runner.eb.run = original_run

    if generated != expected_generated or len(results) != count:
        raise RuntimeError(
            f"Unexpected result counts: {generated} generated, "
            f"{len(results)} total; expected "
            f"{expected_generated} generated and {count} total."
        )

    # Saving: 90-99%.
    report_progress(90, f"Saving frames: 0/{count}")

    for index, image in enumerate(results):
        if image.shape != frames[index].shape:
            raise RuntimeError(
                f"Unexpected dimensions at output frame {index}."
            )

        if not np.isfinite(image).all():
            raise RuntimeError(
                f"Invalid pixel values at output frame {index}."
            )

        image = np.clip(image, 0, 255).astype(np.uint8)
        encoded_ok, encoded = cv2.imencode(".png", image)

        if not encoded_ok:
            raise OSError(f"Could not encode output frame {index}.")

        path = output / f"output_{index:06d}.png"
        temporary = output / f"output_{index:06d}.png.part"

        temporary.write_bytes(encoded.tobytes())
        temporary.replace(path)

        report_progress(
            90 + 9 * (index + 1) / count,
            f"Saving frames: {index + 1}/{count}",
        )

    (output / "COMPLETE.txt").write_text(
        f"Successfully saved {count} frames.\n"
        f"One supplied style frame and {generated} generated frames.\n",
        encoding="utf-8",
    )

    report_progress(99, "Output saved; finishing worker...")
    print(f"COMPLETE: {count} frames saved to {output}", flush=True)


# ---------- GUI ----------

def launch_gui():
    from PySide6.QtCore import QProcess, Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    class DropPathEdit(QLineEdit):
        def __init__(self, kind):
            super().__init__()
            self.kind = kind
            self.setAcceptDrops(True)

            hint = (
                "Drop one folder here"
                if kind == "folder"
                else "Drop one PNG or JPEG image here"
            )
            self.setPlaceholderText(hint)
            self.setToolTip(hint + ", or use Browse.")

        def dropped_path(self, event):
            if not self.isEnabled() or not event.mimeData().hasUrls():
                return None

            urls = event.mimeData().urls()
            if len(urls) != 1 or not urls[0].isLocalFile():
                return None

            try:
                # Correctly decodes file URLs, spaces, and Unicode names.
                path = Path(urls[0].toLocalFile())

                if self.kind == "folder":
                    valid = path.is_dir()
                else:
                    valid = (
                        path.is_file()
                        and path.suffix.lower() in IMAGE_EXTENSIONS
                    )

                return str(path) if valid else None
            except (OSError, ValueError):
                return None

        def dragEnterEvent(self, event):
            if self.dropped_path(event) is not None:
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()

        def dragMoveEvent(self, event):
            self.dragEnterEvent(event)

        def dropEvent(self, event):
            path = self.dropped_path(event)

            if path is None:
                event.ignore()
                return

            self.setText(path)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("ReEzSynth-Windows-GUI - v0.2")
            self.resize(980, 720)

            self.last_output = None
            self.cancelled = False
            self.controls = []
            self.reset_streams()

            self.process = QProcess(self)
            self.process.setProcessChannelMode(
                QProcess.ProcessChannelMode.SeparateChannels
            )
            self.process.readyReadStandardOutput.connect(
                lambda: self.read_stream("out")
            )
            self.process.readyReadStandardError.connect(
                lambda: self.read_stream("err")
            )
            self.process.finished.connect(self.finished)
            self.process.errorOccurred.connect(self.process_error)

            panel = QWidget()
            layout = QVBoxLayout(panel)
            self.setCentralWidget(panel)

            description = QLabel(
                "Single-keyframe forward synthesis | Classic edges | RAFT Sintel\n"
                "Assign a style image matching the FIRST input frame.\n"
                "Drop folders/images directly onto their path fields.\n"
                "All frames are loaded into RAM: start with a short preview."
            )
            description.setWordWrap(True)
            layout.addWidget(description)

            form = QFormLayout()
            layout.addLayout(form)

            self.inputs = DropPathEdit("folder")
            self.style = DropPathEdit("image")
            self.outputs = DropPathEdit("folder")
            self.outputs.setText(str(ROOT / "reezsynth_outputs"))

            self.add_path_row(
                form, "Input frame folder", self.inputs, False
            )
            self.add_path_row(
                form, "Style image", self.style, True
            )
            self.add_path_row(
                form, "Output parent folder", self.outputs, False
            )

            self.quality = QComboBox()
            self.quality.addItems(["Preview", "Standard"])
            form.addRow("Quality", self.quality)

            self.resolution = QComboBox()
            self.resolution.addItem("Maximum width 512 - preview", 512)
            self.resolution.addItem("Maximum width 960", 960)
            self.resolution.addItem(
                "Original resolution - high memory usage", 0
            )
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
            self.status.setWordWrap(True)
            layout.addWidget(self.status)

            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("%p%")
            self.progress.setTextVisible(True)
            self.progress.setToolTip(
                "Phase-weighted completed work, not an ETA. "
                "100% means output saved and worker exited successfully."
            )
            layout.addWidget(self.progress)

            layout.addWidget(QLabel("Log"))

            self.logs = QPlainTextEdit()
            self.logs.setReadOnly(True)
            self.logs.setMaximumBlockCount(5000)
            layout.addWidget(self.logs)

        def add_path_row(self, form, label, field, is_file):
            row = QWidget()
            box = QHBoxLayout(row)
            box.setContentsMargins(0, 0, 0, 0)
            browse = QPushButton("Browse")

            def choose():
                if is_file:
                    selected, _ = QFileDialog.getOpenFileName(
                        self, label, "", "Images (*.png *.jpg *.jpeg)"
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

        def reset_streams(self):
            self.decoders = {
                name: codecs.getincrementaldecoder("utf-8")(
                    errors="replace"
                )
                for name in ("out", "err")
            }
            self.buffers = {"out": "", "err": ""}
            self.streams_closed = False

        def start_render(self):
            if self.process.state() != QProcess.ProcessState.NotRunning:
                return

            try:
                def selected_path(field, label):
                    text = field.text().strip().strip('"')
                    if not text:
                        raise ValueError(f"Choose {label}.")
                    return Path(text).expanduser().resolve()

                source = selected_path(self.inputs, "an input folder")
                style = selected_path(self.style, "a style image")
                parent = selected_path(
                    self.outputs, "an output parent folder"
                )

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
                self.cancelled = False
                self.reset_streams()
                self.logs.clear()
                self.progress.setValue(0)
                self.status.setText("Starting worker...")
                self.open_button.setEnabled(True)
                self.set_busy(True)

                self.process.setWorkingDirectory(str(ROOT))
                self.process.start(
                    sys.executable,
                    [
                        "-X", "utf8", "-u",
                        str(Path(__file__).resolve()),
                        "--worker", str(job_path),
                    ],
                )

            except Exception as exc:
                self.set_busy(False)
                QMessageBox.warning(
                    self, "Cannot start render", str(exc)
                )

        def read_stream(self, name, final=False):
            if self.streams_closed:
                return

            getter = (
                self.process.readAllStandardOutput
                if name == "out"
                else self.process.readAllStandardError
            )

            text = self.decoders[name].decode(
                bytes(getter()), final=final
            )
            self.buffers[name] += text.replace("\r", "\n")

            # Buffer partial lines: QProcess messages can arrive in chunks.
            while "\n" in self.buffers[name]:
                line, self.buffers[name] = self.buffers[name].split(
                    "\n", 1
                )
                self.consume_line(name, line)

            if final and self.buffers[name]:
                self.consume_line(name, self.buffers[name])
                self.buffers[name] = ""

        def consume_line(self, name, line):
            if not line.strip():
                return

            if name == "out" and line.startswith(PROGRESS_PREFIX):
                try:
                    message = json.loads(line[len(PROGRESS_PREFIX):])
                    value = int(message["percent"])
                    stage = str(message["stage"])
                except (ValueError, KeyError, TypeError):
                    self.logs.appendPlainText(line)
                else:
                    if not self.cancelled:
                        value = max(0, min(99, value))
                        self.progress.setValue(
                            max(self.progress.value(), value)
                        )
                        self.status.setText(stage)

                # Progress belongs in the UI, not the scrolling log.
                return

            self.logs.appendPlainText(line)

        def stop_render(self):
            if self.process.state() == QProcess.ProcessState.NotRunning:
                return

            self.cancelled = True
            self.status.setText("Stopping...")
            self.stop_button.setEnabled(False)
            self.process.kill()

        def finished(self, exit_code, exit_status):
            self.read_stream("out", final=True)
            self.read_stream("err", final=True)
            self.streams_closed = True
            self.set_busy(False)

            successful = (
                exit_code == 0
                and exit_status == QProcess.ExitStatus.NormalExit
                and self.last_output is not None
                and (self.last_output / "COMPLETE.txt").is_file()
            )

            if self.cancelled:
                self.status.setText(
                    "Stopped - output may be incomplete"
                )
            elif successful:
                self.progress.setValue(100)
                self.status.setText("Render complete")
            else:
                self.status.setText(
                    "Render failed - see the log"
                )

        def process_error(self, error):
            if not self.cancelled:
                self.logs.appendPlainText(
                    "Worker error: " + self.process.errorString()
                )

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
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )

                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return

                self.cancelled = True
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