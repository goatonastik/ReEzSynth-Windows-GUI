"""Explicit, process-isolated edge previews. Frontend imports no rendering engines."""
import json
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton,
                              QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from reezsynth_engines import FUOUM, default_runtime
from reezsynth_jobs import scan_images


class EdgeImage(QLabel):
    """Equal-size comparison panes that rescale after their layout changes."""
    def __init__(self):
        super().__init__()
        self.original = None
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def show_image(self, pixmap):
        self.original = pixmap
        self.scale_image()

    def scale_image(self):
        if self.original is not None:
            self.setPixmap(self.original.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.scale_image()


class EdgePreviewWindow(QDialog):
    def __init__(self, options):
        super().__init__(options.w)
        self.options = options
        self.setModal(False)
        self.setWindowTitle('Edge Preview')
        self.resize(1000, 700)
        self.process = None
        self.gpu_token = None
        self.temporary = None
        self.request_signature = None
        self.output = ''
        self.cancelled = False
        self.close_pending = False
        self.close_parent = False
        self.pixmaps = {}
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.frames = QComboBox()
        self.frames.setMinimumContentsLength(20)
        self.frames.currentIndexChanged.connect(self.invalidate)
        row.addWidget(QLabel('Source frame'))
        row.addWidget(self.frames, 1)
        self.refresh_button = QPushButton('Refresh frame list')
        self.refresh_button.clicked.connect(self.refresh_frames)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.update_button = QPushButton('Update Preview')
        self.update_button.clicked.connect(self.update_preview)
        row.addWidget(self.update_button)
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        self.view = QComboBox()
        for name, key in (('Source', 'source'), ('Edges', 'edges'), ('Overlay (50%)', 'overlay'),
                          ('Detector defaults', 'defaults'), ('Current / defaults side by side', 'comparison')):
            self.view.addItem(name, key)
        self.view.setCurrentIndex(1)
        self.view.currentIndexChanged.connect(self.display)
        row.addWidget(self.view, 1)
        layout.addLayout(row)
        self.status = QLabel('Choose a frame, then Update Preview.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.size_label = QLabel('Computed at the rendering processing size; display scales to fit.')
        layout.addWidget(self.size_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        images = QHBoxLayout(content)
        self.images = [EdgeImage(), EdgeImage()]
        for image in self.images:
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setMinimumSize(100, 100)
            images.addWidget(image, 1)
        self.images[1].hide()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.stop_timer = QTimer(self)
        self.stop_timer.setSingleShot(True)
        self.stop_timer.setInterval(1500)
        self.stop_timer.timeout.connect(self.force_stop)
        self.refresh_frames()

    def running(self):
        return self.process is not None

    def refresh_frames(self):
        if self.running():
            return
        previous = self.frames.currentData()
        self.frames.clear()
        try:
            frames, _ = scan_images(self.options.w.video_dir.text(), source=True)
            for number, path in frames.items():
                self.frames.addItem(f'{number}: {path.name}', str(path))
            index = self.frames.findData(previous)
            if index >= 0:
                self.frames.setCurrentIndex(index)
            self.invalidate()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def request(self):
        source = self.frames.currentData()
        if not source:
            raise ValueError('Select a source-frame folder and refresh the frame list.')
        options = self.options.render(effective=True)
        source_frames, _ = scan_images(self.options.w.video_dir.text(), source=True)
        if source not in {str(path) for path in source_frames.values()}:
            raise ValueError('The source folder changed. Refresh the frame list before previewing.')
        request = dict(source=source, options=options,
                       application=self.options.application(), **self.options.w.processing_state())
        if options['do_mask'] and options['pre_mask']:
            number = next((n for n, path in source_frames.items() if str(path) == source), None)
            masks, _ = scan_images(self.options.w.mask_dir.text())
            if number not in masks:
                raise ValueError('The selected frame has no matching premask.')
            request['mask'] = str(masks[number])
        return request

    def signature(self, request):
        identities = []
        for name in ('source', 'mask'):
            if name in request:
                path = Path(request[name])
                stat = path.stat()
                identities.append((str(path), stat.st_size, stat.st_mtime_ns))
        return json.dumps([request, identities], sort_keys=True)

    def invalidate(self, *_):
        if self.running():
            return  # Completion compares the submitted request with current settings.
        if self.pixmaps:
            self.status.setText('Preview outdated — Update Preview to apply current settings.')

    def update_preview(self):
        w = self.options.w
        wait_message = w.comfy_tab.gpu_wait_message()
        if wait_message:
            self.status.setText(wait_message)
            return
        if (self.running() or w.busy or w.process is not None or w.close_when_idle
                or self.options.installation_active()):
            self.status.setText('Wait for rendering or component maintenance to finish.')
            return
        try:
            self.cleanup()
            if self.temporary is not None:
                raise ValueError('Previous preview files could not be cleaned. See Diagnostics / Log.')
            request = self.request()
            if request['options']['custom_edge_guides']:
                raise ValueError('Custom edge guides bypass detector tuning and automatic preview.')
            self.request_signature = self.signature(request)
            defaults = default_runtime()
            application = request['application']
            python = (application.get('fuoum_python') or defaults['fuoum_python']
                      if request['options']['engine'] == FUOUM else sys.executable)
            if not Path(python).is_file():
                raise ValueError('The selected engine Python executable is missing. Check Settings.')
            self.gpu_token = w.gpu_gate.acquire('Edge Preview')
            self.temporary = tempfile.TemporaryDirectory(prefix='reezsynth-edge-preview-')
            path = Path(self.temporary.name) / 'request.json'
            path.write_text(json.dumps(request, allow_nan=False), encoding='utf-8')
        except (OSError, ValueError, StopIteration) as exc:
            self.cleanup()
            if self.gpu_token is not None:
                w.gpu_gate.release(self.gpu_token)
                self.gpu_token = None
            self.status.setText(f'Cannot preview: {exc}')
            return
        self.cancelled = False
        self.output = ''
        process = None
        try:
            process = QProcess(self)
            self.process = process
            process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            process.setWorkingDirectory(str(Path(__file__).resolve().parent))
            process.readyReadStandardOutput.connect(lambda p=process: self.read_output(p))
            process.finished.connect(lambda code, status, p=process: self.finished(p, code))
            process.errorOccurred.connect(lambda error, p=process: self.process_error(p, error))
            self.status.setText('Computing one frame in a separate process…')
            self.update_button.setEnabled(False)
            self.refresh_button.setEnabled(False)
            self.frames.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self.options.refresh_engine_controls()
            process.start(str(python), ['-B', str(Path(__file__).with_name('reezsynth_edge_worker.py')), str(path)])
        except Exception as exc:
            if process is not None and process.state() != QProcess.ProcessState.NotRunning:
                # A worker may have started before the exception. Keep ownership
                # until its finished signal proves the process has exited.
                process.kill()
                self.status.setText(f'Preview launch failed; waiting for worker exit: {exc}')
                return
            self.process = None
            if process is not None:
                process.deleteLater()
            self.cleanup()
            if self.gpu_token is not None:
                w.gpu_gate.release(self.gpu_token)
                self.gpu_token = None
            self.update_button.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.frames.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.status.setText(f'Cannot start preview: {exc}')

    def read_output(self, process):
        if process is self.process:
            self.output = (self.output + bytes(process.readAllStandardOutput()).decode('utf-8', 'replace'))[-12000:]

    def process_error(self, process, error):
        if process is self.process and error == QProcess.ProcessError.FailedToStart:
            self.output += '\n' + process.errorString()
            self.finished(process, -1)

    def finished(self, process, code):
        if process is not self.process:
            return
        self.stop_timer.stop()
        self.read_output(process)
        try:
            if self.cancelled:
                self.status.setText('Preview cancelled. Previous images have not been updated.')
            elif code != 0:
                raise ValueError(self.output.strip() or f'Preview worker exited with code {code}.')
            else:
                directory = Path(self.temporary.name)
                result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
                pixmaps = {name: QPixmap(str(directory / f'{name}.png'))
                           for name in ('source', 'edges', 'defaults', 'overlay')}
                if any(image.isNull() for image in pixmaps.values()):
                    raise ValueError('Preview worker produced unreadable images.')
                self.pixmaps = pixmaps
                width, height = result['size']
                self.size_label.setText(f'Computed at {width} × {height}, matching render processing size. Display scales to fit.')
                try:
                    current = self.signature(self.request()) == self.request_signature
                except (ValueError, OSError):
                    current = False
                self.status.setText('Preview up to date.' if current else 'Preview outdated — settings or input changed while computing.')
                self.display()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            detail = str(exc).splitlines()[-1][:200] if str(exc) else 'Unknown worker error.'
            self.status.setText(f'Preview failed: {detail}\nSee Diagnostics / Log for details.')
            self.options.w.log.appendPlainText(f'[Edge Preview] {exc}')
        finally:
            self.process = None
            process.deleteLater()
            self.cleanup()
            if self.gpu_token is not None:
                self.options.w.gpu_gate.release(self.gpu_token)
                self.gpu_token = None
            self.update_button.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.frames.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.options.refresh_engine_controls()
            if self.close_parent:
                self.close_parent = False
                QTimer.singleShot(0, self.options.w.close)
            if self.close_pending:
                self.close_pending = False
                self.close()

    def cleanup(self):
        if self.temporary is not None:
            try:
                self.temporary.cleanup()
                self.temporary = None
            except OSError as exc:
                self.options.w.log.appendPlainText(f'[Edge Preview] Temporary-file cleanup failed: {exc}')

    def cancel(self):
        if self.running() and not self.cancelled:
            self.cancelled = True
            self.status.setText('Stopping preview…')
            self.process.terminate()
            self.stop_timer.start()

    def force_stop(self):
        if self.running():
            self.process.kill()

    def display(self, *_):
        key = self.view.currentData()
        comparison = key == 'comparison'
        self.images[1].setVisible(comparison)
        names = ('edges', 'defaults') if comparison else (key,)
        for label, name in zip(self.images, names):
            pixmap = self.pixmaps.get(name)
            if pixmap is not None:
                label.show_image(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'view'):
            self.display()

    def reject(self):
        self.close()  # Escape follows the same asynchronous shutdown as the close button.

    def closeEvent(self, event):
        if self.running():
            self.close_pending = True
            self.cancel()
            event.ignore()
        else:
            event.accept()
