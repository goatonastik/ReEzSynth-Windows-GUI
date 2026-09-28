"""Comparison contracts without GPU renders."""
import json
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from reezsynth_comparison import comparison_plans, render_comparison_sheet, sample_frames, remap_sheet_dependencies
from reezsynth_engines import FUOUM, file_sha256
from reezsynth_config import atomic_json
from reezsynth_queue_recovery import snapshot_inputs
from unittest.mock import patch
from test_reezsynth_gui import GuiFixture

class ComparisonTests(unittest.TestCase):
    def plans(self, kind='flow', **blend):
        return comparison_plans({n: f'frame{n}.png' for n in range(5)},
            {0: 'key0.png', 4: 'key4.png'}, 0, 4, kind, {'engine': FUOUM}, blend)

    def test_single_factor_and_snapshots(self):
        plans = self.plans()
        left, right = [p['render_options'] for p in plans]
        self.assertEqual([k for k in left if left[k] != right[k]], ['fuoum_flow_engine'])
        plans[0]['plan']['frames'].clear()
        self.assertEqual(len(plans[1]['plan']['frames']), 5)

    def test_templates(self):
        for kind, count in [('flow', 2), ('directions', 2), ('backend', 2), ('reconstruction', 3)]:
            self.assertEqual(len(self.plans(kind)), count)
        self.assertEqual([p['plan']['blend_options']['poisson_maxiter'] for p in
            self.plans('reconstruction', fuoum_poisson_solver='amg')], [None] * 3)

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.plans('reconstruction', only_mode='forward')
        with self.assertRaises(ValueError):
            comparison_plans({0: 'a', 1: 'b'}, {0: 'a', 1: 'b'}, 0, 1, 'flow', {'engine': FUOUM}, {})

    def test_sampling(self):
        self.assertEqual(sample_frames(range(64)), [0, 9, 18, 27, 36, 45, 54, 63])

    def test_range_uses_only_keys_inside_selection(self):
        plans = comparison_plans({n: f'frame{n}.png' for n in range(9)},
            {n: f'key{n}.png' for n in (0, 2, 4, 8)}, 2, 4, 'flow', {'engine': FUOUM}, {})
        self.assertEqual([n for n, _ in plans[0]['plan']['styles']], [2, 4])

    def test_sheet_and_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames = []
            for n in range(3):
                path = root / f'source{n}.png'
                cv2.imwrite(str(path), np.full((12, 16, 3), 40, np.uint8))
                frames.append([n, str(path)])
            variants = []
            for index in range(2):
                output = root / f'variant{index}'; output.mkdir()
                for n, _ in frames:
                    cv2.imwrite(str(output / f'{n:03}.png'), np.full((12, 16, 3), 80, np.uint8))
                atomic_json(output / 'job.json', dict(output=str(output), frames=frames))
                atomic_json(output / 'engine_manifest.json', dict(effective_settings={'variant': index}))
                (output / 'COMPLETE.txt').write_text('done')
                path = output / 'job.json'
                variants.append(dict(label=f'Variant {index}', job=str(path), job_sha256=file_sha256(path)))
            sheet = root / 'sheet'; sheet.mkdir()
            job = dict(output=str(sheet), frames=frames, comparison_kind='flow', comparison_variants=variants)
            snapshot = snapshot_inputs(job, sheet / 'job.json')
            self.assertEqual(len(snapshot), 5)
            self.assertFalse(any(e.get('missing') for e in snapshot))
            render_comparison_sheet(job, lambda *args: None)
            self.assertTrue((sheet / 'COMPLETE.txt').is_file())
            self.assertEqual(cv2.imread(str(sheet / 'contact_sheet.png')).shape[1], 768)
            self.assertEqual(json.loads((sheet / 'comparison_manifest.json').read_text())['sampled_frames'], [0, 1, 2])
            fresh = root / 'fresh.json'; atomic_json(fresh, {'output': 'fresh'})
            mapped = remap_sheet_dependencies(job, {str(Path(variants[0]['job']).resolve()): str(fresh)})
            self.assertEqual(mapped['comparison_variants'][0]['job_sha256'], file_sha256(fresh))
            self.assertNotEqual(mapped['comparison_variants'], job['comparison_variants'])
            (root / 'variant0' / 'COMPLETE.txt').unlink()
            (sheet / 'COMPLETE.txt').unlink()
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                render_comparison_sheet(job, lambda *args: None)
            self.assertFalse((sheet / 'COMPLETE.txt').exists())
            Path(variants[0]['job']).unlink()
            with self.assertRaisesRegex(ValueError, 'missing or outside'):
                render_comparison_sheet(job, lambda *args: None)

class ComparisonGuiTests(GuiFixture):
    def test_queue_snapshots_and_isolation(self):
        from reezsynth_comparison_controls import submit_comparison
        window = self.window()
        window.project_dir.setEditText(str(self.root))
        video, keys = {}, {}
        for n in range(3):
            path = self.root / f'frame{n}.png'
            cv2.imwrite(str(path), np.zeros((16, 16, 3), np.uint8))
            video[n] = path
        keys[0] = video[0]
        keys[2] = video[2]
        window.options.widgets['render']['engine'].setCurrentText(FUOUM)
        captured = []
        def start(records, batch, shared, parallel, script, application):
            captured.extend(records)
            self.assertFalse(shared)
            self.assertFalse(parallel)
            window.busy = True
        with patch('reezsynth_engines.prepare_runtime', return_value={'engine': FUOUM, 'python': 'python.exe'}), \
             patch('reezsynth_engines.preflight_flow'), patch('reezsynth_engines.validate_capabilities'), \
             patch.object(window, 'start_records', side_effect=start):
            batch = submit_comparison(window, video, keys, 3, 0, 2, 'directions')
        window.busy = False
        self.assertEqual(len(captured), 3)
        jobs = [json.loads(record['job_path'].read_text()) for record in captured]
        self.assertFalse(jobs[0]['render_options']['fuoum_bidirectional_flow'])
        self.assertTrue(jobs[1]['render_options']['fuoum_bidirectional_flow'])
        self.assertEqual(jobs[2]['type'], 'comparison_sheet')
        self.assertEqual(Path(jobs[2]['output']).parent, batch)
        self.assertEqual(jobs[0]['exports'], {})
        window.options.refresh_engine_controls()
        self.assertFalse(window.options.comparison_open.isEnabled())

    def test_guard_blocks_maintenance(self):
        from reezsynth_comparison_controls import submit_comparison
        window = self.window()
        with patch.object(window.options, 'installation_active', return_value=True):
            with self.assertRaisesRegex(ValueError, 'component operation'):
                submit_comparison(window, {}, {}, 3, 0, 2, 'flow')
