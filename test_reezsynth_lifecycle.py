"""Real QProcess lifecycle tests with temporary scripts; no GPU rendering."""
import shutil
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QProcess
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from test_reezsynth_gui import GuiFixture, gui

SOURCE = Path(__file__).resolve().parent
MOCK_RENDERER = '''
import json
import time
from pathlib import Path

def render_job(job_path):
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    mode = Path(__file__).with_name("mode.txt").read_text()
    print("MOCK_STARTED", flush=True)
    if mode == "slow":
        time.sleep(30)
    if mode == "fail":
        raise RuntimeError("Intentional render failure")
    if mode == "oom":
        raise RuntimeError("CUDA out of memory. Tried to allocate 62.57 GiB.")
    Path(job["output"], "COMPLETE.txt").write_text("done")

if __name__ == "__main__":
    import sys
    render_job(sys.argv[1])
'''


class LifecycleFixture(GuiFixture):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(gui, 'validate_flow_model_available'))
        shutil.copy2(SOURCE / "reezsynth_shared_worker.py", self.root)
        (self.root / "reezsynth_jobs.py").write_text(MOCK_RENDERER, encoding="utf-8")
        self.mode("normal")
        video = Path(self.directory("video"))
        keys = Path(self.directory("keys"))
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(0)
        for i in range(3):
            self.assertTrue(image.save(str(video / f"frame{i:03d}.png")))
        for i in (0, 2):
            self.assertTrue(image.save(str(keys / f"style{i:03d}.png")))
        self.w = self.window()
        self.w.project_dir.setText(str(self.root / "project"))
        self.w.video_dir.setText(str(video))
        self.w.keyframe_dir.setText(str(keys))
        self.assertTrue(self.w.rebuild_queue())
        self.addCleanup(self.reap)

    def mode(self, mode):
        (self.root / "mode.txt").write_text(mode, encoding="utf-8")

    def until(self, predicate, seconds=5):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate(), self.w.log.toPlainText())

    def reap(self):
        # Emergency cleanup only: tests themselves assert asynchronous finalization.
        if self.w.parallel_queue is not None:
            self.w.stop_queue()
            self.until(lambda: self.w.parallel_queue is None)
        if self.w.process is not None:
            self.w.stop_queue()
            self.until(lambda: self.w.process is None)
        self.w.close_when_idle = False

    def run_queue(self, shared=True):
        self.w.reuse_worker.setChecked(shared)
        self.w.run_rows(list(self.w.rows))


class LifecycleTests(LifecycleFixture):
    def test_cuda_oom_popup_all_worker_modes_and_restart(self):
        for shared, parallel in ((True, False), (False, False), (False, True)):
            self.w.options.widgets['application']['parallel'].setChecked(parallel)
            self.mode('oom')
            self.run_queue(shared)
            self.until(lambda: not self.w.busy)
            dialogs = [d for d in self.w.findChildren(gui.QMessageBox)
                       if d.windowTitle() == 'GPU out of memory']
            self.assertEqual(len(dialogs), 1)
            self.assertTrue(dialogs[0].isVisible())
            self.assertIn('62.57 GiB', dialogs[0].detailedText())
            self.assertTrue(self.w.gpu_memory_error_reported)
            self.assertIsNone(self.w.process)
            self.assertIsNone(self.w.parallel_queue)
            self.w.check_gpu_memory_error('RuntimeError: CUDA out of memory')
            self.assertEqual(len(self.w.findChildren(gui.QMessageBox)), 1)
            dialogs[0].close()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.mode('normal')
            self.run_queue(shared)
            self.until(lambda: not self.w.busy)
            self.assertFalse(self.w.gpu_memory_error_reported)
            self.assertEqual(self.w.overall.value(), 100)

    def test_shared_completion_and_restart(self):
        for _ in range(2):
            self.run_queue()
            self.until(lambda: not self.w.busy)
            self.assertIsNone(self.w.process)
            self.assertEqual(self.w.overall.value(), 100)
            self.assertTrue(all(r["state"].text() == "Complete" for r in self.w.rows))
            self.assertIn("Queue cleanup complete", self.w.log.toPlainText())

    def test_isolated_completion(self):
        self.run_queue(False)
        self.until(lambda: not self.w.busy)
        self.assertIsNone(self.w.process)
        self.assertEqual(self.w.overall.value(), 100)

    def test_cancellation_waits_for_exit_and_can_restart(self):
        self.mode("slow")
        self.run_queue()
        self.until(lambda: "MOCK_STARTED" in self.w.log.toPlainText())
        old = self.w.process
        self.w.stop_queue()
        self.assertTrue(self.w.busy)
        self.assertFalse(self.w.run_all.isEnabled())
        self.until(lambda: not self.w.busy)
        self.assertIsNone(self.w.process)
        self.assertEqual(self.w.rows[0]["state"].text(), "Stopped")
        self.assertEqual(self.w.rows[1]["state"].text(), "Not run")
        self.mode("normal")
        self.run_queue()
        # An obsolete callback must not detach the replacement process.
        replacement = self.w.process
        self.w.worker_finished(old, -1, QProcess.ExitStatus.CrashExit)
        self.assertIs(self.w.process, replacement)
        self.until(lambda: not self.w.busy)
        self.assertEqual(self.w.overall.value(), 100)

    def test_failed_start_unlocks_without_finished_signal(self):
        with patch.object(gui.sys, "executable", str(self.root / "missing.exe")):
            self.run_queue()
            self.until(lambda: not self.w.busy)
        self.assertIsNone(self.w.process)
        self.assertEqual(self.w.rows[0]["state"].text(), "Failed")
        self.assertTrue(self.w.run_all.isEnabled())

    def test_render_failure_halts_pending_jobs(self):
        self.mode("fail")
        self.run_queue()
        self.until(lambda: not self.w.busy)
        self.assertEqual(self.w.rows[0]["state"].text(), "Failed")
        self.assertEqual(self.w.rows[1]["state"].text(), "Not run")
        self.assertIsNone(self.w.process)

    def test_shutdown_timeout_preserves_completed_jobs(self):
        worker = self.root / "reezsynth_shared_worker.py"
        worker.write_text(worker.read_text(encoding="utf-8").replace(
            'if action == "quit":', 'if action == "quit":\n                time.sleep(30)'), encoding="utf-8")
        self.w.shutdown_timer.setInterval(50)
        self.run_queue()
        self.until(lambda: self.w.session_closing)
        self.assertTrue(self.w.busy)
        self.until(lambda: not self.w.busy)
        self.assertIsNone(self.w.process)
        self.assertTrue(all(r["state"].text() == "Complete" for r in self.w.rows))
        self.assertIn("shutdown warning", self.w.status.text())

    def test_close_during_render_waits_for_exit(self):
        self.mode("slow")
        self.w.show()
        self.run_queue()
        self.until(lambda: "MOCK_STARTED" in self.w.log.toPlainText())
        with patch.object(gui.QMessageBox, "question", return_value=gui.QMessageBox.StandardButton.Yes):
            self.assertFalse(self.w.close())
        self.assertTrue(self.w.busy)
        self.until(lambda: not self.w.isVisible())
        self.assertIsNone(self.w.process)
        self.assertFalse(self.w.busy)

    def test_declining_close_keeps_queue_running(self):
        self.mode("slow")
        self.run_queue()
        self.until(lambda: "MOCK_STARTED" in self.w.log.toPlainText())
        with patch.object(gui.QMessageBox, "question", return_value=gui.QMessageBox.StandardButton.No):
            self.w.close()
        self.assertTrue(self.w.busy)
        self.assertFalse(self.w.cancelled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
