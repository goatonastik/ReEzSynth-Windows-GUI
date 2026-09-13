"""Auxiliary output indexing, preservation, failure and GUI persistence tests."""
import contextlib
import io
import itertools
import json
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np
import test_reezsynth_render_adapter as adapter
from test_reezsynth_grouped import upstream_engine
from test_reezsynth_lifecycle import LifecycleFixture, gui
from reezsynth_artifacts import artifact_records, save_artifacts, validate_exports
from reezsynth_video_plan import plan_grouped_video


class MappingTests(unittest.TestCase):
    def test_matches_live_upstream_result_order_and_boundary_trimming(self):
        captured = {}
        Engine = upstream_engine(captured)
        ns = Engine.run_sequences_full.__globals__
        ns['get_flow'] = lambda images, raft, step, forward, i: np.full((2, 2, 3), min(i, i + step) + 10, np.uint8)
        ns['flow_to_image'] = lambda value, **kwargs: value
        frames = [np.full((2, 2, 3), i + 10, np.uint8) for i in range(6)]
        with contextlib.redirect_stdout(io.StringIO()):
            for length in range(1, 7):
                for size in range(1, length + 1):
                    for keys in itertools.combinations(range(length), size):
                        for mode in ('none', 'forward', 'reverse'):
                            cfg = types.SimpleNamespace(only_mode=mode, do_mask=False,
                                edg_wgt=1, img_wgt=1, pos_wgt=1, wrp_wgt=1)
                            runner = Engine(cfg=cfg, img_frs_seq=frames[:length],
                                style_frs=[frames[i] for i in keys], style_idxes=list(keys))
                            runner.eb.run = lambda style, guides: (style, guides[1][1][:, :, 0].astype(np.float32))
                            _, maps, flows = runner.run_sequences_full(return_flow=True)
                            records = artifact_records(list(range(10, 10 + length)), [k + 10 for k in keys], mode)
                            self.assertEqual(len(records), len(maps), (length, keys, mode))
                            self.assertEqual(len(records), len(flows))
                            for record, values, flow in zip(records, maps, flows):
                                self.assertTrue(np.all(flow == record['flow_from']))
                                # The mock blender returns forward-pass errors as its maps.
                                target = record.get('error_frame', record.get('forward_error_frame'))
                                self.assertTrue(np.all(values == target), (record, values))

    def test_rejects_unknown_or_nonboolean_settings(self):
        for data in ({'maps': 1}, {'raw_flow': True}, []):
            with self.assertRaises(ValueError):
                validate_exports(data)


class ExportAdapterTests(unittest.TestCase):
    setUp = adapter.RenderAdapterTests.setUp
    run_job = adapter.RenderAdapterTests.run_job
    fake_engine = adapter.RenderAdapterTests.fake_engine

    def test_numerical_maps_are_lossless_and_manifest_distinguishes_blending(self):
        records = artifact_records([10, 11, 12], [10, 12])
        values = [np.full((128, 128), 1.234567, np.float32)] * 2
        flows = [np.full((128, 128, 3), 42, np.uint8)] * 2
        save_artifacts(self.output, {'maps': True, 'flow': True}, records, values, flows)
        root = self.output / 'auxiliary'
        manifest = json.loads((root / 'manifest.json').read_text())
        entry = manifest['artifacts'][0]
        self.assertEqual(entry['map_kind'], 'selection_mask')
        self.assertNotIn('error_frame', entry)
        np.testing.assert_array_equal(np.load(root / entry['selection_mask']['file'], allow_pickle=False), values[0])
        self.assertTrue((root / entry['flow']['file']).exists())

    def test_requested_export_failure_prevents_completion_marker(self):
        captured = self.fake_engine()
        engine = sys.modules['ezsynth.main_ez'].EzsynthBase
        def full(runner, return_flow):
            results, _ = runner.run_sequences()
            return results, [], []
        engine.run_sequences_full = full
        self.job['exports'] = {'maps': True}
        with self.assertRaisesRegex(RuntimeError, 'auxiliary maps'):
            self.run_job()
        self.assertFalse((self.output / 'COMPLETE.txt').exists())

    def test_grouped_and_independent_exports_reach_full_api(self):
        self.fake_engine()
        engine = sys.modules['ezsynth.main_ez'].EzsynthBase
        def full(runner, return_flow):
            runner.eb.run()
            if len(runner.frames) > 2:
                for _ in range(3):
                    runner.eb.run()
            count = len(runner.frames) - 1
            return runner.frames, [np.full((128, 128), 12.5, np.float32)] * count, [np.zeros((128, 128, 3), np.uint8)] * count if return_flow else []
        engine.run_sequences_full = full
        for grouped in (False, True):
            if grouped:
                self.job.update(plan_grouped_video({i: self.frames[0][1] for i in range(10, 13)},
                                                   {10: self.job['style'], 12: self.job['style']}))
            self.job['exports'] = {'maps': True, 'flow': True}
            self.run_job()
            manifest = json.loads((self.output / 'auxiliary/manifest.json').read_text())
            self.assertEqual(manifest['artifacts'][0]['map_kind'], 'selection_mask' if grouped else 'synthesis_error')
            self.assertTrue((self.output / 'COMPLETE.txt').exists())

    def test_single_frame_writes_empty_manifest_without_engine(self):
        self.job['frames'] = self.frames[:1]
        self.job['exports'] = {'maps': True, 'flow': True}
        with patch.dict(sys.modules, {'torch': None, 'ezsynth.main_ez': None}):
            self.run_job()
        manifest = json.loads((self.output / 'auxiliary/manifest.json').read_text())
        self.assertEqual(manifest['artifacts'], [])
        self.assertTrue((self.output / 'COMPLETE.txt').exists())

    def test_nonfinite_or_wrong_flow_format_is_rejected(self):
        records = artifact_records([0, 1], [0])
        for values in (np.full((2, 2), np.nan), np.ones((2, 2), np.float32)):
            with self.assertRaises(RuntimeError):
                save_artifacts(self.output, {'flow': True}, records, [], [values])

    def test_numerical_flow_reaches_worker_without_visualization_api(self):
        self.fake_engine()
        self.job['exports'] = {'flow_vectors': True}
        self.run_job()
        root = self.output / 'flow_vectors'
        manifest = json.loads((root / 'manifest.json').read_text())
        self.assertEqual(manifest['units'], 'processed-resolution pixels')
        self.assertEqual(len(manifest['artifacts']), 1)
        item = manifest['artifacts'][0]
        self.assertEqual((item['flow_from'], item['flow_to'], item['grid_frame']), (0, 1, 0))
        np.testing.assert_array_equal(np.load(root / item['file']), np.zeros((128, 128, 2), np.float32))

    def test_numerical_flow_preserves_values_and_deduplicates_each_direction(self):
        from reezsynth_artifacts import FlowVectorWriter
        writer = FlowVectorWriter(self.output, True)
        forward = np.full((2, 3, 2), 1.234567, np.float32)
        reverse = np.full((2, 3, 2), -2.345678, np.float64)
        writer.add(10, 11, forward)
        writer.add(10, 11, forward)
        writer.add(11, 10, reverse)
        writer.finish()
        self.assertEqual(len(writer.records), 2)
        np.testing.assert_array_equal(np.load(writer.root / '10_to_11.npy'), forward)
        np.testing.assert_array_equal(np.load(writer.root / '11_to_10.npy'), reverse)
        with self.assertRaisesRegex(RuntimeError, 'finite'):
            writer.add(11, 12, np.full((2, 3, 2), np.nan))


class ExportGuiTests(LifecycleFixture):
    def test_preset_project_legacy_and_job_serialization(self):
        w = self.w
        self.assertEqual(w.options.snapshot('render')['exports'], {'maps': False, 'flow': False, 'flow_vectors': False})
        w.options.export_widgets['maps'].setChecked(True)
        w.options.export_widgets['flow'].setChecked(True)
        w.options.export_widgets['flow_vectors'].setChecked(True)
        preset = w.options.snapshot('render')
        w.project_file = self.root / 'project.json'
        w.save_project()
        data = json.loads(w.project_file.read_text())
        self.assertEqual(data['exports'], {'maps': True, 'flow': True, 'flow_vectors': True})
        for legacy in (False, True):
            if legacy:
                data.pop('exports')
                w.project_file.write_text(json.dumps(data))
            with patch.object(gui.QFileDialog, 'getOpenFileName', return_value=(str(w.project_file), '')):
                w.open_project()
            self.assertEqual(w.options.export_widgets['maps'].isChecked(), not legacy)
        w.options.apply('render', preset)
        self.run_queue()
        self.until(lambda: not w.busy)
        for path in w.batch.rglob('job.json'):
            self.assertEqual(json.loads(path.read_text())['exports'], {'maps': True, 'flow': True, 'flow_vectors': True})


if __name__ == '__main__':
    unittest.main(verbosity=2)
