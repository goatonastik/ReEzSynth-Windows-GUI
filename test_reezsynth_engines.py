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
        for field, value in (('ebsynth_backend', 'cpu'), ('do_mask', True),
                              ('custom_edge_guides', True), ('memory_efficient_raft', True),
                              ('flow_arch', 'EF_RAFT')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_capabilities(dict(options, **{field: value}))
        for extras in ({'exports': {'maps': True}}, {'blend': {'use_gpu': True}},
                       {'blend': {'only_mode': 'forward'}}):
            with self.subTest(extras=extras), self.assertRaises(ValueError):
                validate_capabilities(options, **extras)
        validate_capabilities(dict(options, do_mask=True), image=True)

    def test_native_mapping_uses_actual_solver_and_positive_pyramid_depth(self):
        class StrictNative:
            def __init__(self, uniformity, patch_size, search_vote_iters, patch_match_iters,
                         extra_pass_3x3, backend, edge_weight, image_weight, pos_weight, warp_weight):
                self.__dict__.update(locals())
        class StrictPipeline:
            def __init__(self, pyramid_levels, use_temporal_nnf_propagation, use_sparse_feature_guide):
                self.__dict__.update(locals())
        class StrictBlend:
            def __init__(self, poisson_solver, poisson_maxiter):
                self.__dict__.update(locals())
        schema = types.SimpleNamespace(EbsynthParamsConfig=StrictNative,
                                       PipelineConfig=StrictPipeline, BlendingConfig=StrictBlend)
        with patch.dict(sys.modules, {'ezsynth.config': schema}):
            native, pipeline, blend = build_configs(dict(RENDER, engine=FUOUM, pyramidlevels=-1),
                                                    {'key_wgt': 2, 'img_wgt': 8},
                                                    {'use_lsqr': False, 'poisson_maxiter': 17})
        self.assertEqual(native.image_weight, 4)
        self.assertEqual(native.backend, 'cuda')
        self.assertEqual(pipeline.pyramid_levels, 32)
        self.assertEqual(blend.poisson_solver, 'lsmr')
        self.assertEqual(blend.poisson_maxiter, 17)

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
    def test_engine_and_options_round_trip_in_presets(self):
        w = self.window()
        o = w.options
        o.widgets['render']['engine'].setCurrentText(FUOUM)
        o.widgets['render']['temporal_nnf'].setChecked(False)
        snapshot = o.snapshot('render')
        o.store.save('render', 'FuouM', snapshot)
        o.apply('render', dict(options=RENDER))
        o.apply('render', o.store.groups['render']['FuouM'])
        self.assertEqual(o.render()['engine'], FUOUM)
        self.assertFalse(o.render()['temporal_nnf'])
        self.assertFalse(o.widgets['render']['memory_efficient_raft'].isEnabled())
        o.widgets['render']['engine'].setCurrentText(LEGACY)
        self.assertTrue(o.widgets['render']['memory_efficient_raft'].isEnabled())

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

    def test_incompatible_engine_settings_create_no_outputs(self):
        self.fuoum()
        self.w.options.widgets['render']['memory_efficient_raft'].setChecked(True)
        from test_reezsynth_gui import gui
        with patch.object(gui.QMessageBox, 'warning') as warning:
            self.run_queue()
        self.assertIn('legacy memory-efficient', warning.call_args.args[2])
        self.assertFalse(self.w.busy)
        self.assertFalse(list(self.root.rglob('job.json')))


if __name__ == '__main__':
    unittest.main()
