"""CPU-only durable admission, interrupted-send and restart recovery tests."""

import json
import multiprocessing
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from reezsynth_comfy_jobs import claim_submission, load_job, prepare_job
from reezsynth_comfy_session import ComfySession
from reezsynth_comfy_status import JobObservation
from reezsynth_gpu_gate import GpuAdmission, GpuBusy
from tests.test_reezsynth_comfy_transport import _FakeServer, _Handler


class _SessionHandler(_Handler):
    def do_GET(self):
        if self.path.startswith("/api/jobs/") and self.server.prompts:
            body = self.server.prompts[-1]
            if self.path != "/api/jobs/" + body["prompt_id"] or not self.server.completed:
                self.respond(404, b"{}")
            else:
                self.respond(200, json.dumps({
                    "id": body["prompt_id"], "status": "completed",
                    "workflow": {"extra_data": body["extra_data"]}, "outputs": {},
                }).encode())
        else:
            super().do_GET()


def _interrupted_sender(state_path, directory, project, ready):
    def paused_send(path):
        claim_submission(path)
        ready.set()
        threading.Event().wait(30)
        return load_job(path)
    with patch("reezsynth_comfy_session.submit_uploaded_job", side_effect=paused_send):
        ComfySession(state_path, GpuAdmission()).submit(directory, project)


class SessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.job = prepare_job(self.project, endpoint="http://127.0.0.1:8188",
                               request={"prompt": {"1": {"class_type": "Fixture", "inputs": {}}}},
                               snapshots={"source.png": b"frozen test input"})
        self.path = self.root / "application" / "comfy-session.sqlite"
        self.gate = GpuAdmission()
        self.session = ComfySession(self.path, self.gate)

    def accept(self, directory):
        claim_submission(directory)
        return load_job(directory)

    def start(self):
        with patch("reezsynth_comfy_session.submit_uploaded_job", side_effect=self.accept):
            return self.session.submit(self.job.directory, self.project)

    def test_reservation_committed_before_prompt_and_blocks_rendering(self):
        def inspect_and_accept(directory):
            with closing(sqlite3.connect(self.path)) as connection:
                record = json.loads(connection.execute("SELECT payload FROM session").fetchone()[0])
            self.assertEqual(record["resolution"], "active")
            self.assertEqual(record["prompt_id"], self.job.prompt_id)
            with self.assertRaises(GpuBusy):
                self.gate.acquire("render")
            return self.accept(directory)
        with patch("reezsynth_comfy_session.submit_uploaded_job", side_effect=inspect_and_accept) as submit:
            self.assertEqual(self.session.submit(self.job.directory, self.project).status, "unknown")
            self.session.submit(self.job.directory, self.project)
            self.assertEqual(submit.call_count, 1)
        self.assertIsNotNone(self.gate.owner)

    def test_preflight_failure_without_attempt_releases_admission(self):
        with patch("reezsynth_comfy_session.submit_uploaded_job", side_effect=ValueError("Missing model")):
            update = self.session.submit(self.job.directory, self.project)
        self.assertEqual(update.status, "not_submitted")
        self.assertIn("Missing model", update.error)
        self.assertFalse(load_job(self.job.directory).attempted)
        self.assertIsNone(self.gate.owner)
        self.assertEqual(self.session.restore().status, "not_submitted")

    def test_lost_reply_survives_restart_and_missing_status_never_resubmits(self):
        def lost(directory):
            claim_submission(directory)
            raise OSError("reply lost")
        with patch("reezsynth_comfy_session.submit_uploaded_job", side_effect=lost) as submit:
            update = self.session.submit(self.job.directory, self.project)
            self.assertEqual(update.status, "unknown")
            restarted_gate = GpuAdmission()
            restarted = ComfySession(self.path, restarted_gate)
            self.assertEqual(restarted.restore().status, "unknown")
            with patch("reezsynth_comfy_session.fetch_job_status", return_value=JobObservation(
                    self.job.prompt_id, "unknown", False, False)):
                self.assertEqual(restarted.refresh().status, "unknown")
            restarted.submit(self.job.directory, self.project)
            self.assertEqual(submit.call_count, 1)
            self.assertIsNotNone(restarted_gate.owner)

    def test_verified_terminal_is_persisted_before_releasing_gate(self):
        self.start()
        with patch("reezsynth_comfy_session.fetch_job_status", return_value=JobObservation(
                self.job.prompt_id, "completed", True, True)):
            self.assertEqual(self.session.refresh().status, "completed")
        self.assertIsNone(self.gate.owner)
        restarted_gate = GpuAdmission()
        with patch("reezsynth_comfy_session.fetch_job_status") as status:
            self.assertEqual(ComfySession(self.path, restarted_gate).restore().status, "completed")
            status.assert_not_called()
        self.assertIsNone(restarted_gate.owner)
        with patch("reezsynth_comfy_session.submit_uploaded_job") as submit:
            result = self.session.submit(self.job.directory, self.project)
            self.assertEqual(result.status, "not_submitted")
            submit.assert_not_called()

    def test_unverified_terminal_and_network_error_hold_reservation(self):
        self.start()
        with patch("reezsynth_comfy_session.fetch_job_status", return_value=JobObservation(
                self.job.prompt_id, "completed", False, True)):
            self.assertEqual(self.session.refresh().status, "blocked")
        with patch("reezsynth_comfy_session.fetch_job_status", side_effect=OSError("offline")):
            self.assertEqual(self.session.refresh().status, "blocked")
        self.assertIsNotNone(self.gate.owner)
        self.assertEqual(self.session.restore().status, "unknown")

    def test_stale_status_cannot_regress_running_job_across_restart(self):
        self.start()
        with patch("reezsynth_comfy_session.fetch_job_status", return_value=JobObservation(
                self.job.prompt_id, "in_progress", False, False)):
            self.assertEqual(self.session.refresh().status, "in_progress")
        restarted = ComfySession(self.path, GpuAdmission())
        self.assertEqual(restarted.restore().status, "in_progress")
        with patch("reezsynth_comfy_session.fetch_job_status", return_value=JobObservation(
                self.job.prompt_id, "pending", False, False)):
            self.assertEqual(restarted.refresh().status, "in_progress")

    def test_restart_before_attempt_can_resolve_without_network(self):
        with patch.object(self.session, "_send_reserved", side_effect=SystemExit("crash")):
            with self.assertRaises(SystemExit):
                self.session.submit(self.job.directory, self.project)
        gate = GpuAdmission()
        restarted = ComfySession(self.path, gate)
        self.assertEqual(restarted.restore().status, "unknown")
        with patch("reezsynth_comfy_session.fetch_job_status") as fetch:
            self.assertEqual(restarted.refresh().status, "not_submitted")
            fetch.assert_not_called()
        self.assertIsNone(gate.owner)

    def test_recovery_between_reservation_and_send_prevents_delayed_post(self):
        original = self.session._send_reserved
        other = ComfySession(self.path, GpuAdmission())
        def race(record):
            self.assertEqual(other.refresh().status, "not_submitted")
            return original(record)
        with patch.object(self.session, "_send_reserved", side_effect=race), \
                patch("reezsynth_comfy_session.submit_uploaded_job") as submit:
            self.assertEqual(self.session.submit(self.job.directory, self.project).status, "not_submitted")
            submit.assert_not_called()
        self.assertIsNone(self.gate.owner)

    def test_recovery_cannot_clear_reservation_during_inflight_send(self):
        entered, release = threading.Event(), threading.Event()
        def delayed(directory):
            entered.set()
            release.wait(5)
            return self.accept(directory)
        updates = []
        with patch("reezsynth_comfy_session.submit_uploaded_job", side_effect=delayed):
            thread = threading.Thread(target=lambda: updates.append(self.session.submit(self.job.directory, self.project)))
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                other = ComfySession(self.path, GpuAdmission())
                self.assertEqual(other.refresh().status, "blocked")
                self.assertIsNotNone(other.gate.owner)
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(updates[0].status, "unknown")
        self.assertTrue(load_job(self.job.directory).attempted)

    def test_terminated_sender_leaves_durable_uncertainty_and_releases_database_lock(self):
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        process = context.Process(target=_interrupted_sender,
                                  args=(self.path, self.job.directory, self.project, ready))
        process.start()
        try:
            self.assertTrue(ready.wait(10))
        finally:
            process.terminate()
            process.join(10)
        self.assertFalse(process.is_alive())
        self.assertEqual(self.session.restore().status, "unknown")
        self.assertTrue(load_job(self.job.directory).attempted)
        with patch("reezsynth_comfy_session.fetch_job_status", return_value=JobObservation(
                self.job.prompt_id, "unknown", False, False)):
            self.assertEqual(self.session.refresh().status, "unknown")
        self.assertIsNotNone(self.gate.owner)

    def test_other_project_and_busy_render_reject_before_submission(self):
        with patch("reezsynth_comfy_session.submit_uploaded_job") as submit:
            self.assertEqual(self.session.submit(self.job.directory, self.root).status, "not_submitted")
            self.assertIsNone(self.gate.owner)
            token = self.gate.acquire("render")
            self.assertEqual(self.session.submit(self.job.directory, self.project).status, "blocked")
            self.assertEqual(self.gate.owner, "render")
            submit.assert_not_called()
            self.gate.release(token)

    def test_unreadable_job_or_database_fails_closed(self):
        self.start()
        (self.job.directory / "submit.json").write_bytes(b"changed")
        self.assertEqual(self.session.refresh().status, "blocked")
        self.assertIsNotNone(self.gate.owner)
        self.path.write_bytes(b"invalid sqlite database")
        restarted = ComfySession(self.path, GpuAdmission())
        self.assertEqual(restarted.restore().status, "blocked")
        self.assertIsNotNone(restarted.gate.owner)

    def test_corrupt_database_render_only_keeps_evidence_and_restart_guard(self):
        self.start()
        self.path.write_bytes(b"invalid sqlite database")
        evidence = self.path.read_bytes()
        restarted = ComfySession(self.path, GpuAdmission())
        self.assertEqual(restarted.restore().status, "blocked")
        self.assertTrue(restarted.can_enter_render_only)
        self.assertEqual(restarted.enter_render_only().status, "blocked")
        self.assertIsNotNone(restarted.gate.owner)
        self.assertFalse(restarted.render_only)
        self.assertEqual(restarted.enter_render_only(confirmed_idle=True).status, "render_only")
        self.assertIsNone(restarted.gate.owner)
        self.assertFalse(restarted.can_enter_render_only)
        with patch.object(restarted, "_transaction", side_effect=AssertionError("Must not read/write recovery")), \
                patch("reezsynth_comfy_session.submit_uploaded_job") as submit, \
                patch("reezsynth_comfy_session.fetch_job_status") as status:
            self.assertEqual(restarted.submit(self.job.directory, self.project).status, "render_only")
            self.assertEqual(restarted.refresh().status, "render_only")
            self.assertEqual(restarted.restore().status, "render_only")
            submit.assert_not_called()
            status.assert_not_called()
        self.assertEqual(self.path.read_bytes(), evidence)
        self.assertTrue(load_job(self.job.directory).attempted)
        again = ComfySession(self.path, GpuAdmission())
        self.assertEqual(again.restore().status, "blocked")
        self.assertIsNotNone(again.gate.owner)

    def test_render_only_preserves_valid_uncertainty_and_cannot_free_other_owner(self):
        self.start()
        evidence = self.path.read_bytes()
        self.assertEqual(self.session.enter_render_only(confirmed_idle=True).status, "render_only")
        self.assertEqual(self.path.read_bytes(), evidence)
        self.assertTrue(load_job(self.job.directory).attempted)
        token = self.gate.acquire("render")
        self.assertEqual(self.session.refresh().status, "render_only")
        self.assertEqual(self.session.enter_render_only(confirmed_idle=True).status, "render_only")
        self.assertEqual(self.gate.owner, "render")
        self.gate.release(token)
        fresh = ComfySession(self.path, GpuAdmission())
        self.assertEqual(fresh.restore().status, "unknown")
        self.assertIsNotNone(fresh.gate.owner)

    def test_render_only_refuses_during_sender_and_never_waits_for_new_job(self):
        entered, release = threading.Event(), threading.Event()
        def sending(directory):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Test release timed out")
            return self.accept(directory)
        with patch("reezsynth_comfy_session.submit_uploaded_job", side_effect=sending):
            thread = threading.Thread(target=self.session.submit, args=(self.job.directory, self.project))
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(self.session.enter_render_only(confirmed_idle=True).status, "blocked")
                self.assertFalse(self.session.render_only)
                self.assertIsNotNone(self.gate.owner)
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertIsNotNone(self.gate.owner)

    def test_render_only_without_owned_recovery_cannot_release_render(self):
        token = self.gate.acquire("render")
        self.assertEqual(self.session.enter_render_only(confirmed_idle=True).status, "blocked")
        self.assertFalse(self.session.render_only)
        self.assertEqual(self.gate.owner, "render")
        self.gate.release(token)

    def test_missing_database_or_record_cannot_release_known_reservation(self):
        self.start()
        saved_database = self.path.read_bytes()
        self.path.unlink()
        self.assertEqual(self.session.refresh().status, "blocked")
        self.assertFalse(self.path.exists())
        self.assertIsNotNone(self.gate.owner)
        self.path.write_bytes(saved_database)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DELETE FROM session")
            connection.commit()
        self.assertEqual(self.session.restore().status, "blocked")
        self.assertIsNotNone(self.gate.owner)
        with patch("reezsynth_comfy_session.submit_uploaded_job") as submit:
            self.assertEqual(self.session.submit(self.job.directory, self.project).status, "blocked")
            submit.assert_not_called()

    def test_real_transport_lost_reply_reconciles_via_owned_fake_server_history(self):
        import numpy as np
        from reezsynth_comfy_binding import bind_qwen_plan
        from reezsynth_comfy_qwen import QwenSettings, plan_qwen
        from reezsynth_comfy_transport import upload_job_inputs
        server = _FakeServer()
        server.RequestHandlerClass = _SessionHandler
        server.completed = False
        server.lose_prompt_response = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        plan = plan_qwen(QwenSettings("generate", "Pencil drawing", 42, 12, 4, 1,
                                      allow_vision_preprocessing=True),
                         np.full((17, 19, 4), 255, dtype=np.uint8))
        job = bind_qwen_plan(self.project, endpoint=f"http://127.0.0.1:{server.server_port}", plan=plan)
        upload_job_inputs(job.directory)
        # Schema validation has dedicated server tests; all other transport
        # and normalized job-status requests here use the actual HTTP helpers.
        with patch("reezsynth_comfy_preflight.preflight_graph", return_value=19):
            self.assertEqual(self.session.submit(job.directory, self.project).status, "unknown")
        self.assertTrue(load_job(job.directory).attempted)
        self.assertFalse(load_job(job.directory).receipt_confirmed)
        restarted_gate = GpuAdmission()
        restarted = ComfySession(self.path, restarted_gate)
        self.assertEqual(restarted.restore().status, "unknown")
        self.assertEqual(restarted.refresh().status, "unknown")
        restarted.submit(job.directory, self.project)
        self.assertEqual(len(server.prompts), 1)
        server.completed = True
        self.assertEqual(restarted.refresh().status, "completed")
        self.assertIsNone(restarted_gate.owner)
        self.assertFalse(load_job(job.directory).receipt_confirmed)


if __name__ == "__main__":
    unittest.main()
