"""Image synthesis with the live upstream run method and mocked native work."""
import ast
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
import test_reezsynth_render_adapter as adapter
from test_reezsynth_lifecycle import LifecycleFixture, gui
from reezsynth_image import validate_image_settings
from reezsynth_image_controls import ImageFileEdit


class ImageAdapterTests(unittest.TestCase):
    setUp = adapter.RenderAdapterTests.setUp
    run_job = adapter.RenderAdapterTests.run_job

    def prepare(self):
        source = self.root/'source.png'
        target = self.root/'target.png'
        source.write_bytes(cv2.imencode('.png', np.full((128,128), 40, np.uint8))[1].tobytes())
        target.write_bytes(cv2.imencode('.png', np.full((80,160), 70, np.uint8))[1].tobytes())
        self.settings = dict(style=self.job['style'], source=str(source), target=str(target),
                             source_weight=6, key_weight=2, guides=[])
        self.job = dict(type='image_synthesis', image_synthesis=self.settings, output=str(self.output),
                        quality='Standard', max_width=0)
        captured = dict(calls=[])
        tree = ast.parse((Path(__file__).parent/'ezsynth/main_ez.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ImageSynthBase')
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run']
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), cls], type_ignores=[])
        namespace = {}
        exec(compile(ast.fix_missing_locations(module), 'main_ez.py', 'exec'), namespace)
        class Engine(namespace['ImageSynthBase']):
            def __init__(runner, style_img, src_img, tgt_img, cfg):
                runner.style_img, runner.src_img, runner.tgt_img, runner.cfg = style_img, src_img, tgt_img, cfg
                captured['cfg'] = cfg
                captured['runner'] = runner
                def native(style, guides):
                    captured['calls'].append(list(guides))
                    result = np.full((*tgt_img.shape[:2], 3), 123, np.uint8)
                    error = np.full(tgt_img.shape[:2], 1.234567, np.float32)
                    return result, error
                runner.eb = types.SimpleNamespace(backends={'cuda': 17}, backend=None, run=native)
        self.enterContext(patch.dict(sys.modules, {
            'ezsynth.aux_classes': types.SimpleNamespace(RunConfig=lambda **kw: types.SimpleNamespace(**kw)),
            'ezsynth.main_ez': types.SimpleNamespace(ImageSynthBase=Engine),
            'torch': None,
        }))
        return captured

    def test_retargeting_weights_and_lossless_error_using_upstream_run(self):
        captured = self.prepare()
        self.settings['guides'] = [dict(source=self.settings['source'], target=self.settings['target'], weight=8)]
        for _ in range(2):
            self.run_job()
            self.assertEqual([g[2] for g in captured['calls'][-1]], [4, 3])
            self.assertEqual(captured['runner'].eb.backend, 17)
            self.assertEqual(captured['cfg'].patchsize, 7)
        output = cv2.imread(str(self.output/'image.png'))
        self.assertEqual(output.shape, (80,160,3))
        np.testing.assert_array_equal(np.load(self.output/'error.npy', allow_pickle=False), np.full((80,160),1.234567,np.float32))
        manifest = json.loads((self.output/'image_manifest.json').read_text())
        self.assertEqual(manifest['guide_channels'], [1,1])
        self.assertTrue((self.output/'COMPLETE.txt').exists())

    def test_bad_dimensions_and_channels_rejected_before_engine(self):
        captured = self.prepare()
        self.settings['source'] = self.settings['target']
        with self.assertRaisesRegex(ValueError, 'styled image dimensions'):
            self.run_job()
        self.assertNotIn('runner', captured)
        self.settings['source'] = self.settings['style']
        with self.assertRaisesRegex(ValueError, 'channel counts'):
            self.run_job()
        self.assertFalse((self.output/'COMPLETE.txt').exists())

    def test_channel_limit_and_bad_files_rejected(self):
        self.prepare()
        self.settings['source'] = self.settings['style']
        self.settings['target'] = self.settings['style']
        self.settings['guides'] = [dict(source=self.settings['style'], target=self.settings['style'], weight=1)]*8
        with self.assertRaisesRegex(ValueError, '24 guide channels'):
            self.run_job()
        self.settings['guides'] = []
        self.settings['source'] = str(self.root/'missing.png')
        with self.assertRaises(ValueError):
            self.run_job()

    def test_error_save_failure_prevents_completion(self):
        self.prepare()
        with patch('numpy.save', side_effect=OSError('test disk failure')), self.assertRaises(OSError):
            self.run_job()
        self.assertFalse((self.output/'COMPLETE.txt').exists())

    def test_shared_processing_size_resizes_source_and_target_independently(self):
        captured = self.prepare()
        source = np.zeros((600,800), np.uint8)
        target = np.zeros((300,600), np.uint8)
        Path(self.settings['style']).write_bytes(cv2.imencode('.png', np.zeros((600,800,3),np.uint8))[1].tobytes())
        Path(self.settings['source']).write_bytes(cv2.imencode('.png', source)[1].tobytes())
        Path(self.settings['target']).write_bytes(cv2.imencode('.png', target)[1].tobytes())
        self.job['max_width'] = 512
        self.run_job()
        self.assertEqual(captured['runner'].style_img.shape, (384,512,3))
        self.assertEqual(captured['runner'].tgt_img.shape, (256,512))

    def test_invalid_settings_and_uint16_guide(self):
        for data in ({'key_weight':0}, {'source_weight':float('nan')}, {'guides':[{}]}, {'unknown':1}):
            with self.assertRaises(ValueError):
                validate_image_settings(data)
        self.prepare()
        Path(self.settings['source']).write_bytes(cv2.imencode('.png',np.ones((128,128),np.uint16))[1].tobytes())
        with self.assertRaisesRegex(ValueError, '8-bit'):
            self.run_job()


class ImageGuiTests(LifecycleFixture):
    def prepare(self):
        image = self.root/'still.png'
        image.write_bytes(cv2.imencode('.png', np.ones((32,32,3), np.uint8))[1].tobytes())
        self.w.image_synthesis.set_settings(dict(style=str(image), source=str(image), target=str(image)))
        return image

    def test_image_completion_in_shared_isolated_and_parallel_modes(self):
        self.prepare()
        for shared, parallel in ((True,False),(False,False),(False,True)):
            self.w.reuse_worker.setChecked(shared)
            self.w.options.widgets['application']['parallel'].setChecked(parallel)
            self.w.run_image()
            self.assertFalse(self.w.image_synthesis.run.isEnabled())
            self.assertTrue(self.w.image_synthesis.stop.isEnabled())
            self.until(lambda: not self.w.busy)
            self.assertTrue(self.w.image_synthesis.run.isEnabled())
            self.assertEqual(self.w.image_synthesis.state.text(), 'Complete')
            self.assertEqual(self.w.overall.value(), 100)
            data = json.loads(next(self.w.batch.rglob('job.json')).read_text())
            self.assertEqual(data['type'], 'image_synthesis')
            self.assertNotIn('frames', data)

    def test_cancel_image_then_restart_video(self):
        self.prepare()
        self.mode('slow')
        self.w.run_image()
        self.until(lambda: 'MOCK_STARTED' in self.w.log.toPlainText())
        self.w.image_synthesis.stop.click()
        self.until(lambda: not self.w.busy)
        self.assertIsNone(self.w.process)
        self.mode('normal')
        self.run_queue()
        self.until(lambda: not self.w.busy)
        self.assertTrue(all(r['state'].text() == 'Complete' for r in self.w.rows))

    def test_image_only_project_and_preset_and_old_project_compatibility(self):
        image = self.prepare()
        w = self.w
        w.image_synthesis.add_guide(dict(source=str(image), target=str(image), weight=2))
        settings = w.image_synthesis.settings()
        w.options.store.save('image', 'Still', settings)
        w.options.apply('image', {})
        w.options.apply('image', w.options.store.groups['image']['Still'])
        self.assertEqual(w.image_synthesis.settings(), settings)
        w.project_file = self.root/'video.json'
        w.save_project()
        old = json.loads(w.project_file.read_text())
        old.pop('image_synthesis')
        w.project_file.write_text(json.dumps(old))
        with patch.object(gui.QFileDialog,'getOpenFileName',return_value=(str(w.project_file),'')):
            w.open_project()
        self.assertEqual(w.image_synthesis.settings()['style'], '')
        w.image_synthesis.set_settings(settings)
        w.video_dir.setText('')
        w.keyframe_dir.setText('')
        w.rebuild_queue()
        w.project_file = self.root/'still.json'
        w.save_project()
        self.assertEqual(json.loads(w.project_file.read_text())['project_mode'], 'image')
        with patch.object(gui.QFileDialog,'getOpenFileName',return_value=(str(w.project_file),'')):
            w.open_project()
        self.assertEqual(w.image_synthesis.settings(), settings)
        self.assertEqual(w.rows, [])
        self.assertIs(w.tabs.currentWidget(), w.image_synthesis)

    def test_file_drop_and_guide_removal(self):
        path = self.prepare()
        widget = self.w.image_synthesis
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        event = QDropEvent(QPointF(1,1), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        widget.source.setText('')
        widget.source.dropEvent(event)
        self.assertEqual(Path(widget.source.text()), path)
        widget.add_guide()
        widget.remove_guide(widget.table.cellWidget(0,3))
        self.assertEqual(widget.settings()['guides'], [])

    def test_render_failure_does_not_report_completion(self):
        self.prepare()
        self.mode('fail')
        self.w.run_image()
        self.until(lambda: not self.w.busy)
        self.assertNotEqual(self.w.image_synthesis.state.text(), 'Complete')
        self.assertEqual(list(self.w.batch.rglob('COMPLETE.txt')), [])
        self.assertIsNone(self.w.process)

    def test_close_during_image_render_waits_for_worker_exit(self):
        self.prepare()
        self.mode('slow')
        self.w.show()
        self.w.run_image()
        self.until(lambda: 'MOCK_STARTED' in self.w.log.toPlainText())
        with patch.object(gui.QMessageBox,'question',return_value=gui.QMessageBox.StandardButton.Yes):
            self.assertFalse(self.w.close())
        self.until(lambda: not self.w.isVisible())
        self.assertIsNone(self.w.process)
        self.assertFalse(self.w.busy)


if __name__ == '__main__':
    unittest.main(verbosity=2)
