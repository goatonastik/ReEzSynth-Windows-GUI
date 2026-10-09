"""CPU-only recovery tests for the single-attempt ComfyUI job record."""

import hashlib
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from reezsynth_comfy_jobs import (
    claim_submission, load_job, prepare_job, record_receipt,
)


class ComfyJobTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "project"
        self.project.mkdir()
        self.key = self.project / "keys" / "frame_000011.png"
        self.key.parent.mkdir()
        self.key.write_bytes(b"original numbered key")
        self.key_hash = hashlib.sha256(self.key.read_bytes()).hexdigest()

    def prepare(self):
        return prepare_job(
            self.project, endpoint="http://127.0.0.1:8188",
            request={"prompt": {"1": {"class_type": "SaveImage", "inputs": {}}},
                     "mode": "modify", "frame": 11},
            snapshots={"drawing.png": b"frozen drawing", "edit_mask.png": b"frozen mask"},
        )

    def test_freeze_claim_and_recovery_never_claim_again(self):
        job = self.prepare()
        self.assertFalse(load_job(job.directory).attempted)
        wire = claim_submission(job.directory)
        self.assertEqual(json.loads(wire)["prompt_id"], job.prompt_id)
        self.assertEqual(json.loads(wire)["extra_data"]["reezsynth_job_id"], job.prompt_id)
        self.assertEqual(json.loads(wire)["extra_data"]["client_id"], job.client_id)
        self.assertTrue(load_job(job.directory).attempted)
        with self.assertRaises((ValueError, FileExistsError)):
            claim_submission(job.directory)
        self.assertEqual(self.key_hash, hashlib.sha256(self.key.read_bytes()).hexdigest())

    def test_uncertain_submission_stays_uncertain_after_lost_response(self):
        job = self.prepare()
        claim_submission(job.directory)
        recovered = load_job(job.directory)
        self.assertTrue(recovered.attempted)
        self.assertFalse(recovered.receipt_confirmed)
        with self.assertRaises((ValueError, FileExistsError)):
            claim_submission(recovered.directory)

    def test_two_controllers_can_claim_only_one_attempt(self):
        job = self.prepare()
        barrier = threading.Barrier(2)
        def attempt(_):
            barrier.wait(timeout=5)
            try:
                claim_submission(job.directory)
                return "claimed"
            except (ValueError, FileExistsError):
                return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, range(2)))
        self.assertCountEqual(outcomes, ["claimed", "rejected"])

    def test_changed_endpoint_in_manifest_blocks_claim(self):
        job = self.prepare()
        manifest_path = job.directory / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["endpoint"] = "http://127.0.0.1:9999"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ownership"):
            claim_submission(job.directory)
        self.assertFalse((job.directory / "attempted").exists())

    def test_reserved_windows_snapshot_name_is_rejected_early(self):
        with self.assertRaisesRegex(ValueError, "names"):
            prepare_job(self.project, endpoint="http://localhost:8188",
                        request={"prompt": {"1": {"class_type": "SaveImage", "inputs": {}}}},
                        snapshots={"nul.png": b"bytes"})
        self.assertFalse((self.project / ".reezsynth-candidates").exists())

    def test_empty_project_does_not_use_current_directory(self):
        with self.assertRaisesRegex(ValueError, "Select an existing project"):
            prepare_job("", endpoint="http://localhost:8188",
                        request={"prompt": {"1": {"class_type": "SaveImage", "inputs": {}}}},
                        snapshots={"drawing.png": b"bytes"})

    def test_interrupted_preparation_has_clear_recovery_error(self):
        job = self.prepare()
        (job.directory / "manifest.json").unlink()
        with self.assertRaisesRegex(ValueError, "preparation was interrupted"):
            load_job(job.directory)

    def test_manifest_size_checked_before_job_directory_creation(self):
        with self.assertRaisesRegex(ValueError, "manifest exceeds"):
            prepare_job(self.project, endpoint="http://localhost:8188",
                        request={"prompt": {"1": {"class_type": "SaveImage", "inputs": {}}},
                                 "large_metadata": "x" * (16 * 1024 * 1024 - 200)},
                        snapshots={"drawing.png": b"bytes"})
        self.assertFalse((self.project / ".reezsynth-candidates").exists())

    def test_mismatched_receipt_does_not_acknowledge(self):
        job = self.prepare()
        claim_submission(job.directory)
        with self.assertRaisesRegex(ValueError, "does not match"):
            record_receipt(job.directory, b'{"prompt_id":"another-job"}')
        self.assertFalse(load_job(job.directory).receipt_confirmed)
        confirmed = record_receipt(job.directory,
                                   json.dumps({"prompt_id": job.prompt_id, "number": 1}).encode())
        self.assertTrue(confirmed.receipt_confirmed)
        with self.assertRaises(ValueError):
            record_receipt(job.directory, json.dumps({"prompt_id": job.prompt_id}).encode())

    def test_changed_snapshot_blocks_claim(self):
        job = self.prepare()
        (job.directory / "inputs" / "drawing.png").write_bytes(b"changed drawing")
        with self.assertRaisesRegex(ValueError, "changed"):
            claim_submission(job.directory)
        self.assertFalse((job.directory / "attempted").exists())

    def test_changed_wire_body_blocks_claim(self):
        job = self.prepare()
        (job.directory / "submit.json").write_text('{"prompt":{}}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            claim_submission(job.directory)
        self.assertFalse((job.directory / "attempted").exists())

    def test_redirected_record_file_blocks_claim(self):
        job = self.prepare()
        external = self.project.parent / "elsewhere.json"
        external.write_bytes((job.directory / "submit.json").read_bytes())
        (job.directory / "submit.json").unlink()
        try:
            (job.directory / "submit.json").symlink_to(external)
        except OSError:
            self.skipTest("Creating Windows symlinks is not available.")
        with self.assertRaisesRegex(ValueError, "redirects"):
            claim_submission(job.directory)

    def test_redirected_candidate_root_is_rejected(self):
        external = self.project.parent / "external"
        external.mkdir()
        candidate = self.project / ".reezsynth-candidates"
        try:
            candidate.symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest("Creating Windows symlinks is not available.")
        with self.assertRaises(ValueError):
            self.prepare()


if __name__ == "__main__":
    unittest.main()
