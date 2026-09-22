"""Schedule schema, real legacy C-int boundary, and FuouM call sequencing."""
import ast
from ctypes import c_int
import json
from pathlib import Path
import tempfile
import types
import unittest

import numpy as np

from reezsynth_config import quality_profile, validate_render
from reezsynth_iterations import (expand_schedule, parse_schedule, resolve,
    legacy_schedule, fuoum_synthesize, ScheduleRecorder)
from test_reezsynth_gui import GuiFixture


class ScheduleTests(unittest.TestCase):
    def test_alignment_and_scalar_fallback(self):
        self.assertEqual(expand_schedule([12, 8, 4], 99, 2), [8, 4])
        self.assertEqual(expand_schedule([12, 8, 4], 99, 4), [12, 12, 8, 4])
        self.assertEqual(expand_schedule([], 6, 3), [6, 6, 6])
        self.assertEqual(expand_schedule([8, 4], 6, 1), [4])
        self.assertEqual(parse_schedule(' 12, 8, 4 '), [12, 8, 4])
        self.assertEqual(parse_schedule('  '), [])

    def test_reject_invalid_imports_and_editor_text(self):
        for value in (None, '1,2', [True], [1.5], [0], [-1], [1001], [2] * 33, [float('nan')]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_render(dict(searchvote_schedule=value))
        for value in ('1,', ',2', '1,,2', '1.5', '1e2', '0', '1001'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_schedule(value)
        a = validate_render()
        a['searchvote_schedule'].append(7)
        self.assertEqual(validate_render()['searchvote_schedule'], [])
        a = quality_profile('Standard')
        a['patchmatch_schedule'].append(7)
        self.assertEqual(quality_profile('Standard')['patchmatch_schedule'], [])

    def test_real_legacy_wrapper_arrays_clamping_and_restoration(self):
        # Load only the pure method, without importing torch or the DLL.
        tree = ast.parse((Path(__file__).parent / 'ezsynth/utils/_eb.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'EbsynthRunner')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'validate_per_levels')
        namespace = {'c_int': c_int}
        # Compile only the selected method parsed from this checkout's fixed source.
        exec(compile(ast.Module(body=[method], type_ignores=[]), '_eb.py', 'exec'), namespace)  # nosec B102
        runner = types.SimpleNamespace()
        original = types.MethodType(namespace['validate_per_levels'], runner)
        runner.validate_per_levels = original
        eb = types.SimpleNamespace(runner=runner)
        options = validate_render(dict(searchvote_schedule=[12, 8, 4], patchmatch_schedule=[6, 2]))
        recorder = ScheduleRecorder()
        with self.assertRaisesRegex(RuntimeError, 'native failure'):
            with legacy_schedule(eb, options, recorder):
                for requested, maximum, search, match in (
                    (-1, 4, [12, 12, 8, 4], [6, 6, 6, 2]),
                    (6, 2, [8, 4], [6, 2]), (1, 4, [4], [2])):
                    levels, a, b, stop = runner.validate_per_levels(requested, 12, 6, 5, maximum)
                    self.assertEqual(list(a), search)
                    self.assertEqual(list(b), match)
                    self.assertEqual(list(stop), [5] * levels)
                    self.assertIs(a._type_, c_int)
                raise RuntimeError('native failure')
        self.assertIs(runner.validate_per_levels, original)
        with legacy_schedule(eb, validate_render(), recorder):
            self.assertIs(runner.validate_per_levels, original)

    def test_fuoum_finest_polish_reset_forwarding_and_failure_cleanup(self):
        calls = []
        backend = types.SimpleNamespace(run_level=lambda *args, **kw: calls.append((args, kw)))
        original = backend.run_level
        style = np.zeros((128, 256, 3), np.uint8)
        guides = [(style, style, 1)]
        options = validate_render(dict(searchvote_schedule=[9, 5, 2], patchmatch_schedule=[4, 1]))
        engine = types.SimpleNamespace(backend=backend)
        def synthesize(style, guides, output_nnf=False):
            self.assertTrue(output_nnf)
            for _ in range(4):  # 128 pixels/patch 7 permits four levels.
                backend.run_level(*range(16))
            backend.run_level(search_vote_iters=99, patch_match_iters=98)
            return 'image', 'error', 'nnf'
        engine.run = synthesize
        for _ in range(2):
            result = fuoum_synthesize(engine, style, guides, options, ScheduleRecorder(), output_nnf=True)
            self.assertEqual(result, ('image', 'error', 'nnf'))
            self.assertIs(backend.run_level, original)
        self.assertEqual([call[0][10:12] for call in calls[:4]], [(9, 4), (9, 4), (5, 4), (2, 1)])
        self.assertEqual(calls[4][1], dict(search_vote_iters=2, patch_match_iters=1))
        self.assertEqual(calls[:5], calls[5:])
        for count in (3, 6):
            engine.run = lambda *a, **kw: [backend.run_level(*range(16)) for _ in range(count)]
            with self.assertRaisesRegex(RuntimeError, 'pyramid calls'):
                fuoum_synthesize(engine, style, guides, options, ScheduleRecorder())
            self.assertIs(backend.run_level, original)
        def failure(*args, **kwargs):
            raise ValueError('native failure')
        engine.run = failure
        with self.assertRaisesRegex(ValueError, 'native failure'):
            fuoum_synthesize(engine, style, guides, options, ScheduleRecorder())
        self.assertIs(backend.run_level, original)

    def test_manifest_records_unique_resolutions(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = ScheduleRecorder(directory)
            options = validate_render(dict(searchvote_schedule=[8, 4, 2]))
            for depth in (2, 2, 4):
                recorder.record(resolve(options, depth))
            data = json.loads((Path(directory) / 'iteration_schedule.json').read_text())
            self.assertEqual(data['alignment'], 'finest')
            self.assertEqual([p['searchvote'] for p in data['resolved']], [[4, 2], [8, 8, 4, 2]])

    def test_effective_provenance_omits_overridden_scalar_and_copy_schedule(self):
        from reezsynth_provenance import effective_settings
        for kind in ('image_synthesis', 'grouped_video'):
            data = effective_settings(dict(type=kind, frames=[[0, 'a'], [1, 'b']],
                render_options=dict(searchvote_schedule=[8, 4, 2])))
            self.assertNotIn('searchvoteiters', data['render_options'])
            self.assertEqual(data['render_options']['patchmatchiters'], 6)
            self.assertEqual(data['iteration_schedule']['file'], 'iteration_schedule.json')
        copy = effective_settings(dict(frames=[[0, 'a']], render_options=dict(searchvote_schedule=[8, 4])))
        self.assertNotIn('iteration_schedule', copy)


class ScheduleGuiTests(GuiFixture):
    def test_preset_roundtrip_engine_switch_and_quality_reset(self):
        w = self.window()
        options = w.options
        widgets = options.widgets['render']
        widgets['searchvote_schedule'].setText(' 12, 8, 4 ')
        widgets['patchmatch_schedule'].setText('6, 2')
        self.assertFalse(widgets['searchvoteiters'].isEnabled())
        settings = options.render()
        self.assertEqual(settings['searchvote_schedule'], [12, 8, 4])
        options.store.save('render', 'Schedule', options.snapshot('render'))
        from reezsynth_config import PresetStore
        reloaded = PresetStore(options.store.path)
        options.apply('render', reloaded.groups['render']['Schedule'])
        self.assertEqual(widgets['searchvote_schedule'].text(), '12, 8, 4')
        from reezsynth_engines import FUOUM, LEGACY
        for engine in (FUOUM, LEGACY):
            widgets['engine'].setCurrentText(engine)
            self.assertEqual(options.render()['searchvote_schedule'], [12, 8, 4])
        w.set_busy(True)
        self.assertFalse(widgets['searchvote_schedule'].isEnabled())
        w.set_busy(False)
        self.assertFalse(widgets['searchvoteiters'].isEnabled())
        widgets['searchvote_schedule'].setText('1,,2')
        with self.assertRaises(ValueError):
            options.render()
        options.quality_changed('Highest')
        self.assertEqual(options.render()['searchvote_schedule'], [])
        self.assertTrue(widgets['searchvoteiters'].isEnabled())


if __name__ == '__main__':
    unittest.main()
