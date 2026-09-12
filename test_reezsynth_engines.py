"""Engine isolation, configuration mapping and actual GUI job routing regressions."""
import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from reezsynth_config import RENDER, STANDARD, validate_render, validate_group
from reezsynth_engines import LEGACY, FUOUM, FUOUM_REVISION, ROOT, prepare_runtime, validate_capabilities, activate_fuoum
from reezsynth_fuoum import build_configs, native_guides
from test_reezsynth_gui import GuiFixture
from test_reezsynth_lifecycle import LifecycleFixture


class EngineTests(unittest.TestCase):
    def test_revision_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'file requests'):
            validate_group('render', dict(options={'engine': FUOUM}, engine_revision='wrong-revision'))

    def test_legacy_job_cannot_reuse_a_fuoum_worker(self):
        from reezsynth_jobs import render_job
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / 'job.json'
            job.write_text(json.dumps({'render_options': {'engine': LEGACY}}), encoding='utf-8')
            module = types.SimpleNamespace(_frontend_source='fuoum-source')
            with patch.dict(sys.modules, {'ezsynth': module}), self.assertRaisesRegex(RuntimeError, 'engine changed'):
                render_job(job)

    def test_old_presets_keep_the_original_engine(self):
        result = validate_group('render', {'quality': 'Standard', 'options': STANDARD})
        self.assertEqual(result['options']['engine'], LEGACY)
        with self.assertRaisesRegex(ValueError, 'Unknown synthesis engine'):
            validate_render({'engine': 'unknown'})

    def test_unsupported_requests_fail_before_rendering(self):
        options = dict(RENDER, engine=FUOUM)
        validate_capabilities(options)
        for field, value in (('ebsynth_backend', 'cpu'), ('memory_efficient_raft', True),
                              ('flow_arch', 'EF_RAFT')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_capabilities(dict(options, **{field: value}))
        for extras in ({'blend': {'use_gpu': True}}, {'blend': {'use_poisson_cupy': True}}):
            with self.subTest(extras=extras), self.assertRaises(ValueError):
                validate_capabilities(options, **extras)
        validate_capabilities(dict(options, do_mask=True), image=True)
        validate_capabilities(dict(options, do_mask=True, custom_edge_guides=True),
                              exports={'maps': True, 'flow': True}, blend={'only_mode': 'reverse'})

    def test_native_mapping_uses_actual_solver_and_positive_pyramid_depth(self):
        class StrictNative:
            def __init__(self, uniformity, patch_size, search_vote_iters, patch_match_iters,
                         extra_pass_3x3, backend, vote_mode, cost_function, stop_threshold,
                         search_pruning_threshold, edge_weight, image_weight, pos_weight, warp_weight,
                         sparse_anchor_weight):
                self.__dict__.update(locals())
        class StrictPipeline:
            def __init__(self, pyramid_levels, use_temporal_nnf_propagation, use_sparse_feature_guide):
                self.__dict__.update(locals())
        class StrictBlend:
            def __init__(self, poisson_solver, poisson_maxiter, poisson_grad_weight_l, poisson_grad_weight_ab):
                self.__dict__.update(locals())
        schema = types.SimpleNamespace(EbsynthParamsConfig=StrictNative,
                                       PipelineConfig=StrictPipeline, BlendingConfig=StrictBlend)
        with patch.dict(sys.modules, {'ezsynth.config': schema}):
            native, pipeline, blend = build_configs(dict(RENDER, engine=FUOUM, pyramidlevels=-1,
                                                        fuoum_vote_mode='plain', fuoum_cost_function='ncc',
                                                        fuoum_stop_threshold=7, fuoum_search_pruning_threshold=9,
                                                        fuoum_sparse_anchor_weight=12),
                                                    {'key_wgt': 2, 'img_wgt': 8},
                                                    {'use_lsqr': False, 'poisson_maxiter': 17,
                                                     'fuoum_poisson_solver': 'cg',
                                                     'fuoum_poisson_grad_weight_l': 3,
                                                     'fuoum_poisson_grad_weight_ab': .25})
        self.assertEqual(native.image_weight, 4)
        self.assertEqual(native.backend, 'cuda')
        self.assertEqual(native.vote_mode, 'plain')
        self.assertEqual(native.cost_function, 'ncc')
        self.assertEqual(native.stop_threshold, 7)
        self.assertEqual(native.search_pruning_threshold, 9)
        self.assertEqual(native.sparse_anchor_weight, 6)
        self.assertEqual(pipeline.pyramid_levels, 32)
        self.assertEqual(blend.poisson_solver, 'cg')
        self.assertEqual(blend.poisson_maxiter, 17)
        self.assertEqual(blend.poisson_grad_weight_l, 3)
        self.assertEqual(blend.poisson_grad_weight_ab, .25)

    def test_grayscale_guides_gain_channel_axis_without_changing_values(self):
        gray = np.arange(20, dtype=np.uint8).reshape(4, 5)
        source, target, weight = native_guides([(gray, gray[:, ::-1], .25)])[0]
        self.assertEqual(source.shape, (4, 5, 1))
        np.testing.assert_array_equal(target[:, :, 0], gray[:, ::-1])
        self.assertTrue(target.flags.c_contiguous)
        self.assertEqual(weight, .25)

    def test_namespace_collision_is_rejected(self):
        runtime = dict(engine=FUOUM, revision=FUOUM_REVISION, source=str(ROOT), python=sys.executable)
        with patch('reezsynth_engines.prepare_runtime', return_value=runtime), \
             patch.dict(sys.modules, {'ezsynth': types.ModuleType('ezsynth')}), \
             self.assertRaisesRegex(RuntimeError, 'both ezsynth'):
            activate_fuoum(runtime)


class EngineGuiTests(GuiFixture):
    def test_flow_models_and_grouped_gpu_controls_follow_the_selected_engine(self):
        w = self.window()
        o = w.options
        controls = o.widgets['render']
        controls['flow_model'].setCurrentText('kitti')
        controls['engine'].setCurrentText(FUOUM)
        controls['fuoum_raft_model'].setCurrentText('sintel')
        self.assertFalse(controls['flow_model'].isEnabled())
        self.assertTrue(controls['fuoum_raft_model'].isEnabled())
        self.assertFalse(w.grouped.poisson_gpu.isEnabled())
        controls['fuoum_flow_engine'].setCurrentText('NeuFlow')
        self.assertFalse(controls['fuoum_raft_model'].isEnabled())
        self.assertTrue(controls['fuoum_neuflow_model'].isEnabled())
        o.store.save('render', 'Flow split', o.snapshot('render'))
        controls['engine'].setCurrentText(LEGACY)
        self.assertEqual(controls['flow_model'].currentText(), 'kitti')
        self.assertFalse(controls['fuoum_neuflow_model'].isEnabled())
        o.apply('render', o.store.groups['render']['Flow split'])
        self.assertEqual(o.render()['fuoum_flow_engine'], 'NeuFlow')
        self.assertEqual(o.render()['fuoum_raft_model'], 'sintel')
        self.assertFalse(w.grouped.poisson_gpu.isEnabled())

    def test_engine_and_options_round_trip_in_presets(self):
        w = self.window()
        o = w.options
        o.widgets['render']['engine'].setCurrentText(FUOUM)
        o.widgets['render']['temporal_nnf'].setChecked(False)
        o.video_export_enabled.setChecked(True)
        o.video_export_fps.setValue(23.976)
        o.video_export_audio.setText('separate-audio.wav')
        snapshot = o.snapshot('render')
        o.store.save('render', 'FuouM', snapshot)
        o.apply('render', dict(options=RENDER))
        o.apply('render', o.store.groups['render']['FuouM'])
        self.assertEqual(o.render()['engine'], FUOUM)
        self.assertFalse(o.render()['temporal_nnf'])
        self.assertEqual(o.snapshot('render')['video_export'],
                         {'enabled': True, 'fps': 23.976, 'audio': 'separate-audio.wav'})
        self.assertFalse(o.widgets['render']['memory_efficient_raft'].isEnabled())
        self.assertFalse(o.widgets['render']['fuoum_vote_mode'].isHidden())
        self.assertTrue(o.widgets['application']['fuoum_source'].isEnabled())
        self.assertTrue(o.widgets['application']['fuoum_python'].isEnabled())
        self.assertTrue(all(not button.isEnabled() for button in o.optional_flow_buttons))
        o.widgets['render']['engine'].setCurrentText(LEGACY)
        self.assertTrue(o.widgets['render']['memory_efficient_raft'].isEnabled())
        self.assertFalse(o.widgets['render']['fuoum_vote_mode'].isEnabled())
        self.assertFalse(o.widgets['application']['fuoum_source'].isEnabled())
        self.assertFalse(o.widgets['application']['fuoum_python'].isEnabled())
        self.assertTrue(all(button.isEnabled() for button in o.optional_flow_buttons))

    def test_engine_selector_locks_during_render(self):
        w = self.window()
        w.set_busy(True)
        self.assertFalse(w.options.widgets['render']['engine'].isEnabled())
        w.set_busy(False)
        self.assertTrue(w.options.widgets['render']['engine'].isEnabled())


class EngineRoutingTests(LifecycleFixture):
    def fuoum(self):
        self.w.options.widgets['render']['engine'].setCurrentText(FUOUM)
        runtime = dict(engine=FUOUM, revision=FUOUM_REVISION, python=sys.executable, source=str(self.root))
        self.enterContext(patch('reezsynth_engines.prepare_runtime', return_value=runtime))
        self.enterContext(patch('reezsynth_engines.preflight_flow'))
        return runtime

    def test_selected_runtime_is_frozen_in_jobs_and_shared_queue_completes(self):
        runtime = self.fuoum()
        self.run_queue(shared=True)
        self.until(lambda: not self.w.busy, 10)
        jobs = list(self.w.batch.rglob('job.json'))
        self.assertEqual(len(jobs), 2)
        for path in jobs:
            job = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(job['engine_runtime'], runtime)
            self.assertEqual(job['render_options']['engine'], FUOUM)
            self.assertTrue((path.parent / 'COMPLETE.txt').is_file())
        self.assertIsNone(self.w.process)

    def test_selected_runtime_completes_parallel_queue(self):
        self.fuoum()
        self.w.options.widgets['application']['parallel'].setChecked(True)
        self.run_queue(shared=False)
        self.until(lambda: not self.w.busy, 10)
        self.assertEqual(self.w.queue_mode, 'parallel')
        self.assertEqual(len(list(self.w.batch.rglob('COMPLETE.txt'))), 2)
        self.assertIsNone(self.w.parallel_queue)

    def test_disabled_legacy_settings_are_retained_but_excluded_from_fuoum_jobs(self):
        self.fuoum()
        self.w.options.widgets['render']['memory_efficient_raft'].setChecked(True)
        from test_reezsynth_gui import gui
        self.run_queue()
        self.until(lambda: not self.w.busy, 10)
        jobs = list(self.w.batch.rglob('job.json'))
        self.assertTrue(jobs)
        self.assertTrue(self.w.options.widgets['render']['memory_efficient_raft'].isChecked())
        self.assertTrue(all(not json.loads(p.read_text())['render_options']['memory_efficient_raft'] for p in jobs))


class FrameCorrespondenceTests(unittest.TestCase):
    def test_poisson_matrix_matches_pixel_differences_without_wrapping_rows(self):
        from reezsynth_fuoum_pipeline import poisson_matrices
        for h, w in ((3, 5), (5, 3), (1, 4), (4, 1)):
            pixels = np.arange(h * w, dtype=float).reshape(h, w) ** 2
            gx, gy = np.zeros_like(pixels), np.zeros_like(pixels)
            gx[:-1] = pixels[:-1] - pixels[1:]
            gy[:, :-1] = pixels[:, :-1] - pixels[:, 1:]
            for weight, matrix in zip((2.5, .5, 0), poisson_matrices(h, w, (2.5, .5, 0))):
                expected = np.concatenate((gx.ravel() * weight, gy.ravel() * weight, pixels.ravel()))
                np.testing.assert_allclose(matrix @ pixels.ravel(), expected)

    def test_old_raft_model_migrates_and_separate_fuoum_selection_is_preserved(self):
        self.assertEqual(validate_render({'flow_model': 'kitti'})['fuoum_raft_model'], 'kitti')
        self.assertEqual(validate_render({'flow_model': 'kitti', 'fuoum_raft_model': 'sintel'})['fuoum_raft_model'], 'sintel')

    def test_all_direction_modes_preserve_keys_and_cover_frames_with_aligned_errors(self):
        from reezsynth_fuoum_pipeline import run_sequences, work_count
        for count, keys in ((9, [2, 4, 6]), (4, [0, 1, 3]), (6, [3]), (3, [0, 2])):
            for mode in ('none', 'forward', 'reverse'):
                calls = []
                class Pipeline:
                    _fwd_flows = list(range(count - 1))
                    def _run_a_pass(self, seq, style_img, is_forward, content_frames):
                        a, b = seq.start_frame, seq.end_frame
                        targets = list(range(a + 1, b + 1) if is_forward else range(a, b))
                        calls.extend(targets)
                        return list(range(a, b + 1)), targets, list(range(a, b)), []
                def blend(fwd, rev, ea, eb, flows):
                    self.assertEqual(fwd, rev)
                    self.assertEqual(ea, fwd)
                    self.assertEqual(eb, fwd)
                    return fwd
                result = run_sequences(Pipeline(), list(range(count)), [100 + k for k in keys], keys,
                                       mode, blend, lambda *a: None)
                self.assertEqual(result, [100 + n if n in keys else n for n in range(count)])
                self.assertEqual(len(calls), work_count(count, keys, mode))

    def test_older_lsmr_preset_migrates_without_changing_fuoum_solver(self):
        from reezsynth_video_plan import validate_blend_options
        self.assertEqual(validate_blend_options({'use_lsqr': False})['fuoum_poisson_solver'], 'lsmr')


if __name__ == '__main__':
    unittest.main()
