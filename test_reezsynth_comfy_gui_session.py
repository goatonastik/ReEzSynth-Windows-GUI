"""Offscreen GUI admission and recovery tests; no model or live backend."""

import threading
import time
from unittest.mock import patch

from reezsynth_comfy_jobs import claim_submission, load_job, prepare_job
from reezsynth_comfy_session import ComfySession, SessionUpdate
from reezsynth_comfy_controls import _ImageWork, _submit_session_job
from reezsynth_comfy_status import JobObservation
from reezsynth_gpu_gate import GpuAdmission
from test_reezsynth_gui import GuiFixture
from test_reezsynth_lifecycle import LifecycleFixture


class ComfyGuiSessionTests(GuiFixture):
    def wait_for_worker(self, tab):
        deadline = time.monotonic() + 5
        while tab._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(tab._worker)

    def test_corrupt_startup_can_use_confirmed_render_only_without_resetting_record(self):
        import reezsynth_comfy_controls as controls
        path = self.root / "configuration" / "comfy-session.sqlite"
        path.parent.mkdir()
        path.write_bytes(b"damaged database")
        window = self.window()
        tab = window.comfy_tab
        self.assertIsNotNone(window.gpu_gate.owner)
        self.assertTrue(tab.session_render_only_button.isEnabled())
        self.assertIn(str(path), tab.session_status.text())
        with patch.object(controls.QMessageBox, "question", return_value=controls.QMessageBox.StandardButton.No) as ask:
            tab.use_rendering_only()
        self.assertEqual(ask.call_args.args[-1], controls.QMessageBox.StandardButton.No)
        self.assertIsNotNone(window.gpu_gate.owner)
        self.assertFalse(tab.session.render_only)
        with patch.object(controls.QMessageBox, "question", return_value=controls.QMessageBox.StandardButton.Yes):
            tab.use_rendering_only()
        self.wait_for_worker(tab)
        self.assertIsNone(window.gpu_gate.owner)
        self.assertTrue(tab.session.render_only)
        self.assertFalse(tab.session_submit_button.isEnabled())
        self.assertFalse(tab.session_refresh_button.isEnabled())
        self.assertFalse(tab.session_render_only_button.isEnabled())
        self.assertIn("Rendering-only mode", tab.session_status.text())
        self.assertEqual(path.read_bytes(), b"damaged database")
        with patch.object(tab.session, "submit") as submit:
            tab.start_generation()
            submit.assert_not_called()
        token = window.gpu_gate.acquire("render")
        window.gpu_gate.release(token)

    def test_terminal_refresh_releases_real_gate_for_reserved_not_selected_job(self):
        window = self.window()
        tab = window.comfy_tab
        project = self.root / "project"
        project.mkdir()
        job = prepare_job(project, endpoint="http://127.0.0.1:8188",
                          request={"prompt": {"1": {"class_type": "Fixture", "inputs": {}}}},
                          snapshots={"source.png": b"frozen source"})
        def accept(directory):
            claim_submission(directory)
            return load_job(directory)
        with patch("reezsynth_comfy_session.submit_uploaded_job", side_effect=accept):
            tab._show_session_update(tab.session.submit(job.directory, project))
        self.assertIsNotNone(window.gpu_gate.owner)
        tab.owned_job.setText("a different selected folder")
        with patch("reezsynth_comfy_session.fetch_job_status", return_value=JobObservation(
                job.prompt_id, "completed", True, True)) as status:
            tab.check_generation_status()
            self.wait_for_worker(tab)
        self.assertEqual(status.call_args.args[0].directory, job.directory)
        self.assertIsNone(window.gpu_gate.owner)
        self.assertIn("completed", tab.session_status.text())
        self.assertIn(str(job.directory), tab.session_status.text())
        self.assertFalse(tab.session_render_only_button.isEnabled())
        token = window.gpu_gate.acquire("render")
        window.gpu_gate.release(token)

    def test_worker_reports_system_exit_instead_of_orphaning_busy_state(self):
        for exception in (SystemExit("worker stopped"), ValueError()):
            with self.subTest(exception=type(exception).__name__):
                def exit_worker():
                    raise exception
                worker = _ImageWork(1, "session_refresh", exit_worker)
                result = []
                worker.signals.finished.connect(lambda *args: result.append(args))
                worker.run()
                self.assertEqual(len(result), 1)
                self.assertIn(type(exception).__name__, result[0][-1])

    def test_successful_submission_does_not_replace_receipt_with_second_read(self):
        directory = str(self.root / "prepared")
        session = ComfySession(self.root / "session.sqlite", GpuAdmission())
        accepted = SessionUpdate("unknown", directory)
        with patch.object(session, "submit", return_value=accepted) as submit, \
                patch.object(session, "restore") as restore:
            self.assertEqual(_submit_session_job(session, directory, self.root), (accepted, accepted))
        submit.assert_called_once()
        restore.assert_not_called()

    def test_failed_submission_keeps_blocked_recovery_error_visible(self):
        session = ComfySession(self.root / "session.sqlite", GpuAdmission())
        attempt = SessionUpdate("not_submitted", error="invalid new job")
        blocked = SessionUpdate("blocked", error="database unreadable")
        with patch.object(session, "submit", return_value=attempt), \
                patch.object(session, "restore", return_value=blocked):
            self.assertEqual(_submit_session_job(session, "new job", self.root), (attempt, blocked))

    def test_status_during_render_does_not_report_broken_recovery(self):
        window = self.window()
        token = window.gpu_gate.acquire("ReEzSynth rendering")
        with patch.object(window.comfy_tab.session, "refresh") as refresh:
            window.comfy_tab.check_generation_status()
            refresh.assert_not_called()
        self.assertIsNone(window.comfy_tab._worker)
        self.assertIn("ReEzSynth rendering", window.comfy_tab.session_status.text())
        self.assertNotIn("Recovery file", window.comfy_tab.session_status.text())
        window.gpu_gate.release(token)

    def test_recovery_block_identified_at_generation_preview_and_maintenance(self):
        import reezsynth_options
        from reezsynth_edge_preview import EdgePreviewWindow
        window = self.window()
        tab = window.comfy_tab
        tab.session.path.parent.mkdir(parents=True, exist_ok=True)
        tab.session.path.write_bytes(b"damaged")
        tab._show_session_update(tab.session.restore())
        tab.start_generation()
        self.assertIn("check generation status", tab.session_status.text())
        preview = EdgePreviewWindow(window.options)
        self.widgets.append(preview)
        with patch.object(preview, "request") as request:
            preview.update_preview()
            request.assert_not_called()
        self.assertIn("ComfyUI generation or recovery", preview.status.text())
        for action in (window.options.install_flowdiffuser_timm,
                       lambda: window.options.rebuild_engine_component("legacy"),
                       lambda: window.options.start_engine_action("test", "unused", [])):
            with patch.object(reezsynth_options.QMessageBox, "information") as info:
                action()
                info.assert_called_once()
                self.assertIn("check generation status", info.call_args.args[2])

    def test_blocked_status_does_not_name_previous_job(self):
        window = self.window()
        tab = window.comfy_tab
        prior = str(self.root / "previous-job")
        tab._show_session_update(SessionUpdate("completed", prior))
        tab._show_session_update(SessionUpdate("blocked", error="recovery file unreadable"))
        self.assertNotIn(prior, tab.session_status.text())
        self.assertIn("comfy-session.sqlite", tab.session_status.text())
        self.assertIn("recovery file unreadable", tab.session_status.text())

    def test_startup_restores_uncertain_job_before_render_can_start(self):
        project = self.root / "project"
        project.mkdir()
        job = prepare_job(project, endpoint="http://127.0.0.1:8188",
                          request={"prompt": {"1": {"class_type": "Fixture", "inputs": {}}}},
                          snapshots={"source.png": b"frozen source"})
        session = ComfySession(self.root / "configuration" / "comfy-session.sqlite", GpuAdmission())
        def lose_response(directory):
            claim_submission(directory)
            raise OSError("lost reply")
        with patch("reezsynth_comfy_session.submit_uploaded_job", side_effect=lose_response):
            self.assertEqual(session.submit(job.directory, project).status, "unknown")
        window = self.window()
        self.assertEqual(window.comfy_tab.session.path, session.path)
        self.assertIn(str(job.directory), window.comfy_tab.session_status.text())
        self.assertIsNotNone(window.gpu_gate.owner)
        window.run_rows([])
        self.assertFalse(window.busy)
        self.assertIn("ComfyUI", window.status.text())

    def test_active_render_prevents_generation_before_worker_dispatch(self):
        window = self.window()
        project = self.root / "project"
        project.mkdir()
        window.project_dir.setText(str(project))
        window.comfy_tab.owned_job.setText("prepared job")
        token = window.gpu_gate.acquire("render")
        with patch.object(window.comfy_tab.session, "submit") as submit:
            window.comfy_tab.start_generation()
            submit.assert_not_called()
        self.assertIn("Wait for render to finish", window.comfy_tab.session_status.text())
        window.gpu_gate.release(token)

    def test_pending_dispatch_blocks_render_maintenance_and_close(self):
        import reezsynth_options
        window = self.window()
        window.show()
        project = self.root / "project"
        project.mkdir()
        window.project_dir.setText(str(project))
        window.comfy_tab.owned_job.setText(str(project / "prepared-job"))
        window.options.auto_timer.stop()
        entered, release = threading.Event(), threading.Event()
        original = window.comfy_tab.owned_job.text()
        def delayed(*_):
            entered.set()
            release.wait(5)
            return SessionUpdate("unknown", original)
        with patch.object(window.comfy_tab.session, "submit", side_effect=delayed), \
                patch.object(window.comfy_tab.session, "restore", return_value=SessionUpdate("unknown", original)):
            window.comfy_tab.start_generation()
            try:
                self.assertTrue(entered.wait(3))
                self.assertTrue(window.comfy_tab.session_operation_pending())
                window.run_rows([])
                self.assertIn("current ComfyUI operation", window.status.text())
                with patch.object(reezsynth_options.QMessageBox, "information") as info:
                    window.options.start_engine_action("test", "unused", [])
                    info.assert_called_once()
                with patch.object(reezsynth_options.QMessageBox, "information") as info:
                    self.assertFalse(window.close())
                    info.assert_called_once()
                window.comfy_tab.owned_job.setText("another selection")
            finally:
                release.set()
                self.wait_for_worker(window.comfy_tab)
        self.assertIsNone(window.comfy_tab._worker)
        self.assertIn(original, window.comfy_tab.session_status.text())
        self.assertEqual(window.comfy_tab.owned_job.text(), "another selection")

    def test_failed_new_attempt_keeps_earlier_completed_status(self):
        window = self.window()
        project = self.root / "project"
        project.mkdir()
        window.project_dir.setText(str(project))
        window.comfy_tab.owned_job.setText("already attempted")
        earlier = str(project / "earlier-completed-job")
        with patch.object(window.comfy_tab.session, "submit", return_value=SessionUpdate(
                "not_submitted", error="This job has already been attempted")), \
                patch.object(window.comfy_tab.session, "restore", return_value=SessionUpdate(
                    "completed", earlier)):
            window.comfy_tab.start_generation()
            self.wait_for_worker(window.comfy_tab)
        status = window.comfy_tab.session_status.text()
        self.assertIn("completed", status)
        self.assertIn(earlier, status)
        self.assertIn("already been attempted", status)


class ComfyRenderLifecycleTests(LifecycleFixture):
    def test_pending_status_check_preserves_auto_trigger_before_gate_acquisition(self):
        tab = self.w.comfy_tab
        options = self.w.options
        options.auto_timer.stop()
        options.widgets['application']['auto_start'].setChecked(True)
        options.auto_armed = True
        entered, release = threading.Event(), threading.Event()
        def delayed_refresh():
            entered.set()
            release.wait(5)
            return SessionUpdate("idle")
        with patch.object(tab.session, 'refresh', side_effect=delayed_refresh):
            tab.check_generation_status()
            try:
                self.assertTrue(entered.wait(3))
                self.assertIsNone(self.w.gpu_gate.owner)
                self.assertTrue(tab.session_operation_pending())
                self.assertIn("ComfyUI", tab.gpu_wait_message())
                options.maybe_start()
                self.assertTrue(options.auto_armed)
                self.assertIsNone(options.last_auto)
                self.w.run_rows(list(self.w.rows))
                self.assertFalse(self.w.busy)
                self.assertIn("current ComfyUI operation", self.w.status.text())
                self.assertIn("ComfyUI", options.maintenance_wait_message())
            finally:
                release.set()
                self.until(lambda: tab._worker is None)
        self.assertFalse(tab.session_operation_pending())
        with patch.object(self.w, 'start_next'):
            options.maybe_start()
        self.assertFalse(options.auto_armed)
        self.assertIsNotNone(options.last_auto)
        self.assertTrue(self.w.busy)
        self.w.stop_queue()

    def test_automatic_render_waits_without_consuming_input_trigger(self):
        options = self.w.options
        options.auto_timer.stop()
        options.widgets['application']['auto_start'].setChecked(True)
        options.auto_armed = True
        token = self.w.gpu_gate.acquire("ComfyUI generation or recovery")
        options.maybe_start()
        self.assertTrue(options.auto_armed)
        self.assertIsNone(options.last_auto)
        self.assertTrue(options.auto_timer.isActive())
        self.assertFalse(self.w.busy)
        self.w.gpu_gate.release(token)
        with patch.object(self.w.comfy_tab, 'session_operation_pending', return_value=True):
            options.maybe_start()
        self.assertTrue(options.auto_armed)
        self.assertIsNone(options.last_auto)
        with patch.object(self.w, 'start_next'):
            options.maybe_start()
        self.assertFalse(options.auto_armed)
        self.assertIsNotNone(options.last_auto)
        self.assertTrue(self.w.busy)
        self.assertTrue(self.w.pending)
        self.w.stop_queue()

    def test_deferred_close_refusal_restores_controls_during_comfy_worker(self):
        import reezsynth_gui as gui
        self.mode('slow')
        self.w.show()
        release = threading.Event()
        notice = self.enterContext(patch.object(gui.QMessageBox, 'information'))
        original = self.w.end_queue
        def delayed():
            release.wait(5)
            return SessionUpdate("idle")
        def end_then_check(message):
            original(message)
            self.w.comfy_tab._start_work("session_refresh", delayed)
        self.run_queue()
        self.until(lambda: 'MOCK_STARTED' in self.w.log.toPlainText())
        try:
            with patch.object(self.w, 'end_queue', side_effect=end_then_check), \
                    patch.object(gui.QMessageBox, 'question', return_value=gui.QMessageBox.StandardButton.Yes):
                self.assertFalse(self.w.close())
                self.assertTrue(self.w.close_when_idle)
                self.until(lambda: notice.called)
            self.assertTrue(self.w.isVisible())
            self.assertFalse(self.w.close_when_idle)
            self.assertFalse(self.w.busy)
            self.assertTrue(self.w.project_dir.isEnabled())
        finally:
            release.set()
            self.until(lambda: self.w.comfy_tab._worker is None)


if __name__ == "__main__":
    import unittest
    unittest.main()
