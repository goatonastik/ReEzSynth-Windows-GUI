"""FuouM per-render cache bypass, preservation, persistence and UI relevance."""
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from reezsynth_config import validate_render
from reezsynth_engines import LEGACY, FUOUM
from reezsynth_fuoum_pipeline import extend_pipeline
from reezsynth_provenance import effective_settings
from reezsynth_sequence import frame_storage
from test_reezsynth_gui import GuiFixture


class RecomputeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='reezsynth-recompute-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.frames = [np.full((8, 9, 3), value, np.uint8) for value in (20, 40, 60)]
        self.counts = {'flow': 0, 'edge': 0}
        counts = self.counts
        class Pipeline:
            def __init__(self, config, data):
                pass
        class Flow:
            def __init__(self, **kwargs):
                pass
            def compute(self, pair):
                counts['flow'] += 1
                return [np.full((*pair[0].shape[:2], 2), counts['flow'], np.float32)]
        def edges(frames, method, options, engine):
            counts['edge'] += 1
            return [np.full(frame.shape, counts['edge'], np.uint8) for frame in frames]
        self.enterContext(patch.dict(sys.modules, {
            'ezsynth.pipeline': types.SimpleNamespace(SynthesisPipeline=Pipeline),
            'ezsynth.engines.flow_engine': types.SimpleNamespace(RAFTFlowEngine=Flow, NeuFlowEngine=Flow),
            'torch': types.SimpleNamespace(cuda=types.SimpleNamespace(empty_cache=lambda: None)),
        }))
        self.enterContext(patch('reezsynth_edges.compute_edge_frames', side_effect=edges))
        self.enterContext(patch('reezsynth_precompute_cache.flow_identity', return_value={'model': 'fixture'}))

    def run_pipeline(self, force_flow=False, force_edge=False, *, engine='RAFT', bidirectional=True,
                     custom=None, cache=True):
        options = dict(engine=FUOUM, fuoum_force_recompute_flow=force_flow,
                       fuoum_force_recompute_edge=force_edge)
        job = dict(render_options=options)
        if cache:
            job['precompute_cache'] = str(self.root / 'cache')
        config = types.SimpleNamespace(precomputation=types.SimpleNamespace(
            flow_engine=engine, flow_model='sintel', edge_method='Classic'))
        pipeline = extend_pipeline(config, types.SimpleNamespace(_content_frames=self.frames), [],
            custom or [], 0, 'none', lambda *a: None, cache_job=job, bidirectional=bidirectional)
        pipeline._compute_optical_flow(self.frames)
        pipeline._compute_edge_maps(self.frames)
        # Detach and close cached mmaps before Windows temp-directory cleanup.
        values = []
        for sequence in (pipeline._fwd_flows, pipeline._bwd_flows, pipeline._edge_maps):
            values.append([value.copy() for value in sequence])
            for value in sequence:
                if isinstance(value, np.memmap):
                    value._mmap.close()
        return values

    def snapshot_cache(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def test_defaults_and_boolean_validation(self):
        values = validate_render()
        self.assertFalse(values['fuoum_force_recompute_flow'])
        self.assertFalse(values['fuoum_force_recompute_edge'])
        for name in ('fuoum_force_recompute_flow', 'fuoum_force_recompute_edge'):
            with self.assertRaises(ValueError):
                validate_render({name: 1})

    def test_force_flow_ignores_warm_entries_but_reuses_edges_and_preserves_shared_files(self):
        warm = self.run_pipeline()
        snapshot = self.snapshot_cache()
        fresh = self.run_pipeline(force_flow=True)
        self.assertEqual(self.counts, {'flow': 8, 'edge': 1})
        self.assertFalse(np.array_equal(warm[0][0], fresh[0][0]))
        np.testing.assert_array_equal(warm[2][0], fresh[2][0])
        self.assertEqual(snapshot, self.snapshot_cache())
        reused = self.run_pipeline()
        self.assertEqual(self.counts, {'flow': 8, 'edge': 1})
        np.testing.assert_array_equal(warm[0][0], reused[0][0])

    def test_force_edges_ignores_warm_entries_but_reuses_flow_and_preserves_shared_files(self):
        warm = self.run_pipeline()
        snapshot = self.snapshot_cache()
        fresh = self.run_pipeline(force_edge=True)
        self.assertEqual(self.counts, {'flow': 4, 'edge': 2})
        np.testing.assert_array_equal(warm[0][0], fresh[0][0])
        self.assertFalse(np.array_equal(warm[2][0], fresh[2][0]))
        self.assertEqual(snapshot, self.snapshot_cache())

    def test_forcing_both_creates_no_shared_cache_entries_on_a_cold_cache(self):
        self.run_pipeline(force_flow=True, force_edge=True)
        self.assertEqual(self.counts, {'flow': 4, 'edge': 1})
        self.assertFalse((self.root / 'cache').exists())

    def test_custom_edges_bypass_recomputation_and_edge_cache(self):
        custom = [np.full((8, 9), 70, np.uint8) for _ in self.frames]
        result = self.run_pipeline(force_flow=True, force_edge=True, custom=custom)
        self.assertEqual(self.counts, {'flow': 4, 'edge': 0})
        np.testing.assert_array_equal(result[2][0], custom[0])
        self.assertFalse((self.root / 'cache').exists())

    def test_neuflow_forward_only_and_no_cache_keep_fresh_results(self):
        self.run_pipeline(force_flow=True, force_edge=True, engine='NeuFlow', bidirectional=False, cache=False)
        self.assertEqual(self.counts, {'flow': 2, 'edge': 1})

    def test_forced_results_work_with_disk_backed_frame_storage(self):
        with frame_storage(dict(output=str(self.root), render_options=dict(stream_frames=True))):
            result = self.run_pipeline(force_flow=True, force_edge=True)
            self.assertEqual(result[0][0].shape, (8, 9, 2))
            self.assertEqual(result[2][0].shape, (8, 9, 3))
        self.assertFalse(list(self.root.glob('.frame-storage-*')))

    def test_effective_metadata_omits_inactive_and_bypassed_controls(self):
        job = dict(frames=[[0, 'a'], [1, 'b']], render_options=dict(engine=FUOUM,
            fuoum_force_recompute_flow=True, fuoum_force_recompute_edge=True))
        values = effective_settings(job)['render_options']
        self.assertTrue(values['fuoum_force_recompute_flow'])
        self.assertTrue(values['fuoum_force_recompute_edge'])
        job['render_options']['custom_edge_guides'] = True
        self.assertNotIn('fuoum_force_recompute_edge', effective_settings(job)['render_options'])
        job['render_options']['engine'] = LEGACY
        values = effective_settings(job)['render_options']
        self.assertNotIn('fuoum_force_recompute_flow', values)
        self.assertNotIn('fuoum_force_recompute_edge', values)


class RecomputeGuiTests(GuiFixture):
    def test_controls_are_fuoum_video_only_and_custom_edges_disable_edge_bypass(self):
        window = self.window()
        widgets = window.options.widgets['render']
        flow, edge = (widgets[name] for name in ('fuoum_force_recompute_flow', 'fuoum_force_recompute_edge'))
        self.assertFalse(flow.isEnabled())
        widgets['engine'].setCurrentText(FUOUM)
        self.assertTrue(flow.isEnabled())
        self.assertTrue(edge.isEnabled())
        flow.setChecked(True)
        edge.setChecked(True)
        self.assertIn('optical flow', window.options.recompute_note.text())
        self.assertIn('automatic edges', window.options.recompute_note.text())
        widgets['custom_edge_guides'].setChecked(True)
        self.assertFalse(edge.isEnabled())
        self.assertTrue(edge.isChecked())
        self.assertNotIn('automatic edges', window.options.recompute_note.text())
        window.tabs.setCurrentWidget(window.image_synthesis)
        self.assertFalse(flow.isEnabled())
        self.assertFalse(edge.isEnabled())

    def test_preset_roundtrip_old_defaults_engine_switch_and_quality_preserve_flags(self):
        window = self.window()
        options = window.options
        widgets = options.widgets['render']
        widgets['engine'].setCurrentText(FUOUM)
        widgets['fuoum_force_recompute_flow'].setChecked(True)
        widgets['fuoum_force_recompute_edge'].setChecked(True)
        state = options.snapshot('render')
        options.apply('render', options.default_group('render'))
        options.apply('render', state)
        self.assertTrue(options.render()['fuoum_force_recompute_flow'])
        widgets['engine'].setCurrentText(LEGACY)
        widgets['engine'].setCurrentText(FUOUM)
        window.quality.setCurrentText('Preview')
        self.assertTrue(options.render()['fuoum_force_recompute_edge'])
        for name in ('fuoum_force_recompute_flow', 'fuoum_force_recompute_edge'):
            state['options'].pop(name)
        options.apply('render', state)
        self.assertFalse(options.render()['fuoum_force_recompute_flow'])
        self.assertFalse(options.render()['fuoum_force_recompute_edge'])


if __name__ == '__main__':
    unittest.main()
