"""Fake-server tests for owned output selection and native crop."""

import io
import hashlib
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from PIL import Image

from reezsynth_comfy_binding import bind_qwen_plan
from reezsynth_comfy_jobs import claim_submission, record_receipt
from reezsynth_comfy_output import fetch_owned_output
from reezsynth_comfy_qwen import QwenSettings, plan_qwen
from reezsynth_comfy_candidate import prepare_job_candidate, save_job_candidate
from reezsynth_comfy_approval import load_candidate_review, approve_candidate, reject_candidate
from reezsynth_keyframe_protection import AlphaPolicy, EditIntent, protection_band


class _Server(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.status = {}
        self.image = b""
        self.missing_job = False


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/jobs/"):
            if self.server.missing_job:
                self.send_error(404)
                return
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
                                  plan=self.plan, intended_frame_number=97)
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

    def test_lost_receipt_recovers_only_verified_completed_job(self):
        receipt = self.job.directory / "receipt.json"
        receipt.unlink()
        attempt = self.job.directory / "attempted"
        original_attempt = attempt.read_bytes()
        output = fetch_owned_output(self.job.directory)
        self.assertEqual(output.prompt_id, self.job.prompt_id)
        self.assertFalse(receipt.exists())
        self.assertEqual(attempt.read_bytes(), original_attempt)
        with self.assertRaisesRegex(ValueError, "already have been submitted"):
            claim_submission(self.job.directory)
        result = prepare_job_candidate(self.job.directory)
        self.assertEqual(result.prompt_id, self.job.prompt_id)

    def test_lost_receipt_rejects_unverified_or_unfinished_job(self):
        (self.job.directory / "receipt.json").unlink()
        self.server.status["status"] = "pending"
        with self.assertRaisesRegex(ValueError, "completed job"):
            fetch_owned_output(self.job.directory)
        self.server.status["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "completed job"):
            fetch_owned_output(self.job.directory)
        self.server.status["status"] = "completed"
        self.server.status["workflow"]["extra_data"]["client_id"] = "other"
        with self.assertRaisesRegex(ValueError, "ownership"):
            fetch_owned_output(self.job.directory)
        self.assertFalse((self.job.directory / "receipt.json").exists())

    def test_unattempted_job_does_not_fetch_result(self):
        (self.job.directory / "receipt.json").unlink()
        (self.job.directory / "attempted").unlink()
        with self.assertRaisesRegex(ValueError, "no submission attempt"):
            fetch_owned_output(self.job.directory)

    def test_lost_receipt_unknown_server_record_stays_uncertain(self):
        (self.job.directory / "receipt.json").unlink()
        self.server.missing_job = True
        with self.assertRaisesRegex(ValueError, "remains uncertain"):
            fetch_owned_output(self.job.directory)
        self.assertTrue((self.job.directory / "attempted").exists())
        with self.assertRaisesRegex(ValueError, "already have been submitted"):
            claim_submission(self.job.directory)

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

    def test_generate_candidate_is_opaque_native_and_read_only(self):
        before = sorted(str(p) for p in self.job.directory.rglob("*"))
        result = prepare_job_candidate(self.job.directory)
        with Image.open(io.BytesIO(result.image_png)) as image:
            pixels = np.array(image)
        np.testing.assert_array_equal(pixels[..., :3], self.pixels[:33, :19])
        self.assertTrue(np.all(pixels[..., 3] == 255))
        self.assertIsNone(result.matte_report)
        self.assertEqual(json.loads(result.provenance_json)["status"], "unreviewed")
        provenance = json.loads(result.provenance_json)
        self.assertEqual(provenance["candidate_sha256"], hashlib.sha256(result.image_png).hexdigest())
        self.assertEqual(provenance["prompt_id"], self.job.prompt_id)
        self.assertEqual((provenance["width"], provenance["height"]), (19, 33))
        self.assertEqual(provenance["manifest_sha256"], hashlib.sha256(
            (self.job.directory / "manifest.json").read_bytes()).hexdigest())
        self.assertEqual(before, sorted(str(p) for p in self.job.directory.rglob("*")))

    def test_save_owned_candidate_preserves_raw_and_stays_unassigned(self):
        preview = prepare_job_candidate(self.job.directory)
        saved = save_job_candidate(self.job.directory, preview)
        self.assertEqual(saved.image_path.read_bytes(), preview.image_png)
        self.assertEqual((saved.image_path.parent / "raw-output.png").read_bytes(),
                         self.server.image)
        self.assertEqual((saved.image_path.parent / "provenance.json").read_bytes(),
                         preview.provenance_json)
        record = json.loads(saved.metadata_path.read_bytes())
        self.assertEqual(record["status"], "unreviewed")
        self.assertIsNone(record["frame_number"])
        self.assertEqual(record["intended_frame_number"], 97)
        self.assertEqual(json.loads(preview.provenance_json)["intended_frame_number"], 97)
        self.assertEqual(record["candidate_sha256"], hashlib.sha256(preview.image_png).hexdigest())
        self.assertEqual(record["raw_output_sha256"], hashlib.sha256(self.server.image).hexdigest())
        self.assertIsNone(record["qc"])

    def test_approval_records_exact_saved_image_and_frame_without_assigning_key(self):
        saved = save_job_candidate(self.job.directory, prepare_job_candidate(self.job.directory))
        key = saved.image_path.parent.parent.parent / "keys" / "kling97.png"
        key.parent.mkdir()
        key.write_bytes(b"existing numbered key")
        original = key.read_bytes()
        review = load_candidate_review(saved.image_path.parent.parent.parent,
                                       saved.image_path.parent, 97)
        self.assertEqual(review.image_png, saved.image_path.read_bytes())
        approval = approve_candidate(review)
        marker = json.loads(approval.read_bytes())
        self.assertEqual(marker["status"], "approved_unassigned")
        self.assertEqual(marker["frame_number"], 97)
        self.assertEqual(marker["candidate_sha256"], hashlib.sha256(review.image_png).hexdigest())
        self.assertEqual(key.read_bytes(), original)
        self.assertEqual(json.loads(saved.metadata_path.read_bytes())["status"], "unreviewed")
        reopened = load_candidate_review(saved.image_path.parent.parent.parent,
                                         saved.image_path.parent, 97)
        self.assertTrue(reopened.approved)
        with self.assertRaisesRegex(ValueError, "review decision"):
            approve_candidate(review)

    def test_rejection_records_exact_image_without_changing_candidate_or_key(self):
        saved = save_job_candidate(self.job.directory, prepare_job_candidate(self.job.directory))
        project = saved.image_path.parent.parent.parent
        key = project / "keys" / "kling97.png"
        key.parent.mkdir()
        key.write_bytes(b"existing numbered key")
        original = key.read_bytes()
        review = load_candidate_review(project, saved.image_path.parent, 97)
        rejection = reject_candidate(review)
        self.assertEqual(json.loads(rejection.read_bytes())["candidate_sha256"], review.image_sha256)
        self.assertTrue(load_candidate_review(project, saved.image_path.parent, 97).rejected)
        self.assertEqual(saved.image_path.read_bytes(), review.image_png)
        self.assertEqual(key.read_bytes(), original)
        self.assertFalse((saved.image_path.parent / "approval.json").exists())
        with self.assertRaisesRegex(ValueError, "review decision"):
            approve_candidate(review)

    def test_rejection_fails_closed_on_stale_review_and_interrupted_decision(self):
        saved = save_job_candidate(self.job.directory, prepare_job_candidate(self.job.directory))
        project = saved.image_path.parent.parent.parent
        review = load_candidate_review(project, saved.image_path.parent, 97)
        saved.image_path.write_bytes(saved.image_path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "saved bytes"):
            reject_candidate(review)
        self.assertFalse((saved.image_path.parent / "rejection.json").exists())
        saved.image_path.write_bytes(review.image_png)
        (saved.image_path.parent / ".review-decision").mkdir()
        with self.assertRaisesRegex(ValueError, "interrupted"):
            load_candidate_review(project, saved.image_path.parent, 97)

    def test_approval_rejects_stale_image_and_wrong_project_or_frame(self):
        saved = save_job_candidate(self.job.directory, prepare_job_candidate(self.job.directory))
        project = saved.image_path.parent.parent.parent
        directory = saved.image_path.parent
        review = load_candidate_review(project, directory, 97)
        with self.assertRaisesRegex(ValueError, "frame"):
            load_candidate_review(project, directory, 98)
        other = project / "other-project"
        other.mkdir()
        with self.assertRaisesRegex(ValueError, "selected project"):
            load_candidate_review(other, directory, 97)
        original = saved.image_path.read_bytes()
        saved.image_path.write_bytes(original + b"changed")
        with self.assertRaisesRegex(ValueError, "saved bytes"):
            approve_candidate(review)
        self.assertFalse((directory / "approval.json").exists())

    def test_approval_rejects_changed_manifest_and_redirected_candidate(self):
        saved = save_job_candidate(self.job.directory, prepare_job_candidate(self.job.directory))
        project = saved.image_path.parent.parent.parent
        review = load_candidate_review(project, saved.image_path.parent, 97)
        manifest = self.job.directory / "manifest.json"
        manifest.write_bytes(manifest.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "provenance"):
            approve_candidate(review)
        redirect = project / ".reezsynth-candidates" / "comfy-preview-redirect"
        try:
            redirect.symlink_to(saved.image_path.parent, target_is_directory=True)
        except OSError:
            return  # Windows accounts without symlink privilege.
        with self.assertRaisesRegex(ValueError, "selected project"):
            load_candidate_review(project, redirect, 97)

    def test_interrupted_approval_marker_is_not_accepted_or_overwritten(self):
        saved = save_job_candidate(self.job.directory, prepare_job_candidate(self.job.directory))
        review = load_candidate_review(saved.image_path.parent.parent.parent,
                                       saved.image_path.parent, 97)
        marker = saved.image_path.parent / "approval.json"
        marker.write_bytes(b'{"schema":')  # A crash after exclusive create.
        with self.assertRaisesRegex(ValueError, "approval marker"):
            approve_candidate(review)
        self.assertEqual(marker.read_bytes(), b'{"schema":')

    def test_older_job_approval_binds_explicit_selected_frame(self):
        self.modify_job()
        saved = save_job_candidate(self.job.directory, prepare_job_candidate(self.job.directory))
        project = saved.image_path.parent.parent.parent
        with self.assertRaisesRegex(ValueError, "frame"):
            load_candidate_review(project, saved.image_path.parent)
        review = load_candidate_review(project, saved.image_path.parent, 7)
        self.assertEqual(review.frame_number, 7)
        marker = json.loads(approve_candidate(review).read_bytes())
        self.assertEqual(marker["frame_number"], 7)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            load_candidate_review(project, saved.image_path.parent, 8)

    def test_save_rejects_mutated_preview_or_changed_job(self):
        from dataclasses import replace
        preview = prepare_job_candidate(self.job.directory)
        forged = json.loads(preview.provenance_json)
        forged["intended_frame_number"] = 98
        with self.assertRaisesRegex(ValueError, "frozen job"):
            save_job_candidate(self.job.directory, replace(
                preview, provenance_json=json.dumps(forged).encode()))
        with self.assertRaisesRegex(ValueError, "image bytes"):
            save_job_candidate(self.job.directory, replace(preview, image_png=b"changed"))
        with self.assertRaisesRegex(ValueError, "image bytes"):
            save_job_candidate(self.job.directory, replace(preview, raw_output_png=b"changed"))
        manifest = self.job.directory / "manifest.json"
        manifest.write_bytes(manifest.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "frozen job"):
            save_job_candidate(self.job.directory, preview)
        self.assertEqual(list(self.job.directory.parent.glob("comfy-preview-*")), [])

    def test_interrupted_save_removes_only_new_incomplete_candidate(self):
        preview = prepare_job_candidate(self.job.directory)
        from reezsynth_comfy_candidate import _write_exclusive
        def fail_raw(path, content):
            if path.name == "raw-output.png":
                raise OSError("disk full")
            return _write_exclusive(path, content)
        with patch("reezsynth_comfy_candidate._write_exclusive", side_effect=fail_raw):
            with self.assertRaisesRegex(OSError, "disk full"):
                save_job_candidate(self.job.directory, preview)
        self.assertEqual(list(self.job.directory.parent.glob("comfy-preview-*")), [])

    def modify_job(self):
        drawing = np.full((33, 19, 4), 100, dtype=np.uint8)
        drawing[..., 3] = np.arange(33, dtype=np.uint8)[:, None] * 7
        drawing[0, :, :3] = 231  # hidden RGB must survive
        edit = np.full((33, 19), 255, dtype=np.uint8)
        edit[:, 12:] = 128
        protected = np.zeros((33, 19), dtype=np.uint8)
        protected[10, 5] = 255
        plan = plan_qwen(QwenSettings(
            "modify", "Shade", 1, 12, 4, .5, intent=EditIntent.REGION_DETAIL,
            alpha_policy=AlphaPolicy.PRESERVE, background=(255, 255, 255),
            protection_radius=2, allow_vision_preprocessing=True),
            np.full_like(drawing, 255), drawing=drawing,
            edit_mask=edit, protection_mask=protected)
        self.job = bind_qwen_plan(self.job.directory.parent.parent,
                                  endpoint=self.endpoint, plan=plan)
        claim_submission(self.job.directory)
        record_receipt(self.job.directory, json.dumps({"prompt_id": self.job.prompt_id}).encode())
        self.server.status["id"] = self.job.prompt_id
        self.server.status["workflow"]["extra_data"].update(
            reezsynth_job_id=self.job.prompt_id, client_id=self.job.client_id)
        prefix = plan.request()["prompt"]["16"]["inputs"]["filename_prefix"]
        self.server.status["outputs"]["16"]["images"][0]["filename"] = prefix + "_00001_.png"
        self.server.image = dict(plan.snapshots)["inference.png"]
        return drawing, edit, protected

    def test_modify_identity_preserves_every_original_byte(self):
        drawing, _, _ = self.modify_job()
        result = prepare_job_candidate(self.job.directory)
        with Image.open(io.BytesIO(result.image_png)) as image:
            np.testing.assert_array_equal(np.array(image), drawing)
        self.assertEqual(result.matte_report.clipped_reconstruction_pixels, 0)
        saved = save_job_candidate(self.job.directory, result)
        record = json.loads(saved.metadata_path.read_bytes())
        self.assertIsNone(record["frame_number"])
        self.assertIsNone(record["intended_frame_number"])
        self.assertEqual(record["qc"]["protection"]["protected_mismatches"], 0)

    def test_modify_enforces_band_alpha_hidden_rgb_and_reports_clipping(self):
        drawing, _, protected = self.modify_job()
        self.save_png(np.full((48, 32, 3), 255, dtype=np.uint8))
        result = prepare_job_candidate(self.job.directory)
        with Image.open(io.BytesIO(result.image_png)) as image:
            pixels = np.array(image)
        band = protection_band(protected, 2) > 0
        np.testing.assert_array_equal(pixels[band], drawing[band])
        np.testing.assert_array_equal(pixels[..., 3], drawing[..., 3])
        np.testing.assert_array_equal(pixels[0], drawing[0])
        self.assertTrue(np.any(pixels[20, 0, :3] != drawing[20, 0, :3]))
        self.assertGreater(result.matte_report.clipped_reconstruction_pixels, 0)
        self.assertEqual(result.matte_report.protection.protected_mismatches, 0)

    def test_candidate_rejects_changed_snapshot_and_inflight_metadata(self):
        path = self.job.directory / "inputs" / "source.png"
        original = path.read_bytes()
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "snapshot has changed"):
            prepare_job_candidate(self.job.directory)
        path.write_bytes(original)
        def changed(directory, **kwargs):
            output = fetch_owned_output(directory, **kwargs)
            manifest = self.job.directory / "manifest.json"
            manifest.write_bytes(manifest.read_bytes() + b" ")
            return output
        with patch("reezsynth_comfy_candidate.fetch_owned_output", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "plan changed"):
                prepare_job_candidate(self.job.directory)

    def test_candidate_rejects_changed_protection_radius(self):
        self.modify_job()
        path = self.job.directory / "manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["metadata"]["protection_radius"] = 0
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inference mask"):
            prepare_job_candidate(self.job.directory)

    def test_candidate_rejects_snapshot_changed_during_download(self):
        def changed(directory, **kwargs):
            output = fetch_owned_output(directory, **kwargs)
            (self.job.directory / "inputs" / "source.png").write_bytes(b"changed")
            return output
        with patch("reezsynth_comfy_candidate.fetch_owned_output", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "snapshot has changed"):
                prepare_job_candidate(self.job.directory)

    def test_candidate_rejects_malformed_metadata(self):
        path = self.job.directory / "manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["metadata"] = []
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "metadata is invalid"):
            prepare_job_candidate(self.job.directory)


if __name__ == "__main__":
    unittest.main()
