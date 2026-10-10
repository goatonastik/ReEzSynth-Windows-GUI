"""CPU-only contracts for the offline experimental Qwen planner."""
from dataclasses import replace
from io import BytesIO
import hashlib
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from reezsynth_comfy_jobs import prepare_job, load_job
from reezsynth_comfy_qwen import QwenSettings, plan_qwen
from reezsynth_keyframe_protection import AlphaPolicy, EditIntent


class QwenPlanTests(unittest.TestCase):
    def setUp(self):
        self.source = np.full((17,19,4),255,dtype=np.uint8)
        self.drawing = self.source.copy()
        self.drawing[..., :3] = (20,30,40)
        self.edit = np.full((17,19),255,dtype=np.uint8)
        self.protect = np.zeros((17,19),dtype=np.uint8)
        self.settings = QwenSettings(
            mode="modify", prompt="Clean up the specified strokes.", seed=42,
            steps=20, guidance=4, denoise=0.5, intent=EditIntent.REFINE_STROKES,
            alpha_policy=AlphaPolicy.PRESERVE, background=(255,255,255),
            allow_vision_preprocessing=True,
        )

    def plan(self, settings=None):
        return plan_qwen(settings or self.settings,self.source,drawing=self.drawing,
                         edit_mask=self.edit,protection_mask=self.protect)

    def image(self, plan, name):
        with Image.open(BytesIO(dict(plan.snapshots)[name])) as image:
            return np.array(image)

    def test_native_padding_retains_pixels_and_original_rgba(self):
        self.drawing[0,0] = (123,45,67,0)
        self.drawing[1,1] = (0,0,0,128)
        original = self.drawing.copy()
        plan = self.plan()
        self.assertEqual(plan.request()["padded_size"],[32,32])
        self.assertEqual(plan.request()["padding_right_bottom"],[13,15])
        rgb = self.image(plan,"inference.png")
        self.assertEqual(rgb.shape,(32,32,3))
        np.testing.assert_array_equal(rgb[2:17,:19],original[2:17,:,:3])
        np.testing.assert_array_equal(rgb[0,0],[255,255,255])
        np.testing.assert_array_equal(rgb[1,1],[127,127,127])
        np.testing.assert_array_equal(rgb[-1,-1],rgb[16,18])
        np.testing.assert_array_equal(self.image(plan,"drawing.png"),original)
        np.testing.assert_array_equal(self.drawing,original)

    def test_noise_mask_obeys_protection_alpha_and_padding(self):
        self.protect[5,5] = 1
        self.edit[10,10] = 80
        self.drawing[0,0,3] = 0
        plan = self.plan(replace(self.settings,protection_radius=1))
        mask_rgb = self.image(plan,"noise_mask.png")
        self.assertEqual(mask_rgb.shape,(32,32,3))
        np.testing.assert_array_equal(mask_rgb[...,0],mask_rgb[...,1])
        np.testing.assert_array_equal(mask_rgb[...,0],mask_rgb[...,2])
        mask = mask_rgb[...,0]
        self.assertFalse(mask[4:7,4:7].any())
        self.assertEqual(mask[10,10],80)
        self.assertEqual(mask[0,0],0)
        self.assertFalse(mask[17:,:].any())
        self.assertFalse(mask[:,19:].any())
        self.assertEqual(mask[8,8],255)

    def test_no_op_is_rejected_before_any_workflow(self):
        for case in ("empty","protected","invisible"):
            with self.subTest(case=case):
                self.setUp()
                if case == "empty": self.edit[:] = 0
                elif case == "protected": self.protect[:] = 1
                else: self.drawing[...,3] = 0
                with self.assertRaisesRegex(ValueError,"unnecessary"):
                    self.plan()

    def test_graph_keeps_separate_native_reference_and_mask(self):
        graph = self.plan().request()["prompt"]
        for number in ("6","7"):
            self.assertNotIn("vae",graph[number]["inputs"])
            self.assertEqual(graph[number]["inputs"]["image1"],["4",0])
        for number in ("8","9"):
            self.assertEqual(graph[number]["inputs"]["latent"],["5",0])
        self.assertEqual(graph["14"]["inputs"]["latent_image"],["13",0])
        self.assertEqual(graph["12"]["inputs"]["channel"],"red")
        self.assertFalse(any("Scale" in node["class_type"] for node in graph.values()))

    def test_generate_has_source_authority_and_no_restoration(self):
        settings = QwenSettings("generate","Use a watercolor style",0,20,4,1,
                                allow_vision_preprocessing=True)
        plan = plan_qwen(settings,self.source)
        graph = plan.request()["prompt"]
        self.assertEqual(graph["14"]["inputs"]["latent_image"],["5",0])
        self.assertNotIn("noise_mask.png",dict(plan.snapshots))
        self.assertNotIn("drawing.png",dict(plan.snapshots))
        with self.assertRaisesRegex(ValueError,"restoration"):
            plan_qwen(settings,self.source,drawing=self.drawing)
        with self.assertRaisesRegex(ValueError,"full denoise"):
            plan_qwen(replace(settings,denoise=0.5),self.source)
        self.source[0,0,3] = 0
        with self.assertRaisesRegex(ValueError,"opaque"):
            plan_qwen(settings,self.source)

    def test_settings_reject_silent_or_unsupported_behavior(self):
        changes = [dict(allow_vision_preprocessing=False),dict(allow_vision_preprocessing=1),
                   dict(alpha_policy=AlphaPolicy.EDIT),dict(background=None),
                   dict(background=(255,255,256)),dict(seed=True),dict(seed=-1),
                   dict(steps=0),dict(denoise=0),dict(guidance=float("nan")),
                   dict(prompt=" "),dict(intent=None),dict(intent="custom"),
                   dict(protection_radius=1.5),dict(protection_radius=65)]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.plan(replace(self.settings,**change))

    def test_all_three_intentions_map_to_explicit_prompts(self):
        prompts = set()
        for intent in EditIntent:
            plan = self.plan(replace(self.settings,intent=intent))
            prompt = plan.request()["prompt"]["6"]["inputs"]["prompt"]
            self.assertIn(self.settings.prompt,prompt)
            prompts.add(prompt)
            self.assertEqual(plan.request()["intent"],intent.value)
        self.assertEqual(len(prompts),3)

    def test_wrong_size_or_color_masks_are_rejected(self):
        self.edit = np.zeros((17,19,3),dtype=np.uint8)
        with self.assertRaisesRegex(ValueError,"native dimensions"):
            self.plan()
        self.setUp()
        self.drawing = self.drawing[:16]
        with self.assertRaisesRegex(ValueError,"native dimensions"):
            self.plan()

    def test_padded_size_limit_rejects_instead_of_resizing(self):
        with patch("reezsynth_comfy_qwen.MAX_PIXELS",400):
            with self.assertRaisesRegex(ValueError,"Padded canvas"):
                self.plan()

    def test_native_size_limit_rejects_before_padding(self):
        with patch("reezsynth_comfy_qwen.MAX_PIXELS",300):
            with self.assertRaisesRegex(ValueError,"Image exceeds"):
                self.plan()

    def test_snapshot_and_request_are_independent_of_ui_changes(self):
        plan = self.plan()
        original = plan.request_bytes
        self.drawing[:] = 0
        self.edit[:] = 0
        request = plan.request()
        request["prompt"].clear()
        self.assertEqual(plan.request_bytes,original)
        self.assertTrue(plan.request()["prompt"])
        for name,data in plan.snapshots:
            self.assertEqual(hashlib.sha256(data).hexdigest(),plan.request()["snapshot_sha256"][name])

    def test_names_are_unique_and_job_record_can_freeze_plan(self):
        first, second = self.plan(), self.plan()
        self.assertFalse(set(dict(first.uploads).values()) & set(dict(second.uploads).values()))
        with tempfile.TemporaryDirectory() as project:
            job = prepare_job(project,endpoint="http://127.0.0.1:8188",
                              request=first.request(),snapshots=dict(first.snapshots))
            self.assertFalse(load_job(job.directory).attempted)


if __name__ == "__main__":
    unittest.main()
