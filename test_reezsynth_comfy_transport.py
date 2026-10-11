"""Local fake-server tests for frozen uploads and single-attempt submission."""

import json
import re
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np

from reezsynth_comfy_binding import bind_qwen_plan
from reezsynth_comfy_jobs import load_job
from reezsynth_comfy_qwen import QwenSettings, plan_qwen
from reezsynth_comfy_qwen import QwenPlan
from reezsynth_comfy_transport import submit_uploaded_job, upload_job_inputs
from reezsynth_keyframe_protection import AlphaPolicy, EditIntent


class _FakeServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.images = {}
        self.upload_posts = 0
        self.prompts = []
        self.rename = False
        self.corrupt = False
        self.redirect = False
        self.lose_prompt_response = False


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, code, body, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.server.redirect:
            self.send_response(302)
            self.send_header("Location", "http://example.com/")
            self.end_headers()
            return
        content = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/upload/image":
            self.server.upload_posts += 1
            match = re.search(rb'filename="([a-z0-9_.]+\.png)"\r\n', content)
            if match is None:
                self.respond(400, b"{}")
                return
            name = match.group(1).decode("ascii")
            boundary = self.headers["Content-Type"].split("boundary=")[1].encode("ascii")
            payload = content.split(b"\r\n\r\n", 1)[1].split(b"\r\n--" + boundary, 1)[0]
            if self.server.rename or (name in self.server.images and self.server.images[name] != payload):
                name = name.removesuffix(".png") + " (1).png"
            self.server.images[name] = payload
            self.respond(200, json.dumps({"name": name, "subfolder": "", "type": "input"}).encode())
        elif self.path == "/prompt":
            body = json.loads(content)
            self.server.prompts.append(body)
            if self.server.lose_prompt_response:
                self.close_connection = True
                return
            self.respond(200, json.dumps({"prompt_id": body["prompt_id"], "number": 1}).encode())
        else:
            self.respond(404, b"{}")

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path != "/view":
            self.respond(404, b"{}")
            return
        name = parse_qs(parts.query).get("filename", [""])[0]
        if name not in self.server.images:
            self.respond(404, b"{}")
            return
        payload = self.server.images[name]
        if self.server.corrupt:
            payload = payload[:-1] + bytes([payload[-1] ^ 1])
        self.respond(200, payload, "image/png")


class TransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.server = _FakeServer()
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        source = np.full((17, 19, 4), 255, dtype=np.uint8)
        self.plan = plan_qwen(QwenSettings("generate", "Style this", 1, 12, 4, 1,
                                           allow_vision_preprocessing=True), source)
        self.job = bind_qwen_plan(self.project,
                                  endpoint=f"http://127.0.0.1:{self.server.server_port}",
                                  plan=self.plan)

    def test_upload_verify_submit_once_and_recover(self):
        upload_job_inputs(self.job.directory)
        upload_job_inputs(self.job.directory)
        self.assertEqual(self.server.upload_posts, 1)
        loaded = submit_uploaded_job(self.job.directory)
        self.assertTrue(loaded.receipt_confirmed)
        self.assertEqual(len(self.server.prompts), 1)
        self.assertEqual(self.server.prompts[0]["prompt_id"], self.job.prompt_id)
        with self.assertRaises(ValueError):
            submit_uploaded_job(self.job.directory)
        self.assertEqual(len(self.server.prompts), 1)

    def test_modify_requires_both_verified_uploads(self):
        drawing = np.full((17, 19, 4), 255, dtype=np.uint8)
        edit = np.full((17, 19), 255, dtype=np.uint8)
        protect = np.zeros_like(edit)
        plan = plan_qwen(QwenSettings("modify", "Refine lines", 2, 12, 4, 0.5,
                                      intent=EditIntent.REFINE_STROKES,
                                      alpha_policy=AlphaPolicy.PRESERVE,
                                      background=(255, 255, 255),
                                      allow_vision_preprocessing=True),
                         drawing, drawing=drawing, edit_mask=edit,
                         protection_mask=protect)
        job = bind_qwen_plan(self.project,
                            endpoint=f"http://127.0.0.1:{self.server.server_port}",
                            plan=plan)
        with self.assertRaisesRegex(ValueError, "Upload every input"):
            submit_uploaded_job(job.directory)
        upload_job_inputs(job.directory)
        self.assertEqual(self.server.upload_posts, 2)
        self.assertEqual(set(self.server.images), set(dict(plan.uploads).values()))
        (job.directory / "upload-noise_mask.json").unlink()
        with self.assertRaisesRegex(ValueError, "Upload every input"):
            submit_uploaded_job(job.directory)
        self.assertFalse(load_job(job.directory).attempted)
        upload_job_inputs(job.directory)
        self.assertEqual(self.server.upload_posts, 3)
        self.assertTrue(submit_uploaded_job(job.directory).receipt_confirmed)
        self.assertEqual(len(self.server.prompts), 1)

    def test_renamed_upload_is_rejected_before_submission(self):
        self.server.rename = True
        with self.assertRaisesRegex(ValueError, "renamed"):
            upload_job_inputs(self.job.directory)
        self.assertFalse(load_job(self.job.directory).attempted)
        self.assertEqual(self.server.prompts, [])

    def test_changed_server_bytes_are_rejected_before_claim(self):
        upload_job_inputs(self.job.directory)
        self.server.corrupt = True
        with self.assertRaisesRegex(ValueError, "differ"):
            submit_uploaded_job(self.job.directory)
        self.assertFalse(load_job(self.job.directory).attempted)

    def test_redirect_is_rejected_without_leaving_loopback(self):
        self.server.redirect = True
        with self.assertRaisesRegex(ValueError, "redirected"):
            upload_job_inputs(self.job.directory)
        self.assertEqual(self.server.prompts, [])

    def test_lost_prompt_response_never_retries(self):
        upload_job_inputs(self.job.directory)
        self.server.lose_prompt_response = True
        with self.assertRaises(Exception):
            submit_uploaded_job(self.job.directory)
        recovered = load_job(self.job.directory)
        self.assertTrue(recovered.attempted)
        self.assertFalse(recovered.receipt_confirmed)
        self.assertEqual(len(self.server.prompts), 1)
        self.server.lose_prompt_response = False
        with self.assertRaises(ValueError):
            submit_uploaded_job(self.job.directory)
        self.assertEqual(len(self.server.prompts), 1)

    def test_cross_project_different_bytes_same_name_cannot_submit(self):
        upload_job_inputs(self.job.directory)
        other = self.project / "other"
        other.mkdir()
        source = np.zeros((17, 19, 4), dtype=np.uint8)
        source[..., 3] = 255
        fresh = plan_qwen(QwenSettings("generate", "Style this", 1, 12, 4, 1,
                                       allow_vision_preprocessing=True), source)
        request = fresh.request()
        old_name = dict(self.plan.uploads)["inference.png"]
        request["uploads"]["inference.png"] = old_name
        request["prompt"]["4"]["inputs"]["image"] = old_name
        altered = QwenPlan(json.dumps(request).encode(), fresh.snapshots,
                           (("inference.png", old_name),))
        job = bind_qwen_plan(other,
                            endpoint=f"http://127.0.0.1:{self.server.server_port}",
                            plan=altered)
        with self.assertRaisesRegex(ValueError, "renamed"):
            upload_job_inputs(job.directory)
        self.assertFalse(load_job(job.directory).attempted)
        self.assertEqual(self.server.prompts, [])


if __name__ == "__main__":
    unittest.main()
