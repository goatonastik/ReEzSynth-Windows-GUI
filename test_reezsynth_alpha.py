"""Transparent styles: raw payload, separate guides, native synthesis and PNGs."""
import contextlib
import io
import itertools
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from reezsynth_alpha import read_style, as_bgra, keyframe_guides, selected_alpha
import test_reezsynth_render_adapter as adapter


def samples(size=128):
    y, x = np.indices((size, size))
    rgb = np.stack((x * 7 % 256, y * 11 % 256, (x + y) * 3 % 256), -1).astype(np.uint8)
    alpha = ((x * 5 + y * 13) % 256).astype(np.uint8)
    alpha[:, :size // 2] = 0
    black, white = [np.dstack((rgb.copy(), alpha)) for _ in range(2)]
    black[alpha == 0, :3], white[alpha == 0, :3] = 0, 255
    return dict(rgb=rgb, opaque=np.dstack((rgb, np.full_like(alpha, 255))),
                zero=np.dstack((rgb, np.zeros_like(alpha))),
                half=np.dstack((rgb, np.full_like(alpha, 128))),
                partial=np.dstack((rgb, alpha)), hidden_black=black, hidden_white=white)


def save(path, value):
    Path(path).write_bytes(cv2.imencode('.png', value)[1].tobytes())


class AlphaAdapterTests(unittest.TestCase):
    setUp = adapter.RenderAdapterTests.setUp
    run_job = adapter.RenderAdapterTests.run_job

    def single(self):
        self.job.update(key=42, frames=[[42, self.frames[0][1]]])
        self.job['render_options'] = dict(ebsynth_backend='cpu', patchsize=3,
            pyramidlevels=1, searchvoteiters=1, patchmatchiters=1,
            extrapass3x3=False, uniformity=0)

    def fake_native(self, calls, transform=lambda a: a.copy()):
        def run(style, guides):
            calls.append((style.copy(), [(a.copy(), b.copy(), w) for a, b, w in guides]))
            return transform(style), np.zeros(style.shape[:2], np.float32)
        factory = lambda **kw: types.SimpleNamespace(run=run,
            runner=types.SimpleNamespace(initialize_libebsynth=lambda: None))
        self.enterContext(patch.dict(sys.modules, {
            'ezsynth.utils._ebsynth': types.SimpleNamespace(ebsynth=factory),
            'ezsynth.aux_computations': types.SimpleNamespace(precompute_edge_guides=lambda frames, method:
                [np.zeros(f.shape[:2], np.uint8) for f in frames])}))

    def test_exact_key_loader_resize_storage_and_png_matrix(self):
        self.single()
        calls = []
        self.fake_native(calls)
        save(self.frames[0][1], samples(256)['rgb'])
        for name, value in samples(256).items():
            save(self.job['style'], value)
            for stream in (False, True):
                for size in (256, 128):
                    with self.subTest(name=name, stream=stream, size=size):
                        calls.clear()
                        self.job['processing_size'] = None if size == 256 else [size, size]
                        self.job['render_options']['stream_frames'] = stream
                        self.run_job()
                        expected = value[..., :3] if name == 'opaque' else value
                        if size != 256:
                            expected = cv2.resize(expected, (size, size), interpolation=cv2.INTER_AREA)
                        output = cv2.imread(str(self.output / '042.png'), cv2.IMREAD_UNCHANGED)
                        np.testing.assert_array_equal(output, expected)
                        self.assertEqual(output.dtype, np.uint8)
                        self.assertEqual(len(calls), 0 if name in ('rgb', 'opaque') else 1)
                        if calls:
                            style, guides = calls[0]
                            np.testing.assert_array_equal(style, expected)
                            self.assertEqual([a.shape[2] if a.ndim == 3 else 1 for a, _, _ in guides], [1, 3, 3, 3])
                            self.assertTrue(all(a.shape[:2] == (size, size) for a, _, _ in guides))
                        self.assertFalse(list(self.output.glob('.frame-storage-*')))

    def test_nonconstant_rgba_key_is_synthesized_not_copied(self):
        self.single()
        style = samples()['partial']
        save(self.job['style'], style)
        calls = []
        self.fake_native(calls, lambda a: np.roll(a, 1, axis=0))
        self.run_job()
        output = cv2.imread(str(self.output / '042.png'), cv2.IMREAD_UNCHANGED)
        np.testing.assert_array_equal(output, np.roll(style, 1, axis=0))
        self.assertFalse(np.array_equal(output, style))

    def test_single_rgba_frame_uses_alpha_aware_mask_composite(self):
        self.single()
        style = np.full((128, 128, 4), [250, 240, 230, 0], np.uint8)
        save(self.job['style'], style)
        mask = self.root / 'mask.png'
        save(mask, np.full((128, 128), 255, np.uint8))
        self.job['masks'] = [[42, str(mask)]]
        self.job['render_options'].update(do_mask=True)
        self.fake_native([])

        self.run_job()

        result = cv2.imread(str(self.output / '042.png'), cv2.IMREAD_UNCHANGED)
        np.testing.assert_array_equal(
            result, np.full((128, 128, 4), [40, 40, 40, 255], np.uint8)
        )

    def test_alpha_detection_precedes_rounding_during_downsize(self):
        self.single()
        value = samples(256)['opaque']
        value[0, 0, 3] = 254
        save(self.frames[0][1], value[..., :3])
        save(self.job['style'], value)
        self.job['processing_size'] = [128, 128]
        calls = []
        self.fake_native(calls)
        self.run_job()
        self.assertEqual(calls[0][0].shape[2], 4)
        result = cv2.imread(str(self.output / '042.png'), -1)
        self.assertEqual(result.shape[2], 4)
        np.testing.assert_array_equal(result, cv2.resize(value, (128, 128), interpolation=cv2.INTER_AREA))

    def test_output_spatial_and_channel_checks_are_explicit(self):
        self.single()
        save(self.job['style'], samples()['partial'])
        self.fake_native([], lambda a: a[..., :3])
        with self.assertRaisesRegex(RuntimeError, 'shape|Invalid'):
            self.run_job()
        self.assertFalse((self.output / 'COMPLETE.txt').exists())

    def test_source_alpha_does_not_select_rgba_style_path(self):
        self.single()
        save(self.frames[0][1], samples()['partial'])
        calls = []
        self.fake_native(calls)
        self.run_job()
        self.assertFalse(calls)
        self.assertEqual(cv2.imread(str(self.output / '042.png'), -1).shape[2], 3)

    def test_transparent_16bit_rejected_without_truncation(self):
        save(self.job['style'], samples()['partial'].astype(np.uint16) * 257)
        with self.assertRaisesRegex(ValueError, '8-bit'):
            read_style(self.job['style'])

    def test_fuoum_rejects_at_real_entry_before_runtime_or_flow(self):
        from reezsynth_fuoum import render_fuoum_job
        from reezsynth_engines import FUOUM
        self.single()
        self.job['render_options']['engine'] = FUOUM
        self.job['render_options']['ebsynth_backend'] = 'cuda'
        save(self.job['style'], samples()['partial'])
        with self.assertRaisesRegex(ValueError, 'FuouM transparent RGBA.*Legacy'):
            render_fuoum_job(self.job, lambda *a, **kw: None)
        self.assertFalse((self.output / 'COMPLETE.txt').exists())

    def test_rgba_image_synthesis_preserves_style_with_grayscale_guides(self):
        from test_reezsynth_image import ImageAdapterTests
        ImageAdapterTests.prepare(self)
        style = samples()['partial']
        save(self.settings['style'], style)
        Engine = sys.modules['ezsynth.main_ez'].ImageSynthBase
        original = Engine.__init__
        def initialize(instance, *args, **kwargs):
            original(instance, *args, **kwargs)
            def native(value, guides):
                np.testing.assert_array_equal(value, style)
                self.assertEqual([a.ndim for a, _, _ in guides], [2])
                return cv2.resize(value, (160, 80)), np.zeros((80, 160), np.float32)
            instance.eb.run = native
        with patch.object(Engine, '__init__', initialize):
            self.run_job()
        result = cv2.imread(str(self.output / 'image.png'), -1)
        np.testing.assert_array_equal(result, cv2.resize(style, (160, 80)))

    def test_mixed_group_promotes_only_styles_and_keeps_frame_identity(self):
        from test_reezsynth_grouped import upstream_engine
        from reezsynth_video_plan import plan_grouped_video
        captured = {}
        Engine = upstream_engine(captured)
        ns = Engine.run_sequences_full.__globals__
        ns['get_warped_img'] = lambda styles, *a: styles[-1]
        # These substitutes remove flow/native cost, not the live pass/sequence code.
        ns['PositionalGuide'] = lambda: types.SimpleNamespace(create_from_flow=lambda *a: np.zeros((128, 128, 3), np.uint8))
        original_init = Engine.__init__
        boundaries = []
        def initialize(instance, **kw):
            original_init(instance, **kw)
            old = instance.eb.run
            def run(style, guides):
                boundaries.append((style.shape[2], [a.shape[2] if a.ndim == 3 else 1 for a, _, _ in guides]))
                return old(style, guides=guides)
            instance.eb.run = run
        transparent = self.root / 'alpha.png'
        save(transparent, samples()['partial'])
        with patch.object(Engine, '__init__', initialize), patch.dict(sys.modules, {
            'torch': types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True, get_device_name=lambda _: 'mock')),
            'ezsynth.main_ez': types.SimpleNamespace(EzsynthBase=Engine),
            'ezsynth.aux_classes': types.SimpleNamespace(RunConfig=lambda **kw: types.SimpleNamespace(**kw))}):
            for stream in (False, True):
                for mode in ('none', 'forward', 'reverse'):
                    self.job.update(plan_grouped_video({i: self.frames[0][1] for i in range(41, 46)},
                        {42: str(transparent), 44: self.job['style']}, blend_options={'only_mode': mode}))
                    self.job['render_options'] = {'stream_frames': stream}
                    self.run_job()
                    self.assertTrue(all(cv2.imread(str(self.output / f'{i:03}.png'), -1).shape == (128, 128, 4) for i in range(41, 46)))
                    self.assertTrue(all(c == 4 and g == [3, 3, 3, 3] for c, g in boundaries))
                    # Disk sequences are deliberately cleaned after render_job returns.
                    self.assertEqual(len(captured['engine']['img_frs_seq']), 5)


class AlphaMaskCompositeTests(unittest.TestCase):
    def test_transparent_style_pixels_reveal_original_in_masked_output(self):
        from ezsynth.aux_masker import apply_masked_back

        original = np.full((1, 3, 3), [10, 20, 30], np.uint8)
        processed = np.array([[[255, 255, 255, 0],
                               [110, 120, 130, 128],
                               [210, 220, 230, 255]]], np.uint8)
        mask = np.full((1, 3), 255, np.uint8)
        result = apply_masked_back(original, processed, mask)
        np.testing.assert_array_equal(result[0, 0], [10, 20, 30, 255])
        np.testing.assert_array_equal(result[0, 1], [60, 70, 80, 255])
        np.testing.assert_array_equal(result[0, 2], [210, 220, 230, 255])

    def test_zero_mask_keeps_original_with_rgba_style(self):
        from ezsynth.aux_masker import apply_masked_back

        original = np.array([[[17, 37, 91]]], np.uint8)
        processed = np.array([[[250, 240, 230, 128]]], np.uint8)
        result = apply_masked_back(original, processed, np.zeros((1, 1), np.uint8))
        np.testing.assert_array_equal(result, np.array([[[17, 37, 91, 255]]], np.uint8))

    def test_feathered_coverage_combines_both_rgba_alphas(self):
        from ezsynth.aux_masker import apply_masked_back

        original = np.full((1, 3, 4), [20, 40, 60, 128], np.uint8)
        processed = np.full((1, 3, 4), [220, 140, 20, 128], np.uint8)
        mask = np.array([[0, 255, 0]], np.uint8)
        result = apply_masked_back(original, processed, mask, feather_radius=3)

        coverage = cv2.GaussianBlur(mask, (3, 3), 0)[0, 1] / 255
        foreground_alpha = 128 / 255
        background_alpha = 128 / 255
        effective_alpha = coverage * foreground_alpha
        output_alpha = effective_alpha + background_alpha * (1 - effective_alpha)
        expected_rgb = (
            processed[0, 1, :3] * effective_alpha
            + original[0, 1, :3] * background_alpha * (1 - effective_alpha)
        ) / output_alpha
        expected = np.rint(np.r_[expected_rgb, output_alpha * 255]).astype(np.uint8)
        np.testing.assert_array_equal(result[0, 1], expected)

    def test_two_fully_transparent_inputs_produce_clear_black(self):
        from ezsynth.aux_masker import apply_masked_back

        original = np.array([[[17, 37, 91, 0]]], np.uint8)
        processed = np.array([[[250, 240, 230, 0]]], np.uint8)
        result = apply_masked_back(original, processed, np.full((1, 1), 255, np.uint8))
        np.testing.assert_array_equal(result, np.zeros((1, 1, 4), np.uint8))

    def test_sequence_rejects_any_length_mismatch(self):
        from ezsynth.aux_masker import apply_masked_back_seq

        frame = np.zeros((1, 1, 3), np.uint8)
        mask = np.zeros((1, 1), np.uint8)
        for images, styles, masks in (
            ([frame], [frame], [mask, mask]),
            ([frame, frame], [frame, frame], [mask]),
        ):
            with self.subTest(lengths=tuple(map(len, (images, styles, masks)))):
                with self.assertRaisesRegex(ValueError, 'Lengths not match'):
                    apply_masked_back_seq(images, styles, masks)


class AlphaReconstructionTests(unittest.TestCase):
    def test_real_four_channel_warp_preserves_alpha_hidden_payload_and_resize(self):
        """Exercise the live float -> remap -> uint8 -> resize propagation path."""
        from ezsynth.aux_run import get_warped_img
        from ezsynth.utils.flow_utils.warp import Warp
        value = samples(7)['hidden_white']
        # Use nonzero partial alpha as well as deliberately hostile RGB at alpha 0.
        self.assertTrue(np.any((value[..., 3] > 0) & (value[..., 3] < 255)))
        self.assertTrue(np.all(value[value[..., 3] == 0, :3] == 255))
        flow = np.zeros((7, 7, 2), np.float32)
        native = get_warped_img([value], (7, 7), 1, Warp(value[..., :3]), flow)
        self.assertIsNotNone(native)
        self.assertEqual(native.shape, (7, 7, 4))
        np.testing.assert_array_equal(native, value)
        resized = get_warped_img([value], (11, 9), 1, Warp(value[..., :3]), flow)
        self.assertEqual(resized.shape, (9, 11, 4))
        np.testing.assert_array_equal(resized, cv2.resize(value, (11, 9)))
        self.assertGreater(np.count_nonzero((resized[..., 3] > 0) & (resized[..., 3] < 255)), 0)

    def test_warp_none_fails_with_adapter_error(self):
        from ezsynth.aux_run import get_warped_img
        value = samples(7)['partial']
        warp = types.SimpleNamespace(run_warping=lambda *args: None)
        with self.assertRaisesRegex(RuntimeError, 'Frame warp failed'):
            get_warped_img([value], (7, 7), 1, warp, np.zeros((7, 7, 2), np.float32))

    def test_constant_rgba_blending_keeps_hidden_color_and_alpha_exact(self):
        from ezsynth.utils.blend.blender import Blend
        mask = np.indices((8, 8)).sum(0).astype(np.uint8) % 2
        with contextlib.redirect_stdout(io.StringIO()), np.errstate(all='raise'):
            for alpha in (0, 128, 255):
                value = np.full((8, 8, 4), [17, 90, 240, alpha], np.uint8)
                blender = Blend()
                hist = blender._hist_blend([value], [value], [mask])
                result = blender._reconstruct([value], [value], [mask], hist)
                np.testing.assert_array_equal(result[0], value)

    def test_rgba_live_pass_boundaries_channels_and_work_counts(self):
        from test_reezsynth_grouped import upstream_engine
        from reezsynth_video_plan import synthesis_work
        captured = {}
        Engine = upstream_engine(captured)
        ns = Engine.run_sequences_full.__globals__
        ns['get_warped_img'] = lambda styles, *a: styles[-1]
        ns['PositionalGuide'] = lambda: types.SimpleNamespace(create_from_flow=lambda *a: np.zeros((8, 8, 3), np.uint8))
        frames = [samples(8)['rgb']] * 5
        style = samples(8)['partial']
        with contextlib.redirect_stdout(io.StringIO()):
            for length in range(2, 6):
                for size in range(1, length + 1):
                    for keys in itertools.combinations(range(length), size):
                        for mode in ('none', 'forward', 'reverse'):
                            cfg = types.SimpleNamespace(only_mode=mode, do_mask=False,
                                edg_wgt=1, img_wgt=6, pos_wgt=2, wrp_wgt=.5)
                            runner = Engine(cfg=cfg, img_frs_seq=frames[:length],
                                            style_frs=[style] * size, style_idxes=list(keys))
                            expected = synthesis_work(0, length - 1, keys, mode) + sum(
                                2 if seq.mode == 'blend' and mode == 'none' else 1 for seq in runner.sequences)
                            old = runner.eb.run
                            def run(value, guides):
                                self.assertEqual(value.shape[2], 4)
                                self.assertTrue(all(a.shape[2] == b.shape[2] == 3 for a, b, _ in guides))
                                return old(value, guides=guides)
                            runner.eb.run = run
                            result, _ = runner.run_sequences()
                            self.assertEqual(captured['calls'], expected, (length, keys, mode))
                            self.assertEqual(len(result), length)
                            for value in result:
                                np.testing.assert_array_equal(value, style)

    def test_rgb_lab_reconstruction_excludes_alpha_and_reassembles_selection(self):
        from ezsynth.utils.blend.reconstruction import construct_A, poisson_fusion
        from ezsynth.utils.blend.blender import Blend
        a, b = samples(8)['partial'], samples(8)['hidden_white']
        b = b.copy()
        b[..., 3] = 255 - a[..., 3]
        mask = np.indices((8, 8)).sum(0).astype(np.uint8) % 2
        with contextlib.redirect_stdout(io.StringIO()):
            hist4 = Blend()._hist_blend([a], [b], [mask])[0]
            hist3 = Blend()._hist_blend([a[..., :3]], [b[..., :3]], [mask])[0]
            np.testing.assert_array_equal(hist4[..., :3], hist3)
            np.testing.assert_array_equal(hist4[..., 3], selected_alpha(a, b, mask))
            matrix = construct_A(8, 8, [2.5, .5, .5])
            output = poisson_fusion(hist4, a, b, mask, matrix, use_lsqr=False)
            rgb = poisson_fusion(hist3, a[..., :3], b[..., :3], mask, matrix, use_lsqr=False)
        np.testing.assert_array_equal(output[..., :3], rgb)
        np.testing.assert_array_equal(output[..., 3], np.where(mask, b[..., 3], a[..., 3]))

    def test_disk_storage_and_promotion_preserve_number_and_hidden_rgb(self):
        from reezsynth_sequence import frame_storage, array_sequence, number_of
        with tempfile.TemporaryDirectory() as root:
            with frame_storage(dict(output=root, render_options={'stream_frames': True})):
                values = array_sequence([samples(8)['rgb'], samples(8)['hidden_white']], numbers=[41, 42])
                values[0] = as_bgra(values[0])
                self.assertEqual(number_of(values[0], {}), 41)
                self.assertTrue((values[0][..., 3] == 255).all())
                np.testing.assert_array_equal(values[1], samples(8)['hidden_white'])


class AlphaNativeTests(unittest.TestCase):
    def test_native_separate_four_style_ten_guide_channels_constant_opacity(self):
        if sys.platform != 'win32':
            self.skipTest('Pinned Windows native DLL compatibility test')
        # The DLL's OpenMP runtime reads its setting at load; isolate it from
        # other suite imports and avoid tiny fixtures spawning many CPU threads.
        if os.environ.get('REEZSYNTH_ALPHA_NATIVE_CHILD') != '1':
            result = subprocess.run([sys.executable, '-B', '-m', 'unittest', self.id()],
                env=dict(os.environ, OMP_NUM_THREADS='1', REEZSYNTH_ALPHA_NATIVE_CHILD='1'),
                cwd=Path(__file__).resolve().parent, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        from ezsynth.utils._ebsynth import ebsynth
        eb = ebsynth(backend='cpu', patchsize=3, pyramidlevels=1,
                     searchvoteiters=1, patchmatchiters=1, uniformity=0, extrapass3x3=False)
        eb.runner.initialize_libebsynth()
        source = samples(16)['rgb']
        weights = dict(edg_wgt=1, img_wgt=6, pos_wgt=2, wrp_wgt=.5)
        for channels, alpha in ((3, 255), (4, 0), (4, 128), (4, 255)):
            with self.subTest(channels=channels, alpha=alpha):
                style = np.empty((16, 16, channels), np.uint8)
                style[..., :3] = [17, 90, 240]
                if channels == 4:
                    style[..., 3] = alpha
                result, error = eb.run(style, keyframe_guides(style, source, np.zeros((16, 16), np.uint8), weights))
                np.testing.assert_array_equal(result, style)
                self.assertEqual(error.shape, (16, 16))


if __name__ == '__main__':
    unittest.main()
