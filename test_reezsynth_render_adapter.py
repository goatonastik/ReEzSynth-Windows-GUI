"""Exercise the real renderer adapter with a fake engine; no torch/GPU imports."""
import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from reezsynth_config import PREVIEW, STANDARD, WEIGHTS
from reezsynth_jobs import render_job


class RenderAdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="reezsynth_adapter_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(patch.dict(os.environ))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.frames = []
        for i in range(2):
            path = self.root / f"frame{i:03d}.png"
            path.write_bytes(cv2.imencode(".png", np.full((128, 128, 3), 40, np.uint8))[1].tobytes())
            self.frames.append([i, str(path)])
        style = self.root / "style.png"
        style.write_bytes(cv2.imencode(".png", np.full((128, 128, 3), 200, np.uint8))[1].tobytes())
        output = self.root / "out"
        output.mkdir()
        self.job = dict(key=0, style=str(style), frames=self.frames, output=str(output),
                        padding=3, quality="Preview", max_width=0)
        self.output = output

    def run_job(self):
        path = self.root / "job.json"
        path.write_text(json.dumps(self.job), encoding="utf-8")
        render_job(path)

    def fake_engine(self):
        captured = {}
        class Config:
            def __init__(self, **kwargs):
                captured["config"] = kwargs
        class Engine:
            def __init__(self, **kwargs):
                captured["engine"] = kwargs
                self.frames = kwargs["img_frs_seq"]
                self.eb = types.SimpleNamespace(backends={"cuda": 17}, backend=None, run=lambda: None)
                captured["runner"] = self
            def run_sequences(self):
                for _ in self.frames[1:]:
                    self.eb.run()
                return self.frames, None
        self.enterContext(patch.dict(sys.modules, {
            "torch": types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True, get_device_name=lambda _: "mock")),
            "ezsynth.aux_classes": types.SimpleNamespace(RunConfig=Config),
            "ezsynth.main_ez": types.SimpleNamespace(EzsynthBase=Engine),
        }))
        return captured

    def test_legacy_jobs_preserve_preview_and_standard_parameters(self):
        captured = self.fake_engine()
        for quality, expected in (("Preview", PREVIEW), ("Standard", STANDARD)):
            self.job["quality"] = quality
            self.run_job()
            for name, value in {**expected, **WEIGHTS}.items():
                if name in ('key_wgt', 'mask_wgt'):
                    continue  # Adapter-level controls, not RunConfig keywords.
                self.assertEqual(captured["config"][name], value)
            self.assertEqual(captured["engine"]["raft_flow_model_name"], "sintel")
            self.assertEqual(captured["runner"].eb.backend, 17)
            self.assertFalse(captured["engine"]["do_mask"])
        self.assertTrue((self.output / "COMPLETE.txt").exists())

    def test_custom_controls_and_grayscale_masks_reach_engine(self):
        captured = self.fake_engine()
        mask = self.root / "mask.png"
        mask.write_bytes(cv2.imencode(".png", np.full((128, 128), 255, np.uint8))[1].tobytes())
        self.job["masks"] = [[i, str(mask)] for i in range(2)]
        self.job["render_options"] = dict(uniformity=4567.0, edge_method="PAGE", do_mask=True, pre_mask=True, feather=5)
        self.job["guide_weights"] = dict(img_wgt=9.0)
        self.run_job()
        self.assertEqual(captured["config"]["uniformity"], 4567)
        self.assertEqual(captured["config"]["img_wgt"], 9)
        self.assertEqual(captured["config"]["feather"], 5)
        self.assertEqual(captured["engine"]["edge_method"], "PAGE")
        self.assertTrue(captured["engine"]["do_mask"])
        self.assertEqual([m.shape for m in captured["engine"]["msk_frs_seq"]], [(128, 128)] * 2)

    def test_single_frame_masks_preserve_background_without_engine(self):
        self.job["frames"] = self.frames[:1]
        self.job["render_options"] = dict(do_mask=True)
        mask = self.root / "mask.png"
        values = np.zeros((128, 128), np.uint8)
        values[:, :64] = 255
        mask.write_bytes(cv2.imencode(".png", values)[1].tobytes())
        self.job["masks"] = [[0, str(mask)]]
        with patch.dict(sys.modules, {"torch": None, "ezsynth.main_ez": None}):
            self.run_job()
        output = cv2.imdecode(np.frombuffer((self.output / "000.png").read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        self.assertTrue(np.all(output[:, :64] == 200))
        self.assertTrue(np.all(output[:, 64:] == 40))

    def test_single_frame_without_masks_copies_style_without_engine(self):
        self.job["frames"] = self.frames[:1]
        with patch.dict(sys.modules, {"torch": None, "ezsynth.main_ez": None}):
            self.run_job()
        output = cv2.imdecode(np.frombuffer((self.output / "000.png").read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        self.assertTrue(np.all(output == 200))

    def test_missing_mask_is_rejected_before_engine_initialization(self):
        self.job["render_options"] = dict(do_mask=True)
        with patch.dict(sys.modules, {"torch": None, "ezsynth.main_ez": None}), self.assertRaises(ValueError):
            self.run_job()
        self.assertFalse((self.output / "COMPLETE.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
