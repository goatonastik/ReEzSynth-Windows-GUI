"""CPU-only plan/job binding tests; no backend or model is used."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from reezsynth_comfy_binding import bind_qwen_plan
from reezsynth_comfy_qwen import QwenPlan, QwenSettings, plan_qwen
from reezsynth_comfy_jobs import load_job
from reezsynth_keyframe_protection import AlphaPolicy, EditIntent


class BindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.source = np.full((17, 19, 4), 255, dtype=np.uint8)

    def plan(self):
        return plan_qwen(QwenSettings("generate", "Draw a bright scene", 4, 12, 4, 1,
                                      allow_vision_preprocessing=True), self.source)

    def test_binding_freezes_exact_plan_and_prevents_reuse(self):
        plan = self.plan()
        job = bind_qwen_plan(self.project, endpoint="http://localhost:8188", plan=plan)
        loaded = load_job(job.directory)
        self.assertEqual(loaded.prompt_id, job.prompt_id)
        self.assertFalse(loaded.attempted)
        manifest = json.loads((job.directory / "manifest.json").read_bytes())
        self.assertEqual(manifest["metadata"]["uploads"], dict(plan.uploads))
        body = json.loads((job.directory / "submit.json").read_bytes())
        self.assertEqual(body["prompt"], plan.request()["prompt"])
        with self.assertRaisesRegex(ValueError, "already bound"):
            bind_qwen_plan(self.project, endpoint="http://localhost:8188", plan=plan)
        self.assertNotEqual(dict(plan.uploads), dict(self.plan().uploads))

    def test_concurrent_binding_claims_one_plan(self):
        plan = self.plan()
        def bind(_):
            try:
                bind_qwen_plan(self.project, endpoint="http://localhost:8188", plan=plan)
                return "bound"
            except ValueError:
                return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(bind, range(2))), ["bound", "rejected"])

    def test_tampered_upload_name_rejected_before_claim(self):
        plan = self.plan()
        request = plan.request()
        request["uploads"]["inference.png"] = "wrong.png"
        altered = QwenPlan(json.dumps(request).encode(), plan.snapshots, plan.uploads)
        with self.assertRaisesRegex(ValueError, "inventory"):
            bind_qwen_plan(self.project, endpoint="http://localhost:8188", plan=altered)
        self.assertEqual(list(self.project.glob(".reezsynth-candidates/*")), [])

    def test_changed_settings_cannot_reuse_existing_upload_names(self):
        plan = self.plan()
        bind_qwen_plan(self.project, endpoint="http://localhost:8188", plan=plan)
        request = plan.request()
        request["prompt"]["14"]["inputs"]["seed"] += 1
        altered = QwenPlan(json.dumps(request).encode(), plan.snapshots, plan.uploads)
        with self.assertRaisesRegex(ValueError, "already bound"):
            bind_qwen_plan(self.project, endpoint="http://localhost:8188", plan=altered)

    def test_modify_binds_mask_and_rejects_cross_identity(self):
        drawing = self.source.copy()
        edit = np.full((17, 19), 255, dtype=np.uint8)
        protect = np.zeros_like(edit)
        plan = plan_qwen(QwenSettings("modify", "Refine", 4, 12, 4, 0.5,
                                      intent=EditIntent.REFINE_STROKES,
                                      alpha_policy=AlphaPolicy.PRESERVE,
                                      background=(255, 255, 255),
                                      allow_vision_preprocessing=True),
                         self.source, drawing=drawing, edit_mask=edit,
                         protection_mask=protect)
        request = plan.request()
        self.assertEqual(request["prompt"]["12"]["inputs"]["image"],
                         dict(plan.uploads)["noise_mask.png"])
        bind_qwen_plan(self.project, endpoint="http://localhost:8188", plan=plan)
        request["uploads"]["noise_mask.png"] = request["uploads"]["noise_mask.png"].replace(
            request["uploads"]["noise_mask.png"].split("_")[1], "a" * 32)
        request["prompt"]["12"]["inputs"]["image"] = request["uploads"]["noise_mask.png"]
        changed = QwenPlan(json.dumps(request).encode(), plan.snapshots,
                           tuple(request["uploads"].items()))
        with self.assertRaisesRegex(ValueError, "share one unique identity"):
            bind_qwen_plan(self.project, endpoint="http://localhost:8188", plan=changed)

    def test_malformed_plan_and_empty_project_rejected_without_claim(self):
        plan = self.plan()
        with self.assertRaisesRegex(ValueError, "Select an existing project"):
            bind_qwen_plan("", endpoint="http://localhost:8188", plan=plan)
        with self.assertRaisesRegex(ValueError, "Select an existing project"):
            bind_qwen_plan(self.project / "missing", endpoint="http://localhost:8188", plan=plan)
        bad_node = plan.request()
        bad_node["prompt"]["4"] = []
        with self.assertRaisesRegex(ValueError, "nodes"):
            bind_qwen_plan(self.project, endpoint="http://localhost:8188",
                           plan=QwenPlan(json.dumps(bad_node).encode(), plan.snapshots, plan.uploads))
        bad_bytes = QwenPlan(plan.request_bytes, (("source.png", None),), plan.uploads)
        with self.assertRaises(ValueError):
            bind_qwen_plan(self.project, endpoint="http://localhost:8188", plan=bad_bytes)
        self.assertEqual(list(self.project.glob(".reezsynth-candidates/*")), [])

    def test_invalid_endpoint_leaves_plan_available(self):
        plan = self.plan()
        with self.assertRaises(ValueError):
            bind_qwen_plan(self.project, endpoint="https://example.com", plan=plan)
        bind_qwen_plan(self.project, endpoint="http://localhost:8188", plan=plan)


if __name__ == "__main__":
    unittest.main()
