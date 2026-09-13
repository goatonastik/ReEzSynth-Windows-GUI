"""Real QProcess lifecycle tests with temporary scripts; no GPU rendering."""
import shutil
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QProcess
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy, QTest

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
    def test_recovery_during_maintenance_preserves_existing_queue(self):
        self.mode('slow')
        self.run_queue(shared=False)
        self.until(lambda: 'MOCK_STARTED' in self.w.log.toPlainText())
        journal = Path(self.w.preferences.value('last_queue_journal'))
        batch = self.w.batch
        output = self.w.current['output']
        self.w.stop_queue()
        self.until(lambda: not self.w.busy)
        (output / 'partial.png').write_bytes(b'preserve me')
        rows = list(self.w.rows)
        states = [row['state'].text() for row in rows]
        journal_before = journal.read_bytes()
        siblings_before = sorted(batch.glob(output.name + '_recovered*'))

        self.w.options.engine_action_pending = True
        try:
            with patch.object(gui.QFileDialog, 'getOpenFileName') as select, \
                 patch.object(gui.QMessageBox, 'information') as notice:
                self.w.recover_queue()
            notice.assert_called_once()
            select.assert_not_called()
        finally:
            self.w.options.engine_action_pending = False

        self.assertEqual(self.w.rows, rows)
        self.assertEqual([row['state'].text() for row in self.w.rows], states)
        self.assertEqual(self.w.table.rowCount(), len(rows))
        self.assertEqual(journal.read_bytes(), journal_before)
        self.assertEqual(sorted(batch.glob(output.name + '_recovered*')), siblings_before)
        self.assertFalse(self.w.busy)
        self.assertIsNone(self.w.process)

    def test_interrupted_queue_recovers_without_overwriting_partial_output(self):
        self.mode('slow')
        self.run_queue(shared=False)
        self.until(lambda: 'MOCK_STARTED' in self.w.log.toPlainText())
        journal = Path(self.w.preferences.value('last_queue_journal'))
        original_batch = self.w.batch
        original_output = self.w.current['output']
        self.w.stop_queue()
        self.until(lambda: not self.w.busy)
        self.w.show_recovery_notice()
        self.assertIn('unfinished queue', self.w.status.text())
        partial = original_output / 'partial.png'
        partial.write_bytes(b'preserve me')

        self.mode('normal')
        with patch.object(gui.QFileDialog, 'getOpenFileName', return_value=(str(journal), '')), \
             patch.object(gui.QMessageBox, 'question', return_value=gui.QMessageBox.StandardButton.Yes):
            self.w.recover_queue()
        self.until(lambda: not self.w.busy)

        self.assertEqual(partial.read_bytes(), b'preserve me')
        self.assertFalse((original_output / 'COMPLETE.txt').exists())
        recovered = [path for path in original_batch.glob(original_output.name + '_recovered*')
                     if (path / 'COMPLETE.txt').is_file()]
        self.assertEqual(len(recovered), 1)
        self.assertTrue(any((path / 'COMPLETE.txt').is_file()
                            for path in original_batch.iterdir() if path != original_output))
        from reezsynth_queue_recovery import audit_journal
        self.assertEqual(audit_journal(journal)['data']['state'], 'interrupted')
        recovery_journals = list(original_batch.glob('.reezsynth-queue-recovery-*.json'))
        self.assertEqual(len(recovery_journals), 1)
        self.assertEqual(audit_journal(recovery_journals[0])['data']['state'], 'complete')

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
            journal = self.w.batch / '.reezsynth-queue.json'
            self.until(lambda: not self.w.busy)
            self.assertIsNone(self.w.process)
            self.assertEqual(self.w.overall.value(), 100)
            self.assertTrue(all(r["state"].text() == "Complete" for r in self.w.rows))
            self.assertIn("Queue cleanup complete", self.w.log.toPlainText())
            from reezsynth_queue_recovery import audit_journal
            self.assertEqual(audit_journal(journal)['data']['state'], 'complete')
            self.assertFalse(self.w.preferences.value('last_queue_journal', '', type=str))

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
        journal = self.w.batch / '.reezsynth-queue.json'
        self.w.stop_queue()
        self.assertTrue(self.w.busy)
        self.assertFalse(self.w.run_all.isEnabled())
        self.until(lambda: not self.w.busy)
        self.assertIsNone(self.w.process)
        self.assertEqual(self.w.rows[0]["state"].text(), "Stopped")
        self.assertEqual(self.w.rows[1]["state"].text(), "Not run")
        from reezsynth_queue_recovery import audit_journal
        self.assertEqual(audit_journal(journal)['data']['state'], 'interrupted')
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


class AuditLifecycleTests(LifecycleFixture):
    def test_second_shared_running_journal_failure_finalizes_worker(self):
        from reezsynth_queue_recovery import audit_journal, update_journal
        running = []
        exits = []
        def update(path, job_path=None, state=None, **kwargs):
            if state == 'running':
                running.append(job_path)
                if len(running) == 2:
                    self.assertEqual(self.w.process.state(), QProcess.ProcessState.Running)
                    exits.append(QSignalSpy(self.w.process.finished))
                    raise OSError('second running update failed')
            return update_journal(path, job_path, state, **kwargs)
        with patch('reezsynth_queue_recovery.update_journal', side_effect=update):
            self.run_queue()
            journal = self.w.queue_journal
            self.until(lambda: not self.w.busy)
        self.assertEqual(len(running), 2)
        self.assertEqual(exits[0].count(), 1)
        self.assertIsNone(self.w.process)
        self.assertEqual([row['state'].text() for row in self.w.rows], ['Complete', 'Failed'])
        self.assertTrue(self.w.run_all.isEnabled())
        self.assertEqual(audit_journal(journal)['data']['state'], 'failed')

    def test_refused_deferred_close_restores_ui_without_unlocking_maintenance(self):
        self.mode('slow')
        self.w.show()
        options = self.w.options
        notice = self.enterContext(patch.object(gui.QMessageBox, 'information'))
        def finish_maintenance():
            process = getattr(options, 'engine_process', None)
            if process is not None:
                process.write(b'\n')
                process.closeWriteChannel()
                self.until(lambda: not options.installation_active())
        self.addCleanup(finish_maintenance)
        original = self.w.end_queue
        def end_then_maintain(message):
            original(message)  # Posts the deferred close, which has not run yet.
            options.start_engine_action('test maintenance', gui.sys.executable,
                                        ['-c', 'import sys; sys.stdin.readline()'])
        self.run_queue()
        self.until(lambda: 'MOCK_STARTED' in self.w.log.toPlainText())
        with patch.object(self.w, 'end_queue', side_effect=end_then_maintain), \
             patch.object(gui.QMessageBox, 'question', return_value=gui.QMessageBox.StandardButton.Yes):
            self.assertFalse(self.w.close())
            self.assertTrue(self.w.close_when_idle)
            self.until(lambda: notice.called)
        self.assertTrue(self.w.isVisible())
        self.assertFalse(self.w.busy)
        self.assertIsNone(self.w.process)
        self.assertFalse(self.w.close_when_idle)
        self.assertTrue(self.w.project_dir.isEnabled())
        self.assertTrue(options.installation_active())
        self.assertFalse(options.widgets['render']['engine'].isEnabled())
        self.assertTrue(all(not b.isEnabled() for b in options.engine_setup_buttons))
        finish_maintenance()
        self.assertTrue(options.widgets['render']['engine'].isEnabled())
        self.assertTrue(all(b.isEnabled() for b in options.engine_setup_buttons))
        self.assertTrue(self.w.run_all.isEnabled())

    def test_common_queue_start_refuses_active_component_maintenance(self):
        with patch.object(self.w.options, 'installation_active', return_value=True), \
             patch.object(gui.QMessageBox, 'information') as notice, \
             patch('reezsynth_queue_recovery.create_journal') as create:
            self.w.start_records([], self.root, True, False,
                                 self.root / 'reezsynth_shared_worker.py', {})
        notice.assert_called_once()
        create.assert_not_called()
        self.assertFalse(self.w.busy)
        self.assertIsNone(self.w.process)

    def exit_before_handshake(self, code):
        worker = self.root / 'reezsynth_shared_worker.py'
        text = (SOURCE / 'reezsynth_shared_worker.py').read_text(encoding='utf-8')
        worker.write_text(text.replace('            render_job(job_path)',
                          f'            render_job(job_path)\n            raise SystemExit({code})'), encoding='utf-8')

    def test_shared_exit_after_completion_preserves_job_and_halts_pending(self):
        from reezsynth_queue_recovery import audit_journal
        self.exit_before_handshake(7)
        self.run_queue()
        record = self.w.current
        journal = self.w.queue_journal
        exits = QSignalSpy(self.w.process.finished)
        self.until(lambda: not self.w.busy)
        self.assertEqual(exits.count(), 1)
        self.assertIsNone(self.w.process)
        self.assertEqual([row['state'].text() for row in self.w.rows], ['Complete', 'Not run'])
        self.assertEqual(self.w.completed_work, record['weight'])
        self.assertLess(self.w.overall.value(), 100)
        audited = audit_journal(journal)
        self.assertEqual(audited['data']['entries'][0]['state'], 'complete')
        self.assertEqual(audited['data']['state'], 'failed')
        self.assertTrue(audited['entries'][0]['complete'])
        self.assertIn('completion handshake', self.w.log.toPlainText())

    def test_protocol_failure_does_not_rescue_completion_marker(self):
        worker = self.root / 'reezsynth_shared_worker.py'
        text = worker.read_text(encoding='utf-8')
        worker.write_text(text.replace(
            'send_event("job_done", job=str(job_path))',
            'send_event("job_done", job=str(job_path.with_name("wrong-job.json")))'),
            encoding='utf-8')
        self.run_queue()
        output = self.w.current['output']
        self.until(lambda: not self.w.busy)
        self.assertTrue((output / 'COMPLETE.txt').is_file())
        self.assertIsNone(self.w.process)
        self.assertEqual([row['state'].text() for row in self.w.rows], ['Failed', 'Not run'])
        self.assertEqual(self.w.completed_work, 0)
        self.assertIn('unexpected job', self.w.log.toPlainText())

    def test_last_shared_job_with_marker_completes_with_shutdown_warning(self):
        from reezsynth_queue_recovery import audit_journal
        for code in (0, 7):
            with self.subTest(exit_code=code):
                self.exit_before_handshake(code)
                self.w.run_rows([self.w.rows[0]])
                journal = self.w.queue_journal
                self.until(lambda: not self.w.busy)
                self.assertIsNone(self.w.process)
                self.assertEqual(self.w.rows[0]['state'].text(), 'Complete')
                self.assertEqual(self.w.completed_work, self.w.total_work)
                self.assertEqual(self.w.overall.value(), 100)
                self.assertIn('shutdown warning', self.w.status.text())
                self.assertEqual(audit_journal(journal)['data']['state'], 'complete')

    def test_pending_storage_marker_is_not_committed_completion(self):
        self.exit_before_handshake(7)
        renderer = self.root / 'reezsynth_jobs.py'
        renderer.write_text(MOCK_RENDERER.replace('"COMPLETE.txt"', '".COMPLETE.storage-pending"'), encoding='utf-8')
        self.run_queue()
        output = self.w.current['output']
        self.until(lambda: not self.w.busy)
        self.assertIsNone(self.w.process)
        self.assertTrue((output / '.COMPLETE.storage-pending').is_file())
        self.assertFalse((output / 'COMPLETE.txt').exists())
        self.assertEqual([row['state'].text() for row in self.w.rows], ['Failed', 'Not run'])
        self.assertEqual(self.w.completed_work, 0)

    def test_explicit_cancellation_keeps_stopped_semantics_after_marker(self):
        worker = self.root / 'reezsynth_shared_worker.py'
        worker.write_text(worker.read_text(encoding='utf-8').replace('            render_job(job_path)',
            '            render_job(job_path)\n            print("COMMITTED_WAITING", flush=True)\n            time.sleep(30)'), encoding='utf-8')
        self.run_queue()
        output = self.w.current['output']
        self.until(lambda: 'COMMITTED_WAITING' in self.w.log.toPlainText())
        self.w.stop_queue()
        self.until(lambda: not self.w.busy)
        self.assertTrue((output / 'COMPLETE.txt').is_file())
        self.assertEqual(self.w.rows[0]['state'].text(), 'Stopped')
        self.assertEqual(self.w.completed_work, 0)
        self.assertIsNone(self.w.process)


if __name__ == "__main__":
    unittest.main(verbosity=2)
