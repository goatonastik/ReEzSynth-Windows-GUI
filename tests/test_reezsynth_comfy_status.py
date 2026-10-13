"""Read-only ComfyUI status parser and fake loopback-server tests."""

import json
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from reezsynth_comfy_jobs import claim_submission, prepare_job
from reezsynth_comfy_status import (
    MAX_STATUS_BYTES, JobObservation, fetch_job_status, parse_job_status,
    reconcile_observation,
)


class _StatusHandler(BaseHTTPRequestHandler):
    response_code = 200
    response_body = b"{}"
    response_location = None
    seen_paths = []

    def do_GET(self):
        type(self).seen_paths.append(self.path)
        self.send_response(type(self).response_code)
        if type(self).response_location:
            self.send_header("Location", type(self).response_location)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(type(self).response_body)
        except ConnectionResetError:
            pass

    def log_message(self, *_):
        pass


class StatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / "project"
        self.project.mkdir()
        self.job = prepare_job(
            self.project, endpoint="http://127.0.0.1:1",
            request={"prompt": {"1": {"class_type": "SaveImage", "inputs": {}}}},
            snapshots={"drawing.png": b"frozen drawing"},
        )
        claim_submission(self.job.directory)
        self.job = replace(self.job, attempted=True)

    def payload(self, status, *, own=True, outputs=None):
        data = {"id": self.job.prompt_id, "status": status}
        if status in {"completed", "failed", "cancelled"}:
            data["workflow"] = {"extra_data": {
                "reezsynth_job_id": self.job.prompt_id if own else "foreign",
                "client_id": self.job.client_id,
                "reezsynth_endpoint": self.job.endpoint,
            }}
            data["outputs"] = {} if outputs is None else outputs
        return json.dumps(data).encode()

    def test_pending_and_running_are_unverified_nonterminal_observations(self):
        self.assertEqual(parse_job_status(self.job, self.payload("pending")),
                         JobObservation(self.job.prompt_id, "pending", False, False))
        self.assertEqual(parse_job_status(self.job, self.payload("in_progress")),
                         JobObservation(self.job.prompt_id, "in_progress", False, False))

    def test_terminal_requires_matching_server_history_identity(self):
        with self.assertRaisesRegex(ValueError, "ownership"):
            parse_job_status(self.job, self.payload("completed", own=False))
        with self.assertRaisesRegex(ValueError, "different job"):
            parse_job_status(self.job, b'{"id":"foreign","status":"completed"}')
        self.assertEqual(parse_job_status(self.job, self.payload(
            "completed", outputs={"2": {"images": [{"filename": "x.png"}]}})),
            JobObservation(self.job.prompt_id, "completed", True, True))

    def test_missing_or_stale_observations_do_not_regress_running_job(self):
        running = JobObservation(self.job.prompt_id, "in_progress", False, False)
        self.assertEqual(reconcile_observation(running, JobObservation(self.job.prompt_id, "unknown", False, False)), running)
        self.assertEqual(reconcile_observation(running, JobObservation(self.job.prompt_id, "pending", False, False)), running)
        completed = JobObservation(self.job.prompt_id, "completed", True, True)
        self.assertEqual(reconcile_observation(running, completed), completed)
        self.assertEqual(reconcile_observation(completed, running), completed)
        with self.assertRaisesRegex(ValueError, "Contradictory"):
            reconcile_observation(completed, JobObservation(self.job.prompt_id, "failed", True, False))

    def test_terminal_outputs_can_appear_later_without_status_conflict(self):
        early = JobObservation(self.job.prompt_id, "completed", True, False)
        later = JobObservation(self.job.prompt_id, "completed", True, True)
        self.assertEqual(reconcile_observation(early, later), later)
        self.assertEqual(reconcile_observation(later, early), later)

    def test_observations_for_different_jobs_cannot_mix(self):
        prior = JobObservation(self.job.prompt_id, "pending", False, False)
        with self.assertRaisesRegex(ValueError, "different jobs"):
            reconcile_observation(prior, JobObservation("foreign", "completed", True, True))

    def test_unverified_terminal_is_never_accepted(self):
        with self.assertRaisesRegex(ValueError, "ownership"):
            reconcile_observation(None, JobObservation(self.job.prompt_id, "completed", False, True))

    def test_invalid_or_oversized_response_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "too large"):
            parse_job_status(self.job, b"x" * (MAX_STATUS_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "invalid number"):
            parse_job_status(self.job, b'{"id":"x","status":NaN}')
        with self.assertRaisesRegex(ValueError, "unknown job status"):
            parse_job_status(self.job, json.dumps({
                "id": self.job.prompt_id, "status": "unrecognized"
            }).encode())

    def test_nonloopback_and_unsubmitted_are_refused_before_network(self):
        with self.assertRaisesRegex(ValueError, "Only a ComfyUI server"):
            fetch_job_status(replace(self.job, endpoint="http://example.com:8188"))
        with self.assertRaisesRegex(ValueError, "not been submitted"):
            fetch_job_status(replace(self.job, attempted=False))

    def test_fake_server_terminal_response_verifies_our_ownership(self):
        _StatusHandler.response_code = 200
        _StatusHandler.response_location = None
        server = ThreadingHTTPServer(("127.0.0.1", 0), _StatusHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            job = replace(self.job, endpoint=f"http://127.0.0.1:{server.server_port}")
            payload = json.loads(self.payload("completed", outputs={"2": {"images": [
                {"filename": "candidate.png", "type": "output", "subfolder": ""}]}}))
            payload["workflow"]["extra_data"]["reezsynth_endpoint"] = job.endpoint
            _StatusHandler.response_body = json.dumps(payload).encode()
            self.assertEqual(fetch_job_status(job),
                             JobObservation(job.prompt_id, "completed", True, True))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_fake_server_scopes_get_to_our_id_and_treats_404_as_unknown(self):
        _StatusHandler.response_code = 200
        _StatusHandler.response_body = self.payload("pending")
        _StatusHandler.response_location = None
        _StatusHandler.seen_paths = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _StatusHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            job = replace(self.job, endpoint=f"http://127.0.0.1:{server.server_port}")
            self.assertEqual(fetch_job_status(job).status, "pending")
            self.assertEqual(_StatusHandler.seen_paths,
                             [f"/api/jobs/{self.job.prompt_id}"])
            _StatusHandler.response_code = 404
            self.assertEqual(fetch_job_status(job).status, "unknown")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_fake_server_redirect_is_rejected(self):
        _StatusHandler.response_code = 302
        _StatusHandler.response_body = b""
        _StatusHandler.response_location = "http://example.com/other"
        _StatusHandler.seen_paths = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _StatusHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            job = replace(self.job, endpoint=f"http://127.0.0.1:{server.server_port}")
            with self.assertRaisesRegex(ValueError, "redirected"):
                fetch_job_status(job)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
