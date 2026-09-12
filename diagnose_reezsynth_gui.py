"""Run one small real queue through the offscreen MainWindow controller.

Uses temporary preferences and copied bundled inputs. Output is written only to
diagnostic_outputs/. This is an opt-in CUDA diagnostic, not a normal test.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import argparse
from datetime import datetime
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import reezsynth_gui as gui


def until(app, predicate, seconds, failure):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise RuntimeError(failure)


def main(parallel=False, cancel=False, close_window=False, restart_after_cancel=False, fuoum=False,
         frames=None, cache_reuse=False):
    root = Path(__file__).resolve().parent
    base = root / 'diagnostic_outputs' / ('gui_controller_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    video, keys, project = base / 'video', base / 'keys', base / 'project'
    video.mkdir(parents=True)
    keys.mkdir()
    project.mkdir()
    for number in range(frames or (24 if cancel or close_window or restart_after_cancel else 3)):
        shutil.copy2(root / 'examples' / 'input' / f'{number % 3:03d}.jpg', video / f'frame{number:03d}.jpg')
    shutil.copy2(root / 'examples' / 'styles' / 'style000.jpg', keys / 'style000.jpg')
    if parallel:
        shutil.copy2(root / 'examples' / 'styles' / 'style002.png', keys / 'style002.png')

    app = QApplication.instance() or QApplication([])
    app.setStyle(gui.QueueStyle('Fusion'))
    app.setStyleSheet(gui.THEME)
    settings = QSettings(str(base / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setFallbacksEnabled(False)
    with patch.object(gui, 'QSettings', return_value=settings):
        window = gui.MainWindow()
        try:
            window.project_dir.setText(str(project))
            window.video_dir.setText(str(video))
            window.keyframe_dir.setText(str(keys))
            window.quality.setCurrentText('Preview')
            window.set_processing_size([512, 288])
            if fuoum:
                from reezsynth_engines import FUOUM
                window.options.widgets['render']['engine'].setCurrentText(FUOUM)
            if parallel:
                window.options.widgets['application']['parallel'].setChecked(True)
                window.options.widgets['application']['parallel_limit'].setValue(0)
            expected_jobs = 2 if parallel else 1
            if not window.rebuild_queue(show_error=True) or len(window.rows) != expected_jobs:
                raise RuntimeError('Could not build the diagnostic queue.')
            window.show()
            window.preview_window.show()
            app.processEvents()
            window.run_rows(list(window.rows))
            until(app, lambda: window.busy, 10, 'GUI queue did not start.')
            if cancel or close_window or restart_after_cancel:
                timing = '[Timing] FuouM frame ' if fuoum else '[Timing] Frame '
                until(app, lambda: timing in window.log.toPlainText(),
                      90, 'GUI queue did not complete its first native synthesis call.')
                if close_window:
                    with patch.object(gui.QMessageBox, 'question',
                                      return_value=gui.QMessageBox.StandardButton.Yes):
                        window.close()
                    until(app, lambda: not window.isVisible(), 30, 'GUI window did not close after cancellation.')
                else:
                    window.stop_queue()
                until(app, lambda: not window.busy, 30, 'Stopped GUI worker did not exit.')
                output = window.batch
                if output is not None and any(output.rglob('COMPLETE.txt')):
                    raise RuntimeError('Stopped GUI queue wrote a completion marker.')
                if window.process is not None or window.parallel_queue is not None:
                    raise RuntimeError('Stopped GUI queue did not finalize its worker process.')
                if restart_after_cancel:
                    if not window.rebuild_queue(show_error=True):
                        raise RuntimeError('Could not rebuild the GUI queue after cancellation.')
                    window.run_rows(list(window.rows))
                    until(app, lambda: window.busy, 10, 'Restarted GUI queue did not start.')
                    until(app, lambda: not window.busy, 120, 'Restarted GUI queue did not finish.')
                    if window.batch is None or not any(window.batch.rglob('COMPLETE.txt')):
                        raise RuntimeError('Restarted GUI queue did not produce a completion marker.')
                    print('GUI controller cancellation/restart diagnostic passed.')
                    print('Output folder:', window.batch)
                    return
                print('GUI controller close diagnostic passed.' if close_window else
                      'GUI controller cancellation diagnostic passed.')
                print('Output folder:', output)
                return
            previewed = {'value': False}
            def preview_ready():
                previewed['value'] = previewed['value'] or any(
                    not tile.pixmap.isNull() for tile in window.preview_window.tiles.values())
                return previewed['value']
            until(app, preview_ready, 90, 'GUI preview did not receive a synthesized frame.')
            until(app, lambda: not window.busy, 120, 'GUI queue did not finish.')
            if parallel and window.queue_mode != 'parallel':
                raise RuntimeError('GUI diagnostic did not enter parallel mode.')
            output = window.batch
            markers = [] if output is None else list(output.rglob('COMPLETE.txt'))
            if len(markers) != expected_jobs:
                raise RuntimeError('GUI queue did not produce a completion marker.')
            if window.process is not None or window.parallel_queue is not None:
                raise RuntimeError('GUI queue did not finalize its worker process.')
            if parallel:
                resource_log = window.log.toPlainText()
                if ('[Parallel resources] GPU ' not in resource_log or
                        resource_log.count('estimated peak') < expected_jobs or
                        resource_log.count('reserved estimate') < expected_jobs):
                    raise RuntimeError('Parallel GUI queue did not report GPU and per-worker resources.')
                (base / 'controller.log').write_text(resource_log, encoding='utf-8')
            if cache_reuse:
                controls = window.options.widgets['render']
                controls['uniformity'].setValue(controls['uniformity'].value() + 1)
                before = len(window.log.toPlainText())
                if not window.rebuild_queue(show_error=True):
                    raise RuntimeError('Could not rebuild the cache-reuse queue.')
                window.run_rows(list(window.rows))
                until(app, lambda: window.busy, 10, 'Cache-reuse queue did not start.')
                until(app, lambda: not window.busy, 120, 'Cache-reuse queue did not finish.')
                second_log = window.log.toPlainText()[before:]
                if '[Cache] Reused' not in second_log or 'optical-flow pair' not in second_log:
                    raise RuntimeError('Second GUI queue did not report validated flow-cache reuse.')
                if window.batch is None or len(list(window.batch.rglob('COMPLETE.txt'))) != expected_jobs:
                    raise RuntimeError('Cache-reuse queue did not complete every job.')
                print('GUI cache-reuse diagnostic passed.')
                print('Second output folder:', window.batch)
            print('GUI controller diagnostic passed.')
            print('Output folder:', output)
        finally:
            if window.busy:
                window.stop_queue()
                until(app, lambda: not window.busy, 30, 'Cancelled GUI worker did not exit.')
            window.preview_window.close()
            window.close()
            window.deleteLater()
            app.processEvents()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fuoum', action='store_true', help='Exercise the dedicated FuouM engine worker.')
    parser.add_argument('--frames', type=int, help='Override input length for stress checks (at least 3).')
    parser.add_argument('--cycles', type=int, default=1, help='Repeat the full create/run/close lifecycle.')
    parser.add_argument('--parallel', action='store_true',
                        help='Run two independent jobs through the GUI ParallelQueue.')
    parser.add_argument('--cancel', action='store_true',
                        help='Stop a longer small shared-worker queue after synthesis begins.')
    parser.add_argument('--close', action='store_true',
                        help='Close the window during synthesis and accept the stop confirmation.')
    parser.add_argument('--cancel-restart', action='store_true',
                        help='Stop a queue after synthesis begins, then rebuild and complete a new queue.')
    parser.add_argument('--cache-reuse', action='store_true',
                        help='Run a second queue with changed synthesis settings and require cache reuse.')
    args = parser.parse_args()
    try:
        if sum(bool(option) for option in (args.parallel, args.cancel, args.close, args.cancel_restart)) > 1:
            raise SystemExit('Choose only one of --parallel, --cancel, --close, or --cancel-restart.')
        if args.cycles < 1 or (args.frames is not None and args.frames < 3):
            parser.error('Use at least one cycle and three frames.')
        from diagnose_reezsynth_engines import gpu_memory
        print('Aggregate GPU memory before cycles:', gpu_memory(), flush=True)
        for cycle in range(args.cycles):
            main(args.parallel, args.cancel, args.close, args.cancel_restart, args.fuoum, args.frames,
                 args.cache_reuse)
            print(f'Cycle {cycle + 1}/{args.cycles}; aggregate GPU memory: {gpu_memory()}', flush=True)
    except Exception as exc:
        print(f'GUI controller diagnostic failed: {exc}', file=sys.stderr)
        raise
