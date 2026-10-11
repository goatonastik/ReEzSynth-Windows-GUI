"""Fake-server tests for owned output selection and native crop."""

import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from PIL import Image

from reezsynth_comfy_binding import bind_qwen_plan
from reezsynth_comfy_jobs import claim_submission, record_receipt
from reezsynth_comfy_output import fetch_owned_output
from reezsynth_comfy_qwen import QwenSettings, plan_qwen


class _Server(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.status = {}
        self.image = b""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/jobs/"):
            payload = json.dumps(self.server.status).encode()
            content_type = "application/json"
        elif path == "/view":
            payload = self.server.image
            content_type = "image/png"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class OutputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.server = _Server()
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"
        source = np.full((33, 19, 4), 255, dtype=np.uint8)
        self.plan = plan_qwen(QwenSettings("generate", "Draw", 1, 12, 4, 1,
                                           allow_vision_preprocessing=True), source)
        self.job = bind_qwen_plan(Path(temporary.name), endpoint=self.endpoint,
                                  plan=self.plan)
        claim_submission(self.job.directory)
        record_receipt(self.job.directory,
                       json.dumps({"prompt_id": self.job.prompt_id}).encode())
        prefix = self.plan.request()["prompt"]["16"]["inputs"]["filename_prefix"]
        self.filename = f"{prefix}_00001_.png"
        self.pixels = np.empty((48, 32, 3), dtype=np.uint8)
        self.pixels[..., 0] = np.arange(32, dtype=np.uint8)[None, :]
        self.pixels[..., 1] = np.arange(48, dtype=np.uint8)[:, None]
        self.pixels[..., 2] = 77
        self.save_png(self.pixels)
        self.server.status = {
            "id": self.job.prompt_id, "status": "completed",
            "workflow": {"extra_data": {
                "reezsynth_job_id": self.job.prompt_id,
                "client_id": self.job.client_id,
                "reezsynth_endpoint": self.endpoint}},
            "outputs": {"16": {"images": [{
                "filename": self.filename, "subfolder": "", "type": "output"}]}}
        }

    def save_png(self, pixels):
        stream = io.BytesIO()
        Image.fromarray(pixels).save(stream, format="PNG")
        self.server.image = stream.getvalue()

    def test_owned_output_crops_only_right_and_bottom_padding(self):
        output = fetch_owned_output(self.job.directory)
        self.assertEqual(output.prompt_id, self.job.prompt_id)
        self.assertEqual(output.filename, self.filename)
        np.testing.assert_array_equal(output.native_rgb, self.pixels[:33, :19])
        self.assertEqual(output.native_rgb.shape, (33, 19, 3))

    def test_wrong_owner_or_filename_rejected(self):
        self.server.status["workflow"]["extra_data"]["client_id"] = "another-client"
        with self.assertRaisesRegex(ValueError, "ownership"):
            fetch_owned_output(self.job.directory)
        self.server.status["workflow"]["extra_data"]["client_id"] = self.job.client_id
        self.server.status["outputs"]["16"]["images"][0]["filename"] = "someone_else.png"
        with self.assertRaisesRegex(ValueError, "unexpected output"):
            fetch_owned_output(self.job.directory)

    def test_wrong_size_or_multiple_outputs_rejected(self):
        self.save_png(self.pixels[:33, :19])
        with self.assertRaisesRegex(ValueError, "padded native size"):
            fetch_owned_output(self.job.directory)
        self.server.status["outputs"]["16"]["images"].append(dict(
            self.server.status["outputs"]["16"]["images"][0]))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            fetch_owned_output(self.job.directory)

    def test_corrupt_png_and_non_rgb_rejected(self):
        self.server.image = b"not a PNG"
        with self.assertRaisesRegex(ValueError, "damaged or incomplete"):
            fetch_owned_output(self.job.directory)
        self.save_png(self.pixels[..., 0])
        with self.assertRaisesRegex(ValueError, "RGB PNG"):
            fetch_owned_output(self.job.directory)


if __name__ == "__main__":
    unittest.main()
