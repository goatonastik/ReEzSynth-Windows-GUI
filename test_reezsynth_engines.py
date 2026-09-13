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
from reezsynth_fuoum import (build_configs, install_final_pass_compatibility,
                             native_guides, render_cache)
from reezsynth_engine_setup import (configured_runtime, readiness_command,
                                    rebuild_command, version_summary)
from test_reezsynth_gui import GuiFixture
from test_reezsynth_lifecycle import LifecycleFixture
from diagnose_reezsynth_release import selected_keyframes


class EngineTests(unittest.TestCase):
    def test_short_painting_diagnostic_uses_enough_grouped_keyframes(self):
        frames = [[100, 'a'], [101, 'b'], [102, 'c']]
        self.assertEqual(selected_keyframes(frames, [100], 'painting'), [100, 101, 102])
        self.assertEqual(selected_keyframes(frames, [100, 106], 'painting'), [100, 106])

    def test_engine_setup_commands_use_configured_pinned_runtimes(self):
        application = {'fuoum_source': 'D:/custom/source',
                       'fuoum_python': 'D:/custom/venv/Scripts/python.exe'}
        source, worker = configured_runtime(application)
        self.assertEqual(source, Path('D:/custom/source'))
        self.assertEqual(worker, Path('D:/custom/venv/Scripts/python.exe'))
        program, arguments = readiness_command(application)
        self.assertEqual(program, sys.executable)
        self.assertIn(str(source), arguments)
        self.assertIn(str(worker), arguments)
        legacy_program, legacy_arguments = rebuild_command('legacy', application)
        self.assertEqual(legacy_program, sys.executable)
        self.assertIn('--install', legacy_arguments)
        fuoum_program, fuoum_arguments = rebuild_command('fuoum', application)
        self.assertEqual(fuoum_program, str(worker))
        self.assertIn('--force', fuoum_arguments)
        summary = version_summary(application)
        self.assertIn(FUOUM_REVISION, summary)
        self.assertIn(str(source), summary)

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

    def test_fuoum_final_pass_missing_modes_are_repaired_and_restorable(self):
        calls = []
        backend = types.SimpleNamespace(run_level=lambda *args, **kwargs: calls.append((args, kwargs)))
        config = types.SimpleNamespace(vote_mode='weighted', cost_function='ncc')
        engine = types.SimpleNamespace(
            backend=backend, ebsynth_config=config,
            vote_mode_map={'weighted': 7}, cost_function_map={'ncc': 9})
        original = install_final_pass_compatibility(engine)
        arguments = list(range(16))
        arguments[9] = arguments[14] = None
        backend.run_level(*arguments)
        self.assertEqual(calls[0][0][9], 7)
        self.assertEqual(calls[0][0][14], 9)
        self.assertEqual(calls[0][1], {})
        backend.run_level(*range(16))
        self.assertEqual(calls[1], (tuple(range(16)), {}))
        backend.run_level(vote_mode=None, cost_function_mode=None)
        self.assertEqual(calls[2][1], {'vote_mode': 7, 'cost_function_mode': 9})
        backend.run_level = original
        self.assertIs(backend.run_level, original)

    def test_image_synthesis_repairs_final_pass_and_restores_after_failure(self):
        from reezsynth_fuoum import synthesize_image
        def strict_level(*args, **kwargs):
            self.assertEqual(args[9], 7)
            self.assertEqual(args[14], 9)
            raise RuntimeError('native failure')
        engine = types.SimpleNamespace(
            backend=types.SimpleNamespace(run_level=strict_level),
            ebsynth_config=types.SimpleNamespace(vote_mode='weighted', cost_function='ssd'),
            vote_mode_map={'weighted': 7}, cost_function_map={'ssd': 9})
        engine.run = lambda *args, **kwargs: engine.backend.run_level(*([None] * 16))
        module = types.SimpleNamespace(EbsynthEngine=lambda *args: engine)
        with patch.dict(sys.modules, {'ezsynth.engines.synthesis_engine': module}), \
             patch('reezsynth_fuoum.build_configs', return_value=(None, None, None)), \
             self.assertRaisesRegex(RuntimeError, 'native failure'):
            synthesize_image(None, [], {})
        self.assertIs(engine.backend.run_level, strict_level)

    def test_fuoum_render_cache_is_writable_and_cleaned(self):
        with render_cache(ROOT) as cache:
            cache = Path(cache)
            (cache / 'probe').write_text('ok', encoding='utf-8')
            self.assertTrue((cache / 'probe').is_file())
        self.assertFalse(cache.exists())

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
        controls['fuoum_bidirectional_flow'].setChecked(True)
        controls['stream_frames'].setChecked(True)
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
        self.assertTrue(o.render()['fuoum_bidirectional_flow'])
        self.assertTrue(o.render()['stream_frames'])
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
    def test_bidirectional_warp_uses_target_grid_not_negated_source_grid(self):
        from reezsynth_flow import pull_warp
        x = np.tile(np.arange(20, dtype=np.float32), (4, 1))
        source = x ** 2
        # Forward map x -> 2*x has displacement x on the source grid.
        # The true inverse map on the target grid is x -> x/2.
        backward = np.stack((-x / 2, np.zeros_like(x)), axis=-1)
        expected = np.tile(np.interp(np.arange(20) / 2, np.arange(20), np.arange(20) ** 2), (4, 1))
        np.testing.assert_allclose(pull_warp(source, backward), expected)
        wrong = pull_warp(source, np.stack((-x, np.zeros_like(x)), axis=-1))
        self.assertGreater(float(np.abs(wrong - expected).mean()), 10)

    def test_bidirectional_pass_accumulates_coordinates_and_aligns_reverse_errors(self):
        from reezsynth_flow import run_bidirectional_pass
        frames = [np.zeros((4, 12, 3), np.uint8) for _ in range(3)]
        style = np.tile(np.arange(12, dtype=np.uint8), (4, 1))[..., None].repeat(3, axis=2)
        fwd = [np.full((4, 12, 2), (2, 0), np.float32) for _ in range(2)]
        bwd = [np.full((4, 12, 2), (-1, 0), np.float32) for _ in range(2)]
        calls = []
        def guides(**kwargs):
            calls.append(kwargs)
            return kwargs
        def synthesize(style, guides, initial_nnf, output_nnf):
            if initial_nnf is not None:
                np.testing.assert_array_equal(initial_nnf[1, 6], [5, 1])
            y, x = np.mgrid[:4, :12]
            nnf = np.stack((x, y), axis=-1).astype(np.int32)
            return guides['warped_previous_style'], np.full((4, 12), guides['target_idx']), nnf
        pipeline = types.SimpleNamespace(_fwd_flows=fwd, _bwd_flows=bwd,
            config=types.SimpleNamespace(pipeline=types.SimpleNamespace(use_temporal_nnf_propagation=True)),
            _prepare_guides_for_frame=guides, synthesis_engine=types.SimpleNamespace(run=synthesize))
        seq = types.SimpleNamespace(start_frame=0, end_frame=2)
        output = run_bidirectional_pass(pipeline, seq, style, True, frames)
        self.assertEqual(output[0][-1][1, 6, 0], 4)
        self.assertEqual(calls[-1]['target_pos_guide'][1, 6, 0], int(4 / 11 * 255))
        pipeline.config.pipeline.use_temporal_nnf_propagation = False
        pipeline.synthesis_engine.run = lambda style, guides, **kw: (
            guides['warped_previous_style'], np.full((4, 12), guides['target_idx']))
        output = run_bidirectional_pass(pipeline, seq, style, False, frames)
        self.assertEqual(output[0][0][1, 3, 0], 7)
        self.assertEqual([int(error[0, 0]) for error in output[1]], [0, 1])
        self.assertIs(output[2][0], fwd[0])

    def test_fuoum_directional_cache_reuses_each_order_and_only_computes_missing_pairs(self):
        from reezsynth_fuoum_pipeline import extend_pipeline
        frames = [np.full((4, 5, 3), v, np.uint8) for v in (10, 20, 30)]
        config = types.SimpleNamespace(precomputation=types.SimpleNamespace(flow_engine='RAFT',
            flow_model='sintel', edge_method='Classic'))
        calls = []
        class Pipeline:
            def __init__(self, config, data):
                self.config = config
        class Flow:
            def __init__(self, **kwargs):
                pass
            def compute(self, pair):
                a, b = (int(f[0, 0, 0]) for f in pair)
                calls.append((a, b))
                return [np.full((4, 5, 2), b - a, np.float32)]
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(sys.modules, {
                 'ezsynth.pipeline': types.SimpleNamespace(SynthesisPipeline=Pipeline),
                 'ezsynth.engines.flow_engine': types.SimpleNamespace(RAFTFlowEngine=Flow, NeuFlowEngine=Flow),
                 'torch': types.SimpleNamespace(cuda=types.SimpleNamespace(empty_cache=lambda: None))}), \
             patch('reezsynth_precompute_cache.flow_identity', return_value={'model': 'fixture'}):
            data = types.SimpleNamespace(_content_frames=frames)
            def compute():
                instance = extend_pipeline(config, data, [], [], 0, 'none', lambda *a: None,
                    cache_job={'precompute_cache': directory}, bidirectional=True)
                instance._compute_optical_flow(frames)
                for value in instance._fwd_flows + instance._bwd_flows:
                    value._mmap.close()
            compute()
            compute()
            self.assertEqual(calls, [(10, 20), (20, 10), (20, 30), (30, 20)])
            frames[2] = np.full((4, 5, 3), 40, np.uint8)
            compute()
            self.assertEqual(calls[-2:], [(20, 40), (40, 20)])
            self.assertEqual(len(calls), 6)

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
