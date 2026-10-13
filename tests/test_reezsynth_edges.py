"""Edge settings, actual dispatch contracts, preview worker and GUI lifecycle."""
import json
from pathlib import Path
import tempfile
import types
import sys
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
from PySide6.QtCore import QProcess

from reezsynth_config import RENDER, validate_render
from reezsynth_edges import (EDGE_DEFAULTS, EDGE_SPECS, compute_tuned_edge,
                             edge_parameters)
from reezsynth_engines import LEGACY, FUOUM
from reezsynth_precompute_cache import edge_identity
from reezsynth_provenance import effective_settings
from tests.test_reezsynth_gui import GuiFixture


class EdgeSettingsTests(unittest.TestCase):
    def test_old_settings_restore_exact_detector_defaults(self):
        values = validate_render({'edge_method': 'PST'})
        self.assertEqual({name: values[name] for name in EDGE_DEFAULTS}, EDGE_DEFAULTS)
        self.assertEqual(edge_parameters('PST'), dict(S=.3, W=15., sigma_LPF=.15,
            thresh_min=.05, thresh_max=.9, morph_flag=1))
        self.assertEqual(len(edge_parameters('PAGE')), 10)

    def test_validation_rejects_nonfinite_bool_as_number_and_invalid_thresholds(self):
        for values in ({'edge_pst_s': float('nan')}, {'edge_pst_s': True},
                       {'edge_page_sigma1': 0}, {'edge_pst_morph': 1},
                       {'edge_method': 'PAGE', 'edge_page_min': .9, 'edge_page_max': .9}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_render(values)

    def test_inactive_detector_thresholds_do_not_block_render(self):
        pst = validate_render({'edge_method': 'PST', 'edge_page_min': .9, 'edge_page_max': .9})
        page = validate_render({'edge_method': 'PAGE', 'edge_pst_min': .9, 'edge_pst_max': .9})
        classic = validate_render({'edge_method': 'Classic', 'edge_pst_min': .9, 'edge_pst_max': .9,
                                   'edge_page_min': .9, 'edge_page_max': .9})
        self.assertEqual((pst['edge_page_min'], page['edge_pst_min'], classic['edge_pst_min']), (.9, .9, .9))

    def test_default_dispatch_is_unchanged_and_tuning_reaches_kernel(self):
        detector = MagicMock()
        frame = np.zeros((8, 8, 3), np.uint8)
        self.assertIs(compute_tuned_edge(detector, frame, 'PST'), detector.compute_edge.return_value)
        detector.compute_edge.assert_called_once_with(frame)
        for method, field, parameter in (('PST', 'edge_pst_s', 'S'), ('PAGE', 'edge_page_s1', 'S1')):
            run = detector.pst_run if method == 'PST' else detector.page_run
            run.return_value = np.ones((8, 8), np.float32)
            compute_tuned_edge(detector, frame, method, {field: .7})
            self.assertEqual(run.call_args.kwargs[parameter], .7)
            detector.pst_page_postprocess.assert_called_with(run.return_value)

    def test_cache_keys_include_only_effective_tuning_and_keep_old_defaults(self):
        original = dict(engine=LEGACY, revision='revision', method='PST')
        self.assertEqual(edge_identity(LEGACY, 'revision', 'PST', RENDER), original)
        self.assertEqual(edge_identity(LEGACY, 'revision', 'PST', {'edge_page_s1': .2}), original)
        changed = edge_identity(LEGACY, 'revision', 'PST', {'edge_pst_s': .2})
        self.assertNotEqual(original, changed)
        self.assertEqual(changed['parameters']['S'], .2)

    def test_effective_metadata_omits_bypassed_and_inactive_tuning(self):
        job = dict(frames=[[0, 'a'], [1, 'b']], render_options=dict(edge_method='PST', edge_pst_s=.4))
        result = effective_settings(job)['render_options']
        self.assertEqual(result['edge_pst_s'], .4)
        self.assertNotIn('edge_page_s1', result)
        job['render_options']['custom_edge_guides'] = True
        result = effective_settings(job)['render_options']
        self.assertFalse(set(result) & set(EDGE_DEFAULTS))

    def test_worker_uses_render_size_and_engine_specific_premasking(self):
        from reezsynth_edge_worker import generate_preview
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, mask = root / '源000.png', root / 'mask000.png'
            source.write_bytes(cv2.imencode('.png', np.full((128, 128, 3), 200, np.uint8))[1].tobytes())
            mask.write_bytes(cv2.imencode('.png', np.full((128, 128), 128, np.uint8))[1].tobytes())
            for engine, expected in ((LEGACY, 200), (FUOUM, 100)):
                captured = []
                def compute(frames, method, options=None, engine=LEGACY):
                    captured.append(frames[0].copy())
                    return [np.full(frames[0].shape[:2], 90, np.uint8)]
                request = dict(source=str(source), mask=str(mask), processing_size=[256, 128],
                    options=dict(engine=engine, edge_method='PST', edge_pst_s=.6, do_mask=True, pre_mask=True))
                with patch('reezsynth_engines.prepare_runtime', return_value={'engine': engine}), \
                     patch('reezsynth_engines.activate_fuoum'), \
                     patch('reezsynth_edges.compute_edge_frames', side_effect=compute):
                    generate_preview(request, root)
                self.assertEqual(captured[0].shape, (128, 256, 3))
                self.assertEqual(int(captured[0][0, 0, 0]), expected)
                result = json.loads((root / 'result.json').read_text())
                self.assertEqual(result['size'], [256, 128])
                self.assertTrue((root / 'overlay.png').is_file())

    def test_fuoum_pipeline_uses_tuning_with_and_without_cache_and_bypasses_custom(self):
        from reezsynth_fuoum_pipeline import extend_pipeline
        frames = [np.full((8, 9, 3), 80, np.uint8)]
        config = types.SimpleNamespace(precomputation=types.SimpleNamespace(edge_method='PST'))
        class Pipeline:
            def __init__(self, config, data):
                pass
        calls = []
        def compute(frames, method, options, engine):
            calls.append((method, options['edge_pst_s'], engine))
            return [np.full(frame.shape, 90, np.uint8) for frame in frames]
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(sys.modules, {'ezsynth.pipeline': types.SimpleNamespace(SynthesisPipeline=Pipeline)}), \
             patch('reezsynth_edges.compute_edge_frames', side_effect=compute), \
             patch('reezsynth_precompute_cache.flow_identity', return_value={}):
            def build(settings, cache=False, custom=None):
                pipeline = extend_pipeline(config, types.SimpleNamespace(_content_frames=frames), [],
                    custom or [], 0, 'none', lambda *a: None, edge_settings=settings,
                    cache_job={'precompute_cache': directory} if cache else {})
                pipeline._compute_edge_maps(frames)
                return pipeline
            build({'edge_pst_s': .7})
            build({'edge_pst_s': .7}, cache=True)
            build({'edge_pst_s': .7}, cache=True)
            build({'edge_pst_s': .4}, cache=True)
            custom = [np.full((8, 9), 12, np.uint8)]
            pipeline = build({'edge_pst_s': .4}, custom=custom)
            self.assertIs(pipeline._edge_maps, custom)
            self.assertEqual(calls, [('PST', .7, FUOUM), ('PST', .7, FUOUM), ('PST', .4, FUOUM)])


class EdgeGuiTests(GuiFixture):
    def test_panel_method_visibility_reset_and_preset_compatibility(self):
        window = self.window()
        options = window.options
        widgets = options.widgets['render']
        self.assertTrue(options.edge_panel.isHidden())
        options.edge_toggle.setChecked(True)
        widgets['edge_method'].setCurrentText('PST')
        self.assertFalse(options.edge_boxes['PST'].isHidden())
        self.assertTrue(options.edge_boxes['PAGE'].isHidden())
        widgets['edge_pst_s'].setValue(.7)
        widgets['edge_page_s1'].setValue(.2)
        state = options.snapshot('render')
        options.reset_edge_settings()
        self.assertEqual(widgets['edge_pst_s'].value(), .3)
        self.assertEqual(widgets['edge_page_s1'].value(), .8)
        options.apply('render', state)
        self.assertEqual(widgets['edge_pst_s'].value(), .7)
        for name in EDGE_DEFAULTS:
            state['options'].pop(name)
        options.apply('render', state)
        self.assertEqual(widgets['edge_pst_s'].value(), .3)
        widgets['engine'].setCurrentText(FUOUM)
        self.assertTrue(widgets['edge_pst_s'].isEnabled())
        widgets['custom_edge_guides'].setChecked(True)
        self.assertFalse(widgets['edge_pst_s'].isEnabled())
        self.assertFalse(options.edge_preview_button.isEnabled())

    def preview(self):
        from reezsynth_edge_preview import EdgePreviewWindow
        window = self.window()
        directory = self.root / 'frames'
        directory.mkdir()
        source = directory / 'frame000.png'
        source.write_bytes(cv2.imencode('.png', np.full((128, 128, 3), 80, np.uint8))[1].tobytes())
        window.video_dir.setText(str(directory))
        preview = EdgePreviewWindow(window.options)
        window.options.edge_preview = preview
        self.widgets.append(preview)
        window.scan_timer.stop()
        return window, preview

    def test_preview_becomes_stale_and_changed_folder_requires_refresh(self):
        window, preview = self.preview()
        request = preview.request()
        signature = preview.signature(request)
        window.options.widgets['render']['edge_method'].setCurrentText('PST')
        self.assertNotEqual(signature, preview.signature(preview.request()))
        window.video_dir.setText(self.directory('other'))
        with self.assertRaises(ValueError):
            preview.request()

    def test_failed_start_releases_process_and_temporary_files(self):
        window, preview = self.preview()
        process = MagicMock()
        process.readAllStandardOutput.return_value = b'cannot start'
        preview.process = process
        preview.temporary = tempfile.TemporaryDirectory()
        path = Path(preview.temporary.name)
        preview.process_error(process, QProcess.ProcessError.FailedToStart)
        self.assertFalse(preview.running())
        self.assertFalse(path.exists())
        self.assertTrue(preview.update_button.isEnabled())
        self.assertIn('failed', preview.status.text())

    def test_process_construction_failure_releases_gpu_lease(self):
        window, preview = self.preview()
        with patch('reezsynth_edge_preview.QProcess', side_effect=OSError('fixture launch failure')):
            preview.update_preview()
        self.assertIsNone(window.gpu_gate.owner)
        self.assertIsNone(preview.gpu_token)
        self.assertIsNone(preview.process)
        self.assertIsNone(preview.temporary)
        self.assertIn('Cannot start preview', preview.status.text())

    def test_preview_excludes_render_start_and_cancel_retains_ownership_until_exit(self):
        window, preview = self.preview()
        process = MagicMock()
        process.readAllStandardOutput.return_value = b''
        preview.process = process
        window.run_rows([])
        self.assertFalse(window.busy)
        self.assertIn('Edge Preview', window.status.text())
        preview.cancel()
        process.terminate.assert_called_once()
        self.assertTrue(preview.running())
        preview.force_stop()
        process.kill.assert_called_once()
        preview.finished(process, -1)
        self.assertFalse(preview.running())
        self.assertIn('cancelled', preview.status.text())

    def test_late_process_signals_cannot_clear_a_replacement_preview(self):
        window, preview = self.preview()
        old, current = MagicMock(), MagicMock()
        preview.process = current
        preview.finished(old, -1)
        preview.process_error(old, QProcess.ProcessError.FailedToStart)
        self.assertIs(preview.process, current)
        current.readAllStandardOutput.return_value = b''
        preview.cancelled = True
        preview.finished(current, -1)


if __name__ == '__main__':
    unittest.main()
