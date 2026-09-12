"""Grouped video contracts using temporary files and upstream orchestration, no GPU."""
import ast
import contextlib
import io
import itertools
import json
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import test_reezsynth_render_adapter as adapter
from test_reezsynth_lifecycle import LifecycleFixture, gui
from reezsynth_video_plan import (check_blend_dependencies, plan_grouped_video,
                                  synthesis_work, validate_blend_options)

ROOT = Path(__file__).resolve().parent


def upstream_engine(captured):
    # Execute the live upstream sequence/pass methods, replacing only expensive
    # initialization, optical flow, native synthesis and blend reconstruction.
    ns = dict(np=np, time=time)
    exec(compile((ROOT / 'ezsynth/sequences.py').read_text(), 'sequences.py', 'exec'), ns)
    ns.update(tqdm=types.SimpleNamespace(tqdm=lambda items, *a, **k: items),
              Warp=lambda image: None,
              PositionalGuide=lambda: types.SimpleNamespace(create_from_flow=lambda *a: None))
    tree = ast.parse((ROOT / 'ezsynth/aux_run.py').read_text())
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)] + functions, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), 'aux_run.py', 'exec'), ns)
    ns['get_flow'] = lambda *a: None
    ns['get_warped_img'] = lambda *a: None
    def blend(images, forward, backward, errors_f, errors_b, flows, cfg):
        result = forward[:-1]
        if not cfg.skip_blend_style_last:
            result.append(backward[-1])
        return result, errors_f, flows
    ns['run_blend'] = blend
    tree = ast.parse((ROOT / 'ezsynth/main_ez.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'EzsynthBase')
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and
                (n.name.startswith('run_sequences') or n.name.startswith('_should_'))]
    module.body = [module.body[0], cls]
    exec(compile(ast.fix_missing_locations(module), 'main_ez.py', 'exec'), ns)
    class Engine(ns['EzsynthBase']):
        def __init__(self, **kwargs):
            captured['engine'] = kwargs
            self.cfg = kwargs['cfg']
            self.img_frs_seq = kwargs['img_frs_seq']
            self.style_frs = kwargs['style_frs']
            self.len_img = len(self.img_frs_seq)
            self.edge_guides = self.img_frs_seq
            self.rafter = None
            self.sequences, self.atlas = ns['SequenceManager'](0, self.len_img - 1,
                len(self.style_frs), kwargs['style_idxes'], list(range(self.len_img))).create_sequences()
            self.num_seqs = len(self.sequences)
            captured['calls'] = 0
            def run(style, **kwargs):
                captured['calls'] += 1
                return style, None
            self.eb = types.SimpleNamespace(run=run, backends={'cuda': 17}, backend=None)
    return Engine


class PlanningTests(unittest.TestCase):
    def test_gpu_blending_requires_a_usable_cupy_kernel(self):
        enabled = {'only_mode': 'none', 'use_gpu': True}
        with patch('reezsynth_video_plan.importlib.util.find_spec', return_value=object()):
            check_blend_dependencies(enabled, probe=lambda: 1)
            with self.assertRaisesRegex(ValueError, 'usable CuPy/CUDA kernel'):
                check_blend_dependencies(enabled, probe=lambda: (_ for _ in ()).throw(RuntimeError('no kernel image')))

    def test_invalid_selection_and_blend_settings(self):
        for selection in ({'keyframes': [0]}, {'keyframes': [0, 0]}, {'start': 1, 'end': 2}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                plan_grouped_video({i: str(i) for i in range(3)}, {0: 'a', 2: 'b'}, selection)
        for options in ({'only_mode': 'blend'}, {'use_gpu': 1}, {'poisson_maxiter': 0}, {'use_poisson_cupy': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                validate_blend_options(options)

    def test_work_count_matches_live_upstream_boundaries(self):
        captured = {}
        Engine = upstream_engine(captured)
        frames = [np.zeros((2, 2, 3))] * 6
        with contextlib.redirect_stdout(io.StringIO()):
            for length in range(2, 7):
                for size in range(2, length + 1):
                    for keys in itertools.combinations(range(length), size):
                        for mode in ('none', 'forward', 'reverse'):
                            cfg = types.SimpleNamespace(only_mode=mode, do_mask=False,
                                edg_wgt=1, img_wgt=1, pos_wgt=1, wrp_wgt=1)
                            runner = Engine(cfg=cfg, img_frs_seq=frames[:length],
                                            style_frs=[frames[0]] * size, style_idxes=list(keys))
                            result, _ = runner.run_sequences()
                            self.assertEqual(len(result), length, (length, keys, mode))
                            self.assertEqual(captured['calls'], synthesis_work(0, length-1, keys, mode))


class GroupedAdapterTests(unittest.TestCase):
    setUp = adapter.RenderAdapterTests.setUp
    run_job = adapter.RenderAdapterTests.run_job
    fake_engine = adapter.RenderAdapterTests.fake_engine

    def test_grouped_modes_use_live_sequence_methods_and_original_numbers(self):
        captured = {}
        Engine = upstream_engine(captured)
        self.fake_engine()
        with patch.dict(sys.modules, {'ezsynth.main_ez': types.SimpleNamespace(EzsynthBase=Engine),
                                     'ezsynth.aux_classes': types.SimpleNamespace(RunConfig=lambda **kw: types.SimpleNamespace(**kw))}):
            for mode in ('none', 'forward', 'reverse'):
                self.job.update(plan_grouped_video(
                    {i: self.frames[0][1] for i in range(10, 16)},
                    {11: self.job['style'], 13: self.job['style']},
                    blend_options={'only_mode': mode, 'use_lsqr': False, 'poisson_maxiter': 27}))
                self.job['synthesis_work'] = 999  # Worker recomputes rather than trusts this.
                self.run_job()
                self.assertEqual(captured['engine']['style_idxes'], [1, 3])
                self.assertEqual(captured['engine']['cfg'].poisson_maxiter, 27)
                self.assertEqual(len(list(self.output.glob('*.png'))), 6)
                self.assertTrue((self.output / '015.png').exists())

    def test_duplicate_styles_rejected_without_completion(self):
        self.job.update(type='grouped_video', styles=[[0, self.job['style']]] * 2)
        with self.assertRaises(ValueError):
            self.run_job()
        self.assertFalse((self.output / 'COMPLETE.txt').exists())


class GroupedGuiTests(LifecycleFixture):
    def test_grouped_completion_both_worker_modes_preserves_independent_rows(self):
        self.w.rows[0]['folder'].setText('manual')
        for shared in (True, False):
            self.w.reuse_worker.setChecked(shared)
            self.w.run_rows([], grouped=True)
            self.until(lambda: not self.w.busy)
            self.assertEqual(self.w.grouped.state.text(), 'Complete')
            self.assertEqual(self.w.overall.value(), 100)
            jobs = list(self.w.batch.rglob('job.json'))
            self.assertEqual(len(jobs), 1)
            data = json.loads(jobs[0].read_text())
            self.assertEqual([n for n, _ in data['styles']], [0, 2])
            self.assertEqual(data['synthesis_work'], 4)
            self.assertEqual(self.w.rows[0]['folder'].text(), 'manual')

    def test_cancel_grouped_then_restart_independent(self):
        self.mode('slow')
        self.w.run_rows([], grouped=True)
        self.until(lambda: 'MOCK_STARTED' in self.w.log.toPlainText())
        self.w.stop_queue()
        self.until(lambda: not self.w.busy)
        self.assertIsNone(self.w.process)
        self.mode('normal')
        self.run_queue()
        self.until(lambda: not self.w.busy)
        self.assertTrue(all(r['state'].text() == 'Complete' for r in self.w.rows))

    def test_project_and_render_preset_round_trip_and_legacy_defaults(self):
        w = self.w
        w.grouped.set_blend_options({'only_mode': 'reverse', 'use_lsqr': False})
        w.grouped.folder.setText('custom/group')
        preset = w.options.snapshot('render')
        w.project_file = self.root / 'project.json'
        w.save_project()
        data = json.loads(w.project_file.read_text())
        for legacy in (False, True):
            if legacy:
                data.pop('blend_options')
                data.pop('grouped_video')
                w.project_file.write_text(json.dumps(data))
            with patch.object(gui.QFileDialog, 'getOpenFileName', return_value=(str(w.project_file), '')):
                w.open_project()
            self.assertEqual(w.grouped.blend_options()['only_mode'], 'none' if legacy else 'reverse')
            self.assertEqual(w.grouped.folder.text(), 'grouped_video' if legacy else 'custom/group')
        w.options.apply('render', preset)
        self.assertEqual(w.grouped.blend_options()['only_mode'], 'none')


if __name__ == '__main__':
    unittest.main(verbosity=2)
