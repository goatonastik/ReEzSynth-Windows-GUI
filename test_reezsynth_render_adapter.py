"""Exercise the real renderer adapter with a fake engine; no torch/GPU imports."""
import ast
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

from reezsynth_config import PREVIEW, STANDARD, WEIGHTS, validate_synthesis_dimensions
from reezsynth_jobs import render_job


class RenderAdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="reezsynth_adapter_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(patch.dict(os.environ))
        self.enterContext(patch('reezsynth_config.validate_flow_model_available'))
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
            def __init__(self, uniformity=3500.0, patchsize=7, pyramidlevels=6,
                         searchvoteiters=12, patchmatchiters=6, extrapass3x3=True,
                         edg_wgt=1.0, img_wgt=6.0, pos_wgt=2.0, wrp_wgt=0.5,
                         use_gpu=False, use_lsqr=True, use_poisson_cupy=False,
                         poisson_maxiter=None, only_mode='none', do_mask=False,
                         pre_mask=False, feather=0, keyframe_preservation='Current behavior'):
                captured["config"] = locals() | {}
                captured["config"].pop("self")
        class Engine:
            def __init__(self, **kwargs):
                captured["engine"] = kwargs
                self.frames = kwargs["img_frs_seq"]
                self.masked_frs_seq = []
                self.edge_guides = []
                self.rafter = types.SimpleNamespace(_compute_flow=lambda source, target:
                    np.zeros((*source.shape[:2], 2), np.float32))
                self.eb = types.SimpleNamespace(backends={"cuda": 17, "auto": 18, "cpu": 19}, backend=None, run=lambda: None)
                captured["runner"] = self
            def run_sequences(self):
                for source, target in zip(self.frames, self.frames[1:]):
                    self.rafter._compute_flow(source, target)
                    self.eb.run()
                return self.frames, None
        self.enterContext(patch.dict(sys.modules, {
            "torch": types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True, get_device_name=lambda _: "mock")),
            "ezsynth.aux_classes": types.SimpleNamespace(RunConfig=Config),
            "ezsynth.main_ez": types.SimpleNamespace(EzsynthBase=Engine),
        }))
        return captured

    def test_validated_precomputations_are_reused_across_jobs(self):
        captured = self.fake_engine()
        self.job['precompute_cache'] = str(self.root / '.reezsynth-cache')
        counts = {'edges': 0, 'flow': 0}
        def edges(frames, method):
            counts['edges'] += 1
            return [np.full(frame.shape[:2], 127, np.uint8) for frame in frames]
        engine = sys.modules['ezsynth.main_ez'].EzsynthBase
        original_init = engine.__init__
        def initialize(instance, **kwargs):
            original_init(instance, **kwargs)
            def flow(source, target):
                counts['flow'] += 1
                return np.zeros((*source.shape[:2], 2), np.float32)
            instance.rafter._compute_flow = flow
        computations = types.SimpleNamespace(precompute_edge_guides=edges)
        with patch.object(engine, '__init__', initialize), \
             patch.dict(sys.modules, {'ezsynth.aux_computations': computations}):
            self.run_job()
            self.run_job()
        self.assertEqual(counts, {'edges': 1, 'flow': 1})
        self.assertEqual(len(captured['runner'].edge_guides), 2)

    def test_cuda_memory_failure_explains_resolution_and_preserves_failure(self):
        self.fake_engine()
        engine = sys.modules['ezsynth.main_ez'].EzsynthBase
        failure = RuntimeError('CUDA out of memory. Tried to allocate 62.57 GiB.')
        log = io.StringIO()
        with patch.object(engine, 'run_sequences', side_effect=failure), \
             contextlib.redirect_stdout(log), self.assertRaises(RuntimeError) as raised:
            self.run_job()
        self.assertIs(raised.exception, failure)
        self.assertIn('720p', log.getvalue())
        self.assertIn('also reduces output resolution', log.getvalue())
        self.assertFalse((self.output / 'COMPLETE.txt').exists())

    def test_legacy_jobs_preserve_preview_and_standard_parameters(self):
        captured = self.fake_engine()
        for quality, expected in (("Preview", PREVIEW), ("Standard", STANDARD)):
            self.job["quality"] = quality
            self.run_job()
            for name, value in {**expected, **WEIGHTS}.items():
                if name in ('key_wgt', 'mask_wgt', 'searchvote_schedule', 'patchmatch_schedule'):
                    continue  # Adapter-level controls, not RunConfig keywords.
                self.assertEqual(captured["config"][name], value)
            self.assertEqual(captured["engine"]["raft_flow_model_name"], "sintel")
            self.assertEqual(captured["runner"].eb.backend, 17)
            self.assertFalse(captured["engine"]["do_mask"])
        self.assertTrue((self.output / "COMPLETE.txt").exists())

    def test_requested_video_export_finishes_before_completion_marker(self):
        self.job['frames'] = self.frames[:1]
        self.job['video_export'] = {'enabled': True, 'fps': 12, 'audio': ''}
        def export(output, numbers, padding, settings, **kwargs):
            self.assertFalse((Path(output) / 'COMPLETE.txt').exists())
            (Path(output) / 'render.mp4').write_bytes(b'mp4')
        with patch('reezsynth_video_export.export_rendered_video', side_effect=export):
            self.run_job()
        self.assertTrue((self.output / 'render.mp4').is_file())
        self.assertTrue((self.output / 'COMPLETE.txt').is_file())

    def test_requested_video_export_failure_prevents_completion_marker(self):
        self.job['frames'] = self.frames[:1]
        self.job['video_export'] = {'enabled': True, 'fps': 24, 'audio': ''}
        with patch('reezsynth_video_export.export_rendered_video',
                   side_effect=RuntimeError('encoder failed')), \
                self.assertRaisesRegex(RuntimeError, 'encoder failed'):
            self.run_job()
        self.assertFalse((self.output / 'COMPLETE.txt').exists())

    def test_custom_controls_and_grayscale_masks_reach_engine(self):
        captured = self.fake_engine()
        mask = self.root / "mask.png"
        mask.write_bytes(cv2.imencode(".png", np.full((128, 128), 255, np.uint8))[1].tobytes())
        self.job["masks"] = [[i, str(mask)] for i in range(2)]
        self.job["render_options"] = dict(uniformity=4567.0, edge_method="PAGE", do_mask=True,
                                            pre_mask=True, feather=5, flow_model="kitti",
                                            ebsynth_backend="cpu")
        self.job["guide_weights"] = dict(img_wgt=9.0)
        self.run_job()
        self.assertEqual(captured["config"]["uniformity"], 4567)
        self.assertEqual(captured["config"]["img_wgt"], 9)
        self.assertEqual(captured["config"]["feather"], 5)
        self.assertEqual(captured["engine"]["edge_method"], "PAGE")
        self.assertEqual(captured["engine"]["raft_flow_model_name"], "kitti")
        self.assertEqual(captured["runner"].eb.backend, 19)
        self.assertTrue(captured["engine"]["do_mask"])
        self.assertEqual([m.shape for m in captured["engine"]["msk_frs_seq"]], [(128, 128)] * 2)

    def test_optional_flow_architecture_reaches_engine(self):
        captured = self.fake_engine()
        self.job['render_options'] = dict(flow_arch='EF_RAFT', flow_model='ours_sintel')
        self.run_job()
        self.assertEqual(captured['engine']['flow_arch'], 'EF_RAFT')
        self.assertEqual(captured['engine']['raft_flow_model_name'], 'ours_sintel')

    def test_custom_edge_guides_skip_engine_edge_generation(self):
        captured = self.fake_engine()
        guides = []
        for number, _ in self.frames:
            path = self.root / f'edge{number:03d}.png'
            path.write_bytes(cv2.imencode('.png', np.full((128, 128), number + 10, np.uint8))[1].tobytes())
            guides.append([number, str(path)])
        self.job['render_options'] = dict(custom_edge_guides=True)
        self.job['edge_guides'] = guides
        self.run_job()
        self.assertFalse(captured['engine']['do_compute_edge'])
        self.assertEqual([guide.shape for guide in captured['runner'].edge_guides], [(128, 128), (128, 128)])
        self.assertEqual(int(captured['runner'].edge_guides[1][0, 0]), 11)

    def test_missing_custom_edge_guide_rejects_before_engine(self):
        self.job['render_options'] = dict(custom_edge_guides=True)
        with patch.dict(sys.modules, {'torch': None, 'ezsynth.main_ez': None}), self.assertRaisesRegex(ValueError, 'edge-guide'):
            self.run_job()

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
        with patch.dict(sys.modules, {"torch": None, "ezsynth.main_ez": None}), \
             patch('reezsynth_config.validate_flow_model_available', side_effect=AssertionError('Copy needs no weights')):
            self.run_job()
        output = cv2.imdecode(np.frombuffer((self.output / "000.png").read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        self.assertTrue(np.all(output == 200))

    def test_exact_dimensions_and_automatic_pyramid_forwarding(self):
        captured = self.fake_engine()
        self.job['processing_size'] = [512, 288]
        self.job['render_options'] = dict(pyramidlevels=-1)
        self.run_job()
        self.assertEqual(captured['config']['pyramidlevels'], -1)
        self.assertEqual(captured['engine']['img_frs_seq'][0].shape, (288, 512, 3))
        self.assertEqual(cv2.imread(str(self.output / '001.png')).shape, (288, 512, 3))

    def test_oversized_patch_is_rejected_before_engine_but_single_copy_is_allowed(self):
        self.job['render_options'] = dict(patchsize=65)
        with patch.dict(sys.modules, {'torch': None, 'ezsynth.main_ez': None}):
            with self.assertRaisesRegex(ValueError, 'at least 131 x 131'):
                self.run_job()
            self.assertFalse((self.output / 'COMPLETE.txt').exists())
            self.job['frames'] = self.frames[:1]
            self.run_job()
            self.assertTrue((self.output / 'COMPLETE.txt').exists())

    def test_largest_fitting_patch_reaches_video_engine_unchanged(self):
        captured = self.fake_engine()
        self.job['render_options'] = dict(patchsize=63, pyramidlevels=-1)
        self.run_job()
        self.assertEqual(captured['config']['patchsize'], 63)
        self.assertEqual(captured['config']['pyramidlevels'], -1)

    def test_cpu_and_auto_allow_cpu_flow_and_reject_cuda_only_settings(self):
        captured = self.fake_engine()
        sys.modules['torch'].cuda.is_available = lambda: False
        sys.modules['torch'].cuda.get_device_name = lambda _: self.fail('Must not query a missing GPU')
        for backend, identifier in (('cpu', 19), ('auto', 18)):
            self.job['render_options'] = dict(ebsynth_backend=backend)
            self.run_job()
            self.assertEqual(captured['runner'].eb.backend, identifier)
        for options, message in ((dict(ebsynth_backend='cuda'), 'CUDA is unavailable'),
                                 (dict(ebsynth_backend='cpu', edge_method='PAGE'), 'Choose Classic'),
                                 (dict(ebsynth_backend='cpu', memory_efficient_raft=True), 'requires CUDA')):
            self.job['render_options'] = options
            with self.subTest(options=options), self.assertRaisesRegex(RuntimeError, message):
                self.run_job()

    def test_missing_mask_is_rejected_before_engine_initialization(self):
        self.job["render_options"] = dict(do_mask=True)
        with patch.dict(sys.modules, {"torch": None, "ezsynth.main_ez": None}), self.assertRaises(ValueError):
            self.run_job()
        self.assertFalse((self.output / "COMPLETE.txt").exists())


class SynthesisDimensionTests(unittest.TestCase):
    def test_preflight_matches_live_wrapper_pyramid_availability(self):
        # Execute only the pure upstream method; never load the native DLL.
        tree = ast.parse((Path(__file__).parent / 'ezsynth/utils/_eb.py').read_text(encoding='utf-8'))
        runner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'EbsynthRunner')
        method = next(node for node in runner.body if isinstance(node, ast.FunctionDef) and node.name == 'get_max_pyramid_level')
        namespace = {}
        # Compile only the selected method parsed from this checkout's fixed source.
        exec(compile(ast.Module(body=[method], type_ignores=[]), '_eb.py', 'exec'), namespace)  # nosec B102
        for patchsize in (3, 7, 63, 99):
            for extent in (patchsize, 2 * patchsize, 2 * patchsize + 1, 512):
                for style, target in (((extent, 512), (512, 512)), ((512, 512), (512, extent))):
                    with self.subTest(patch=patchsize, style=style, target=target):
                        levels = namespace['get_max_pyramid_level'](None, patchsize, *style, *target)
                        if levels:
                            validate_synthesis_dimensions(patchsize, style, target)
                        else:
                            with self.assertRaises(ValueError):
                                validate_synthesis_dimensions(patchsize, style, target)


if __name__ == "__main__":
    unittest.main(verbosity=2)
