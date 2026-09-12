"""Live preview regression tests: real adapter/sequence methods and Qt processes; no GPU."""
import contextlib
import io
import json
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PySide6.QtCore import QEvent
from PySide6.QtGui import QImage

from test_reezsynth_gui import GuiFixture
from test_reezsynth_lifecycle import LifecycleFixture, SOURCE, gui
from test_reezsynth_grouped import upstream_engine
import test_reezsynth_render_adapter as adapter
import test_reezsynth_image as image_adapter
from reezsynth_preview import PreviewTile
from reezsynth_preview_transport import PreviewPublisher, PREVIEW_DIR, preview_channels
from reezsynth_video_plan import plan_grouped_video


def subscribe(output, channels):
    path = Path(output) / PREVIEW_DIR / 'request.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(dict(updated=time.time(), channels=channels)), encoding='utf-8')
    return path


class CaptureTests(unittest.TestCase):
    setUp = adapter.RenderAdapterTests.setUp
    run_job = adapter.RenderAdapterTests.run_job
    fake_engine = adapter.RenderAdapterTests.fake_engine

    def test_no_image_work_hidden_expired_or_unsubscribed_and_bounded_thumbnail(self):
        publisher = PreviewPublisher(self.output)
        pixels = np.full((1080, 1920, 3), 123, np.uint8)
        with patch.object(cv2, 'imencode', side_effect=AssertionError('Hidden preview encoded an image')):
            self.assertIsNone(publisher.publish(0, 'Forward', 1, pixels))
            self.assertFalse(publisher.root.exists())
            request = subscribe(self.output, [[2, 'Backward']])
            self.assertIsNone(publisher.publish(0, 'Forward', 1, pixels))
            request.write_text(json.dumps(dict(updated=time.time()-20, channels=[[0, 'Forward']])))
            self.assertIsNone(publisher.publish(0, 'Forward', 1, pixels))
        subscribe(self.output, [[0, 'Forward']])
        event = publisher.publish(0, 'Forward', 1, pixels)
        loaded = cv2.imdecode(np.frombuffer(Path(event['path']).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(loaded.shape, (540, 960, 3))
        self.assertTrue(np.all(pixels == 123))
        request.unlink()
        before = Path(event['path']).stat().st_mtime_ns
        self.assertIsNone(publisher.publish(0, 'Forward', 2, pixels))
        self.assertEqual(Path(event['path']).stat().st_mtime_ns, before)

    def test_preview_io_failure_does_not_fail_render(self):
        publisher = PreviewPublisher(self.output)
        subscribe(self.output, [[0, 'Forward']])
        with patch.object(cv2, 'imencode', side_effect=cv2.error('mock encoding failure')):
            self.assertIsNone(publisher.publish(0, 'Forward', 1, np.zeros((128,128,3),np.uint8)))
        self.assertTrue(publisher.warned)

    def test_real_adapter_emits_each_direction_before_sequence_returns(self):
        captured = {}
        Engine = upstream_engine(captured)
        self.fake_engine()
        self.job.update(plan_grouped_video(
            {i: self.frames[0][1] for i in range(10, 16)},
            {11: self.job['style'], 13: self.job['style']}))
        self.job['quality'] = 'Standard'
        channels = preview_channels(self.job)
        self.assertEqual(channels, [(11, 'Backward'), (11, 'Forward'), (13, 'Backward'), (13, 'Forward')])
        subscribe(self.output, channels)
        events = []
        def observe(percent, stage, preview=None):
            if preview is not None:
                self.assertLess(percent, 90)
                self.assertFalse(list(self.output.glob('*.png')), 'Preview was only emitted during final saving')
                self.assertFalse((self.output / 'COMPLETE.txt').exists())
                self.assertTrue(Path(preview['path']).is_file())
                events.append((preview['key'], preview['direction'], preview['frame']))
        with patch.dict(sys.modules, {'ezsynth.main_ez': types.SimpleNamespace(EzsynthBase=Engine),
                                     'ezsynth.aux_classes': types.SimpleNamespace(RunConfig=lambda **kw: types.SimpleNamespace(**{'only_mode': 'none', **kw}))}), \
             patch('reezsynth_jobs.progress', side_effect=observe):
            self.run_job()
        self.assertEqual(events, [(11,'Backward',10), (11,'Forward',12), (11,'Forward',13),
                                  (13,'Backward',12), (13,'Backward',11), (13,'Forward',14), (13,'Forward',15)])
        saved = {p.name: p.read_bytes() for p in self.output.glob('*.png')}
        # Same engine inputs and final PNGs when previews are closed.
        (self.output / PREVIEW_DIR / 'request.json').unlink()
        with patch.dict(sys.modules, {'ezsynth.main_ez': types.SimpleNamespace(EzsynthBase=Engine),
                                     'ezsynth.aux_classes': types.SimpleNamespace(RunConfig=lambda **kw: types.SimpleNamespace(**kw))}):
            self.run_job()
        self.assertEqual(saved, {p.name:p.read_bytes() for p in self.output.glob('*.png')})

    def test_independent_reverse_and_forward_frames_emit_before_save(self):
        self.fake_engine()
        Engine = upstream_engine({})
        self.job.update(key=12, frames=[[n,self.frames[0][1]] for n in range(10,15)])
        subscribe(self.output, preview_channels(self.job))
        events = []
        def observe(percent, stage, preview=None):
            if preview:
                self.assertFalse((self.output/'COMPLETE.txt').exists())
                events.append((preview['key'],preview['direction'],preview['frame']))
        with patch.dict(sys.modules, {'ezsynth.main_ez': types.SimpleNamespace(EzsynthBase=Engine),
                                     'ezsynth.aux_classes': types.SimpleNamespace(RunConfig=lambda **kw: types.SimpleNamespace(**{'only_mode': 'none', **kw}))}), \
             patch('reezsynth_jobs.progress', side_effect=observe):
            self.run_job()
        self.assertEqual(events, [(12,'Backward',11),(12,'Backward',10),(12,'Forward',13),(12,'Forward',14)])

    def test_premasked_frame_array_identities_are_mapped(self):
        self.fake_engine()
        Base = upstream_engine({})
        class Engine(Base):
            def __init__(runner, **kwargs):
                super().__init__(**kwargs)
                runner.masked_frs_seq = [image.copy() for image in runner.img_frs_seq]
                runner.style_masked_frs = [image.copy() for image in runner.style_frs]
                runner.msk_frs_seq = kwargs['msk_frs_seq']
        Base.run_sequences_full.__globals__['apply_masked_back_seq'] = lambda frames, results, masks, feather: results
        mask = self.root / 'mask.png'
        mask.write_bytes(cv2.imencode('.png', np.full((128,128),255,np.uint8))[1].tobytes())
        self.job['render_options'] = dict(do_mask=True, pre_mask=True)
        self.job['masks'] = [[n,str(mask)] for n,_ in self.job['frames']]
        subscribe(self.output, [[0,'Forward']])
        events = []
        def observe(percent, stage, preview=None):
            if preview:
                events.append((preview['key'],preview['direction'],preview['frame']))
        with patch.dict(sys.modules, {'ezsynth.main_ez': types.SimpleNamespace(EzsynthBase=Engine),
                                     'ezsynth.aux_classes': types.SimpleNamespace(RunConfig=lambda **kw: types.SimpleNamespace(**{'only_mode':'none',**kw}))}), \
             patch('reezsynth_jobs.progress', side_effect=observe):
            self.run_job()
        self.assertEqual(events, [(0,'Forward',1)])

    def test_single_frame_preview_without_engine(self):
        self.job['frames'] = self.frames[:1]
        subscribe(self.output, [[0,'Keyframe']])
        events = []
        with patch.dict(sys.modules, {'torch': None, 'ezsynth.main_ez': None}), \
             patch('reezsynth_jobs.progress', side_effect=lambda percent, stage, preview=None: events.append(preview) if preview else None):
            self.run_job()
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['direction'],'Keyframe')
        self.assertTrue(Path(events[0]['path']).is_file())


class ImageCaptureTests(unittest.TestCase):
    setUp = adapter.RenderAdapterTests.setUp
    run_job = adapter.RenderAdapterTests.run_job
    prepare = image_adapter.ImageAdapterTests.prepare

    def test_image_result_can_be_previewed_before_outputs_are_saved(self):
        self.prepare()
        subscribe(self.output, [['Image','Image']])
        events = []
        def observe(percent, stage, preview=None):
            if preview:
                self.assertFalse((self.output/'image.png').exists())
                self.assertTrue(Path(preview['path']).is_file())
                events.append(preview)
        with patch('reezsynth_jobs.progress', side_effect=observe):
            self.run_job()
        self.assertEqual(len(events),1)
        self.assertEqual(preview_channels(self.job), [('Image','Image')])


class WindowTests(GuiFixture):
    def record(self, key, start, end):
        output = self.root / ('out' + str(key))
        output.mkdir(exist_ok=True)
        path = output / 'job.json'
        path.write_text(json.dumps(dict(key=key, style='unused',
            frames=[[n,'unused'] for n in range(start,end+1)])), encoding='utf-8')
        return dict(output=output, job_path=path)

    def test_open_close_replace_same_filename_and_reopen_latest(self):
        w = self.window()
        record = self.record(12, 10, 14)
        preview = w.preview_window
        preview.begin([record], 8)
        publisher = PreviewPublisher(record['output'])
        self.assertFalse(publisher.request.exists())
        preview.show()
        self.app.processEvents()
        self.assertTrue(publisher.request.exists())
        for value in (30, 180):
            event = publisher.publish(12,'Backward',11,np.full((128,128,3),value,np.uint8))
            preview.receive(event, record)
            image = preview.tiles[(12,'Backward')].pixmap.toImage()
            self.assertEqual(image.pixelColor(0,0).red(), value)
        preview.close()
        self.app.processEvents()
        self.assertFalse(publisher.request.exists())
        self.assertFalse(preview.refresh_timer.isActive())
        self.assertTrue(preview.tiles[(12,'Backward')].pixmap.isNull())
        self.assertIsNone(publisher.publish(12,'Backward',10,np.zeros((128,128,3),np.uint8)))
        preview.show()
        self.app.processEvents()
        self.assertEqual(preview.tiles[(12,'Backward')].pixmap.toImage().pixelColor(0,0).red(), 180)
        # Reject a late/mismatched worker's image even if the key/direction matches.
        other = self.record(99,98,100)
        preview.receive(dict(event, path=str(self.root/'outside.png')), record)
        preview.receive(event, other)
        self.assertEqual(preview.tiles[(12,'Backward')].path, Path(event['path']))
        preview.end()
        self.assertFalse(publisher.request.exists())

    def test_cap_advances_to_later_jobs_and_old_tiles_are_disposed(self):
        w = self.window()
        records = [self.record(0,0,2), self.record(4,2,4)]
        p = w.preview_window
        p.begin(records, 1)
        p.show()
        p.activate(records[0])
        self.assertEqual(p.entries, [(0,'Forward')])
        p.finish(records[0])
        p.activate(records[1])
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(p.entries, [(4,'Backward')])
        self.assertEqual(len(p.findChildren(PreviewTile)), 1)
        self.assertFalse((records[0]['output']/PREVIEW_DIR/'request.json').exists())
        # Restarting a queue must not retain old full-image widgets.
        p.begin(records[:1], 8)
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(len(p.findChildren(PreviewTile)), 1)

    def test_single_direction_uses_full_row_and_grouped_grid_order(self):
        w = self.window()
        records = [self.record(0,0,2),self.record(4,2,6)]
        p = w.preview_window
        p.begin(records, 8)
        p.show()
        self.app.processEvents()
        self.assertEqual(p.grid.getItemPosition(p.grid.indexOf(p.tiles[(0,'Forward')])), (0,0,1,2))
        self.assertEqual(p.grid.getItemPosition(p.grid.indexOf(p.tiles[(4,'Backward')])), (1,0,1,1))
        self.assertEqual(p.grid.getItemPosition(p.grid.indexOf(p.tiles[(4,'Forward')])), (1,1,1,1))
        p.layout_mode.setCurrentIndex(1)
        p.resize(1200,400)
        self.app.processEvents()
        wide = p.grid.getItemPosition(p.grid.indexOf(p.tiles[(4,'Forward')]))
        p.resize(400,1200)
        self.app.processEvents()
        tall = p.grid.getItemPosition(p.grid.indexOf(p.tiles[(4,'Forward')]))
        self.assertNotEqual(wide[:2], tall[:2])


MOCK_STREAM_RENDERER = r"""
import json
import time
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, SOURCE_PATH)
from reezsynth_preview_transport import PreviewPublisher

def render_job(job_path):
    job = json.loads(Path(job_path).read_text(encoding='utf-8'))
    output = Path(job['output'])
    key = job['key']
    direction = 'Forward' if key == job['frames'][0][0] else 'Backward'
    publisher = PreviewPublisher(output)
    for index in range(1, 4):
        if index > 1:
            until = time.monotonic() + 15
            while not (output / ('allow_' + str(index))).exists():
                if time.monotonic() > until:
                    raise RuntimeError('Preview test synchronization timed out')
                time.sleep(.01)
        preview = publisher.publish(key, direction, key + index if direction == 'Forward' else key - index,
                                    np.full((128,128,3), index*60, np.uint8))
        message = dict(percent=index*25, stage='Synthesis', preview=preview)
        print('\n@@REEZSYNTH_PROGRESS@@' + json.dumps(message), flush=True)
        (output / ('step_' + str(index))).write_text('captured' if preview else 'hidden')
    (output / 'COMPLETE.txt').write_text('done')

if __name__ == '__main__':
    render_job(sys.argv[1])
"""


class ProcessPreviewTests(LifecycleFixture):
    def test_cancellation_releases_capture_and_restart_rejects_old_event(self):
        script = MOCK_STREAM_RENDERER.replace('SOURCE_PATH', repr(str(SOURCE)))
        (self.root/'reezsynth_jobs.py').write_text(script, encoding='utf-8')
        w = self.w
        w.preview_window.show()
        w.run_rows([w.rows[0]])
        self.until(lambda: w.current is not None and (w.current['output']/'step_1').exists(), seconds=10)
        old = dict(w.current)
        old_path = old['output']/PREVIEW_DIR/'0_forward.png'
        w.stop_queue()
        self.until(lambda: not w.busy)
        self.assertFalse((old['output']/PREVIEW_DIR/'request.json').exists())
        w.run_rows([w.rows[0]])
        self.until(lambda: w.current is not None and (w.current['output']/'step_1').exists(), seconds=10)
        self.until(lambda: w.preview_window.tiles[(0,'Forward')].path != old_path)
        new_path = w.preview_window.tiles[(0,'Forward')].path
        w.preview_window.receive(dict(key=0,direction='Forward',frame=99,path=str(old_path)),old)
        self.assertEqual(w.preview_window.tiles[(0,'Forward')].path,new_path)
        w.stop_queue()
        self.until(lambda: not w.busy)

    def test_frames_arrive_before_completion_shared_isolated_and_parallel(self):
        script = MOCK_STREAM_RENDERER.replace('SOURCE_PATH', repr(str(SOURCE)))
        (self.root/'reezsynth_jobs.py').write_text(script, encoding='utf-8')
        for shared, parallel in ((True,False),(False,False),(False,True)):
            with self.subTest(shared=shared,parallel=parallel):
                w = self.w
                w.options.widgets['application']['parallel'].setChecked(parallel)
                w.reuse_worker.setChecked(shared)
                w.preview_window.show()
                w.run_rows(list(w.rows) if parallel else [w.rows[0]])
                self.until(lambda: len(list(w.batch.rglob('step_1'))) == (2 if parallel else 1), seconds=10)
                self.until(lambda: all(not t.pixmap.isNull() for t in w.preview_window.tiles.values()))
                self.assertTrue(w.busy)
                self.assertFalse(list(w.batch.rglob('COMPLETE.txt')))
                outputs = [p.parent for p in w.batch.rglob('step_1')]
                w.preview_window.close()
                for out in outputs:
                    (out/'allow_2').touch()
                self.until(lambda: all((out/'step_2').exists() for out in outputs))
                self.assertTrue(all((out/'step_2').read_text() == 'hidden' for out in outputs))
                w.preview_window.show()
                for out in outputs:
                    (out/'allow_3').touch()
                self.until(lambda: not w.busy)
                self.assertTrue(all(t.pixmap.toImage().pixelColor(0,0).red() == 180
                                    for t in w.preview_window.tiles.values()))
                self.assertFalse(w.preview_window.lease_timer.isActive())


if __name__ == '__main__':
    unittest.main()
