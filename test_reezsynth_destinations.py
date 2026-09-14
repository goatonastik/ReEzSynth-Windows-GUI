"""Destination selection, collision protection and input-weight adapter tests."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import test_reezsynth_render_adapter as adapter
from test_reezsynth_lifecycle import LifecycleFixture, gui
from reezsynth_config import validate_weights
from reezsynth_output_location import output_root, create_unique_directory
from reezsynth_project_controls import project_naming


class DestinationTests(LifecycleFixture):
    def test_project_output_owner_survives_load_and_render_apply(self):
        w = self.w
        naming = dict(project_naming(w), location='custom', custom_folder=str(self.root / 'project_output'),
                      batch_enabled=False, job_pattern='project_{key:03d}')
        w.options.apply('output', naming)
        self.assertTrue(w.rebuild_queue())
        w.project_file = self.root / 'ownership.reezsynth.json'
        w.save_project()
        document = json.loads(w.project_file.read_text())
        self.assertEqual(document['output_naming'], naming)
        self.assertNotIn('output_naming', document['render_options'])
        self.assertNotIn('output_naming', w.options.project_data())
        self.assertEqual(json.dumps(document).count('"output_naming"'), 1)
        w.options.apply('output', dict(naming, custom_folder=str(self.root / 'other')))
        with patch.object(gui.QFileDialog, 'getOpenFileName', return_value=(str(w.project_file), '')):
            w.open_project()
        w.options.apply('render', dict(output_naming={'location': 'project_renders'}), restore_related=True)
        self.assertEqual(project_naming(w), naming)
        with patch.object(w, 'start_records') as start:
            w.run_rows(list(w.rows))
        records, batch = start.call_args.args[:2]
        self.assertEqual(batch, self.root / 'project_output')
        for record in records:
            expected = batch / f"project_{record['key']:03d}"
            self.assertEqual(record['output'], expected)
            self.assertEqual(Path(json.loads(record['job_path'].read_text())['output']), expected)

    def test_output_restore_conflict_cannot_redirect_generated_jobs(self):
        o = self.w.options
        o.persist()
        data = json.loads(o.last_path.read_text())
        canonical = dict(project_naming(self.w), location='custom',
            custom_folder=str(self.root / 'canonical'), batch_pattern='chosen_batch',
            job_pattern='chosen_{key:03d}')
        stale = dict(canonical, custom_folder=str(self.root / 'stale'),
                     batch_pattern='stale_batch', job_pattern='stale_{key:03d}')
        data['groups']['output'] = canonical
        data['groups']['render']['output_naming'] = stale
        o.last_path.write_text(json.dumps(data), encoding='utf-8')
        restored = self.window()
        self.assertTrue(restored.rebuild_queue())
        with patch.object(restored, 'start_records') as start:
            restored.run_rows(list(restored.rows))
        start.assert_called_once()
        records, batch = start.call_args.args[:2]
        expected_batch = self.root / 'canonical' / 'chosen_batch'
        self.assertEqual(batch, expected_batch)
        self.assertEqual(project_naming(restored), canonical)
        for record in records:
            expected = expected_batch / f"chosen_{record['key']:03d}"
            self.assertEqual(record['output'], expected)
            job = json.loads(record['job_path'].read_text())
            self.assertEqual(Path(job['output']), expected)
        self.assertFalse((self.root / 'stale').exists())

    def test_original_resolution_rejects_mismatched_keys_and_video_before_start(self):
        w = self.w
        self.assertEqual(w.resolution.currentData(), 'original')
        paths = [Path(w.keyframe_dir.text())/'style002.png', Path(w.video_dir.text())/'frame001.png']
        for path in paths:
            original = path.read_bytes()
            path.write_bytes(cv2.imencode('.png', np.zeros((9,8,3),np.uint8))[1].tobytes())
            for grouped in (False, True):
                with patch.object(gui.QMessageBox, 'warning') as warning:
                    w.run_rows(list(w.rows), grouped=grouped)
                self.assertIn('8 x 9', warning.call_args.args[2])
                self.assertIn('Expected: 8 x 8', warning.call_args.args[2])
                self.assertIn(path.name, warning.call_args.args[2])
                self.assertIsNone(w.process)
                self.assertIsNone(w.batch)
                self.assertFalse(w.busy)
                self.assertFalse((Path(w.project_dir.text())/'renders').exists())
            path.write_bytes(original)

    def test_explicit_saved_processing_size_survives_new_default(self):
        w = self.w
        w.set_processing_size([960, 540])
        w.options.persist()
        restored = self.window()
        self.assertEqual(restored.resolution.currentData(), 'custom')
        self.assertEqual(restored.processing_size(), [960, 540])

    def test_all_location_roots(self):
        w = self.w
        keys, video, project = map(Path, (w.keyframe_dir.text(), w.video_dir.text(), w.project_dir.text()))
        expected = dict(project_renders=project/'renders', keys_child=keys/'outputs',
                        video_child=video/'outputs', keys_parent=keys.parent,
                        video_parent=video.parent, project=project, custom=self.root/'custom')
        for location, path in expected.items():
            self.assertEqual(output_root(dict(location=location, custom_folder=str(self.root/'custom')),
                                         project, keys, video), path)

    def test_no_batch_collisions_preserve_completed_outputs(self):
        w = self.w
        w.batch_enabled.setChecked(False)
        w.output_location.setCurrentIndex(w.output_location.findData('keys_child'))
        self.run_queue()
        self.until(lambda: not w.busy)
        root = Path(w.keyframe_dir.text())/'outputs'
        self.assertEqual(w.batch, root)
        original = sorted(root.rglob('job.json'))
        original_bytes = [path.read_bytes() for path in original]
        self.run_queue()
        self.until(lambda: not w.busy)
        self.assertEqual(len(list(root.rglob('job.json'))), 4)
        self.assertEqual([path.read_bytes() for path in original], original_bytes)
        self.assertTrue(any(path.name.endswith('_002') for path in root.iterdir()))

    def test_grouped_custom_batch_and_project_round_trip(self):
        w = self.w
        w.output_location.setCurrentIndex(w.output_location.findData('custom'))
        w.custom_output.setText(str(self.root/'custom'))
        w.batch_name_pattern.setText('batch')
        w.project_file = self.root/'saved.json'
        w.save_project()
        naming = project_naming(w)
        w.output_location.setCurrentIndex(0)
        with patch.object(gui.QFileDialog, 'getOpenFileName', return_value=(str(w.project_file), '')):
            w.open_project()
        self.assertEqual(project_naming(w), naming)
        w.run_rows([], grouped=True)
        self.until(lambda: not w.busy)
        self.assertEqual(w.batch, self.root/'custom/batch')
        self.assertTrue((w.batch/'grouped_video/COMPLETE.txt').is_file())

    def test_traversal_and_blank_custom_rejected(self):
        with self.assertRaises(ValueError):
            output_root({'location':'custom'}, self.root, self.root, self.root)
        with self.assertRaises(ValueError):
            create_unique_directory(self.root, '../escape')

    def test_layout_and_mask_toggle_and_preset_restore(self):
        w = self.w
        w.show()
        self.app.processEvents()
        # Both controls occupy the same horizontal band; output is on the right.
        self.assertGreater(w.output_location.mapTo(w, w.output_location.rect().topLeft()).x(),
                           w.keyframe_dir.mapTo(w, w.keyframe_dir.rect().topLeft()).x())
        checkbox = w.options.widgets['render']['do_mask']
        self.assertEqual(checkbox.text(), 'Masks')
        checkbox.setChecked(True)
        self.assertTrue(w.options.render()['do_mask'])
        checkbox.setChecked(False)
        self.assertFalse(w.options.render()['do_mask'])
        w.batch_enabled.setChecked(False)
        w.options.persist()
        data = json.loads(w.options.last_path.read_text())
        self.assertFalse(data['groups']['output']['batch_enabled'])
        self.assertNotIn('output_naming', data['groups']['render'])


class WeightTests(unittest.TestCase):
    setUp = adapter.RenderAdapterTests.setUp
    run_job = adapter.RenderAdapterTests.run_job
    fake_engine = adapter.RenderAdapterTests.fake_engine

    def test_key_ratio_and_mask_pair_forwarding_and_disable(self):
        captured = self.fake_engine()
        engine = sys.modules['ezsynth.main_ez'].EzsynthBase
        original_init = engine.__init__
        seen = []
        def init(runner, **kwargs):
            original_init(runner, **kwargs)
            runner.img_frs_seq = runner.frames
            # The premask path uses different array identities.
            runner.masked_frs_seq = [image.copy() for image in runner.frames]
            runner.eb.run = lambda *args, **kwargs: seen.append(kwargs['guides'])
        def run(runner):
            source = runner.masked_frs_seq if captured['config'].get('pre_mask') else runner.frames
            runner.eb.run(source[0], guides=[(source[0], source[1], 1), (source[0], source[1], 2)])
            return runner.frames, None
        engine.__init__, engine.run_sequences = init, run
        masks = []
        for i in range(2):
            path = self.root/f'mask{i}.png'
            path.write_bytes(cv2.imencode('.png', np.full((128,128), i*255, np.uint8))[1].tobytes())
            masks.append([i, str(path)])
        self.job['masks'] = masks
        self.job['guide_weights'] = dict(key_wgt=2, img_wgt=8, mask_wgt=6)
        for enabled, premask in ((True, False), (True, True), (False, False)):
            self.job['render_options'] = dict(do_mask=enabled, pre_mask=premask)
            self.run_job()
            self.assertEqual(captured['config']['img_wgt'], 4)
            self.assertNotIn('key_wgt', captured['config'])
            self.assertEqual(len(seen[-1]), 3 if enabled else 2)
            if enabled:
                first, second, weight = seen[-1][-1]
                self.assertTrue(np.all(first == 0))
                self.assertTrue(np.all(second == 255))
                self.assertEqual(weight, 3)

    def test_invalid_key_weight_and_legacy_defaults(self):
        self.assertEqual(validate_weights({})['key_wgt'], 1)
        self.assertEqual(validate_weights({})['mask_wgt'], 0)
        for value in (0, -1, float('nan')):
            with self.assertRaises(ValueError):
                validate_weights({'key_wgt': value})


if __name__ == '__main__':
    unittest.main(verbosity=2)
