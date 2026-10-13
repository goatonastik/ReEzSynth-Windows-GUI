"""CPU-only preparation of new frozen jobs from native tab inputs."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from reezsynth_comfy_prepare import PrepareJobRequest, prepare_qwen_job
from reezsynth_keyframe_protection import AlphaPolicy, EditIntent


class PrepareTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "project"
        self.project.mkdir()
        self.source = self.project / "source.png"
        Image.fromarray(np.full((17, 19, 4), 255, dtype=np.uint8)).save(self.source)
        self.request = PrepareJobRequest(
            project=str(self.project), endpoint="http://127.0.0.1:8188",
            intended_frame_number=97, mode="generate", source_path=str(self.source),
            drawing_path="", edit_mask_path="", protection_mask_path="",
            prompt="Draw in pencil", seed=42, steps=20, guidance=4, denoise=1,
            intent=None, alpha_policy=None, background=None, protection_radius=0,
            allow_vision_preprocessing=True,
        )

    def test_generate_freezes_native_source_and_frame_without_submission(self):
        job = prepare_qwen_job(self.request)
        manifest = json.loads((job.directory / "manifest.json").read_bytes())
        body = json.loads((job.directory / "submit.json").read_bytes())
        self.assertEqual(manifest["metadata"]["intended_frame_number"], 97)
        self.assertEqual(manifest["metadata"]["native_size"], [19, 17])
        self.assertEqual(manifest["metadata"]["padded_size"], [32, 32])
        self.assertEqual(body["prompt"]["14"]["inputs"]["seed"], 42)
        self.assertFalse((job.directory / "attempted").exists())
        self.assertFalse((job.directory / "receipt.json").exists())

    def test_modify_freezes_original_alpha_and_both_masks(self):
        drawing = self.project / "drawing.png"
        pixels = np.full((17, 19, 4), 100, dtype=np.uint8)
        pixels[..., 3] = 128
        Image.fromarray(pixels).save(drawing)
        edit = self.project / "edit.png"
        protect = self.project / "protect.png"
        Image.fromarray(np.full((17, 19), 255, dtype=np.uint8)).save(edit)
        Image.fromarray(np.zeros((17, 19), dtype=np.uint8)).save(protect)
        job = prepare_qwen_job(replace(
            self.request, mode="modify", drawing_path=str(drawing),
            edit_mask_path=str(edit), protection_mask_path=str(protect),
            intent=EditIntent.REGION_DETAIL.value,
            alpha_policy=AlphaPolicy.PRESERVE.value,
            background=(255, 255, 255), denoise=.5))
        manifest = json.loads((job.directory / "manifest.json").read_bytes())
        self.assertEqual(set(manifest["input_sha256"]), {
            "source.png", "drawing.png", "edit.png", "protection.png",
            "inference.png", "noise_mask.png"})
        with Image.open(job.directory / "inputs" / "drawing.png") as frozen:
            np.testing.assert_array_equal(np.array(frozen), pixels)
        self.assertFalse(job.attempted)

    def test_invalid_acknowledgement_or_size_leaves_no_job(self):
        with self.assertRaisesRegex(ValueError, "Acknowledge"):
            prepare_qwen_job(replace(self.request, allow_vision_preprocessing=False))
        self.assertFalse((self.project / ".reezsynth-candidates").exists())
        wrong = self.project / "wrong.png"
        Image.fromarray(np.zeros((16, 19), dtype=np.uint8)).save(wrong)
        with self.assertRaisesRegex(ValueError, "native dimensions"):
            prepare_qwen_job(replace(
                self.request, mode="modify", drawing_path=str(self.source),
                edit_mask_path=str(wrong), protection_mask_path=str(wrong),
                intent=EditIntent.REFINE_STROKES.value,
                alpha_policy=AlphaPolicy.PRESERVE.value,
                background=(255, 255, 255), denoise=.5))
        self.assertFalse((self.project / ".reezsynth-candidates").exists())


if __name__ == "__main__":
    unittest.main()
