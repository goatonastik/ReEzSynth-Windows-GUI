"""Opt-in real edge-worker smoke check; no synthesis or optical-flow models load."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import os
import time
from datetime import datetime
from unittest.mock import patch

import cv2
import numpy as np

from reezsynth_engines import LEGACY, FUOUM, default_runtime


def gui_smoke(engine):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import reezsynth_gui as gui
    report = Path(__file__).parent / 'diagnostic_outputs' / ('edge_preview_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    report.mkdir(parents=True)
    app = QApplication.instance() or QApplication([])
    font = Path('C:/Windows/Fonts/segoeui.ttf')
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont('Segoe UI', 10))
    app.setStyle(gui.QueueStyle('Fusion'))
    app.setStyleSheet(gui.THEME)
    with tempfile.TemporaryDirectory(prefix='reezsynth-edge-gui-') as directory:
        root = Path(directory)
        frames = root / 'frames'
        frames.mkdir()
        image = np.random.default_rng(12).integers(30, 220, (128, 192, 3), dtype=np.uint8)
        (frames / 'frame000.png').write_bytes(cv2.imencode('.png', image)[1].tobytes())
        settings = QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
        settings.setFallbacksEnabled(False)
        with patch.object(gui, 'QSettings', return_value=settings):
            window = gui.MainWindow()
            try:
                window.video_dir.setText(str(frames))
                window.scan_timer.stop()
                window.set_processing_size([256, 128])
                window.options.widgets['render']['engine'].setCurrentText(engine)
                window.options.widgets['render']['edge_method'].setCurrentText('PST')
                window.options.widgets['render']['edge_pst_s'].setValue(.7)
                window.options.edge_toggle.setChecked(True)
                window.tabs.setCurrentIndex(1)
                window.show()
                window.options.open_edge_preview()
                preview = window.options.edge_preview
                preview.update_preview()
                assert preview.running(), preview.status.text()
                deadline = time.monotonic() + 45
                while preview.running() and time.monotonic() < deadline:
                    app.processEvents()
                    QTest.qWait(20)
                assert not preview.running(), 'Preview worker did not finish.'
                assert preview.status.text() == 'Preview up to date.', window.log.toPlainText()
                assert preview.temporary is None, 'Preview scratch was not cleaned.'
                assert len(preview.pixmaps) == 4
                preview.view.setCurrentIndex(preview.view.findData('comparison'))
                app.processEvents()
                window.tabs.currentWidget().ensureWidgetVisible(window.options.edge_reset)
                app.processEvents()
                window.grab().save(str(report / 'rendering.png'))
                preview.grab().save(str(report / 'preview.png'))
                window.options.widgets['render']['edge_pst_s'].setValue(.6)
                assert 'outdated' in preview.status.text()
                assert abs(preview.images[0].width() - preview.images[1].width()) <= 1
                preview.update_preview()
                preview.cancel()
                deadline = time.monotonic() + 10
                while preview.running() and time.monotonic() < deadline:
                    app.processEvents()
                    QTest.qWait(20)
                assert not preview.running(), 'Cancellation did not release the preview worker.'
                assert preview.temporary is None
                assert 'cancelled' in preview.status.text()
                preview.update_preview()
                deadline = time.monotonic() + 45
                while preview.running() and time.monotonic() < deadline:
                    app.processEvents()
                    QTest.qWait(20)
                assert not preview.running()
                assert preview.status.text() == 'Preview up to date.', window.log.toPlainText()
                print(f'GUI {engine}: preview, cancel/restart, cleanup and layout passed; screenshots in {report}', flush=True)
            finally:
                if window.options.edge_preview_active():
                    window.options.edge_preview.cancel()
                    deadline = time.monotonic() + 5
                    while window.options.edge_preview_active() and time.monotonic() < deadline:
                        app.processEvents()
                        QTest.qWait(20)
                window.close()
                app.processEvents()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('legacy', 'fuoum'), required=True)
    parser.add_argument('--gui', action='store_true', help='Exercise real asynchronous Qt preview and save offscreen screenshots.')
    args = parser.parse_args()
    engine = LEGACY if args.engine == 'legacy' else FUOUM
    if args.gui:
        gui_smoke(engine)
        return 0
    runtime = default_runtime()
    python = sys.executable if engine == LEGACY else runtime['fuoum_python']
    with tempfile.TemporaryDirectory(prefix='reezsynth-real-edge-check-') as directory:
        root = Path(directory)
        random = np.random.default_rng(12)
        image = random.integers(30, 220, (128, 192, 3), dtype=np.uint8)
        cv2.rectangle(image, (20, 20), (145, 95), (240, 240, 240), 3)
        source = root / 'frame000.png'
        source.write_bytes(cv2.imencode('.png', image)[1].tobytes())
        for method in ('Classic', 'PST', 'PAGE'):
            work = root / method
            work.mkdir()
            tuning = ({'edge_pst_s': .7, 'edge_pst_morph': False} if method == 'PST'
                      else {'edge_page_s1': .4, 'edge_page_morph': False} if method == 'PAGE' else {})
            request = dict(source=str(source), processing_size=[256, 128],
                           options=dict(engine=engine, edge_method=method, **tuning),
                           application=runtime)
            path = work / 'request.json'
            path.write_text(json.dumps(request), encoding='utf-8')
            result = subprocess.run([python, '-B', str(Path(__file__).with_name('reezsynth_edge_worker.py')), str(path)],
                capture_output=True, text=True, timeout=60,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            metadata = json.loads((work / 'result.json').read_text())
            assert metadata['size'] == [256, 128], metadata
            edges = cv2.imdecode(np.frombuffer((work / 'edges.png').read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            defaults = cv2.imdecode(np.frombuffer((work / 'defaults.png').read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            assert edges.shape == defaults.shape == (128, 256, 3)
            assert np.isfinite(edges).all()
            changed = int(np.count_nonzero(edges != defaults))
            if method == 'Classic':
                assert changed == 0
            else:
                assert changed > 0, f'{method} tuning did not change this diagnostic edge map.'
            print(f'{args.engine} {method}: passed, 256x128, {changed} changed channel samples.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
