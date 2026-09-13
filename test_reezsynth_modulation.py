"""Modulation channel/target identity, native buffer safety and workflow tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from reezsynth_config import validate_render, PresetStore
from reezsynth_image import validate_image_settings
from reezsynth_modulation import (pack_maps, read_map, legacy_modulation,
    VideoModulation, validate_video_maps)
import test_reezsynth_image as image_tests
from test_reezsynth_lifecycle import LifecycleFixture, gui
from test_reezsynth_gui import GuiFixture


def write(path, value):
    path.write_bytes(cv2.imencode('.png', value)[1].tobytes())
    return str(path)


class ModulationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_pack_mixed_channels_and_validate_native_inputs(self):
        gray = np.zeros((4, 5), np.uint8)
        rgb = np.zeros((4, 5, 3), np.uint8)
        pairs = [(gray, gray, 1), (rgb, rgb, 2)]
        actual = pack_maps(pairs, [None, np.full((4, 5), 128, np.uint8)])
        self.assertEqual(actual.shape, (4, 5, 4))
        self.assertTrue(np.all(actual[..., 0] == 255))
        self.assertTrue(np.all(actual[..., 1:] == 128))
        self.assertTrue(actual.flags.c_contiguous)
        self.assertIsNone(pack_maps(pairs, [None, None]))
        for maps in ([gray], [gray, np.zeros((5, 4), np.uint8)],
                     [gray, rgb], [gray, gray.astype(np.float32)]):
            with self.subTest(maps=str([getattr(v, 'shape', None) for v in maps])), self.assertRaises(ValueError):
                pack_maps(pairs, maps)
        with self.assertRaisesRegex(ValueError, '24'):
            pack_maps([(rgb, rgb, 1)] * 9, [gray] * 9)

    def test_map_file_type_shape_and_processing_resize(self):
        path = self.root / 'map.png'
        write(path, np.tile(np.arange(8, dtype=np.uint8), (4, 1)))
        value = read_map(path, (4, 8), (4, 2))
        self.assertEqual(value.shape, (2, 4))
        self.assertEqual(value.dtype, np.uint8)
        with self.assertRaisesRegex(ValueError, 'target dimensions'):
            read_map(path, (8, 4))
        for image in (np.zeros((4, 8), np.uint16), np.zeros((4, 8, 3), np.uint8)):
            write(path, image)
            with self.assertRaisesRegex(ValueError, '8-bit grayscale'):
                read_map(path, (4, 8))

    def test_native_buffer_size_check_and_exception_restoration(self):
        calls = []
        def native(*args):
            calls.append(args)
            raise RuntimeError('native failed')
        library = types.SimpleNamespace(ebsynthRun=native)
        eb = types.SimpleNamespace(runner=types.SimpleNamespace(libebsynth=library))
        value = np.full((4, 5, 3), 128, np.uint8)
        arguments = [None] * 24
        arguments[2], arguments[7], arguments[8] = 3, 5, 4
        with self.assertRaisesRegex(RuntimeError, 'native failed'):
            with legacy_modulation(eb, value):
                eb.runner.libebsynth.ebsynthRun(*arguments)
        self.assertEqual(calls[0][10], value.tobytes())
        self.assertIs(eb.runner.libebsynth, library)
        arguments[2] = 4
        with self.assertRaisesRegex(ValueError, 'channel count'):
            with legacy_modulation(eb, value):
                eb.runner.libebsynth.ebsynthRun(*arguments)
        self.assertEqual(len(calls), 1)
        self.assertIs(eb.runner.libebsynth, library)

    def test_video_targets_and_extra_guides_with_bounded_storage(self):
        from reezsynth_sequence import frame_storage, DiskSequence
        numbers = [100, 101, 102]
        paths = [[n, write(self.root / f'map{n}.png', np.full((128, 128), (n - 100) * 127, np.uint8))]
                 for n in numbers]
        options = validate_render(dict(modulation_guide='Video guide', stream_frames=True))
        job = dict(modulation_frames=paths, render_options=options, output=str(self.root))
        rgb = np.zeros((128, 128, 3), np.uint8)
        gray = np.zeros((128, 128), np.uint8)
        pairs = [(gray, gray, 1), (rgb, rgb, 1), (rgb, rgb, 1), (rgb, rgb, 1), (gray, gray, 1)]
        with frame_storage(job):
            maps = VideoModulation(job, options, numbers, rgb.shape, (128, 128))
            self.assertIsInstance(maps.values, DiskSequence)
            for target in (102, 101, 100, 101):  # Reverse and repeated passes use target identity.
                packed = maps.for_guides(pairs, target)
                self.assertTrue(np.all(packed[..., 1:4] == (target - 100) * 127))
                self.assertTrue(np.all(packed[..., 0] == 255))
                self.assertTrue(np.all(packed[..., 4:] == 255))
            maps.mode = 'All guides'
            self.assertTrue(np.all(maps.for_guides(pairs, 100) == 0))
            with self.assertRaisesRegex(ValueError, 'actual synthesis target'):
                maps.for_guides(pairs, None)
            maps.finish(self.root)
        metadata = json.loads((self.root / 'modulation_manifest.json').read_text())
        self.assertEqual(metadata['synthesis_targets'], numbers)
        self.assertEqual(len(metadata['layouts']), 2)
        with self.assertRaisesRegex(ValueError, 'frame numbers'):
            VideoModulation(dict(modulation_frames=paths[:-1]), options, numbers, rgb.shape, (128, 128))

    def test_folder_preflight_and_off_state(self):
        path = self.root / 'map0100.png'
        write(path, np.zeros((128, 128), np.uint8))
        video = {100: path}
        options = validate_render(dict(modulation_guide='All guides', modulation_dir=str(self.root)))
        self.assertEqual(validate_video_maps(options, video), {100: path.resolve()})
        write(self.root / 'map0101.png', np.zeros((128, 128), np.uint8))
        with self.assertRaisesRegex(ValueError, 'frame numbers'):
            validate_video_maps(options, video)
        options['modulation_guide'] = 'Off'
        self.assertEqual(validate_video_maps(options, {}), {})
        with self.assertRaises(ValueError):
            validate_render(dict(modulation_guide='Unknown'))
        with self.assertRaises(ValueError):
            validate_render(dict(modulation_dir=None))

    def test_legacy_cpu_and_auto_modulation_are_rejected_but_off_is_usable(self):
        from reezsynth_modulation import require_backend
        for backend in ('cpu', 'auto'):
            options = validate_render(dict(ebsynth_backend=backend, modulation_guide='All guides'))
            require_backend(options, False)
            with self.assertRaisesRegex(ValueError, 'explicit CUDA'):
                validate_video_maps(options, {})
            with self.assertRaisesRegex(ValueError, 'explicit CUDA'):
                VideoModulation({}, options, [100, 101], (128, 128, 3), (128, 128))

    def test_recovery_fingerprints_enabled_maps_and_image_guides(self):
        from reezsynth_queue_recovery import snapshot_inputs, input_changes
        path = self.root / 'map.png'
        write(path, np.zeros((4, 5), np.uint8))
        video = dict(render_options=dict(modulation_guide='All guides'), modulation_frames=[[100, str(path)]])
        image = dict(image_synthesis=dict(guides=[dict(source='', target='', modulation=str(path))]))
        for job in (video, image):
            snapshot = snapshot_inputs(job, self.root / 'job.json')
            self.assertEqual(len(snapshot), 1)
            self.assertEqual(input_changes(snapshot), [])
            path.write_bytes(path.read_bytes() + b'changed')
            self.assertEqual(input_changes(snapshot), [str(path.resolve())])
        video['render_options']['modulation_guide'] = 'Off'
        self.assertEqual(snapshot_inputs(video, self.root / 'job.json'), [])


class ImageModulationAdapterTests(unittest.TestCase):
    setUp = image_tests.ImageAdapterTests.setUp
    run_job = image_tests.ImageAdapterTests.run_job
    prepare = image_tests.ImageAdapterTests.prepare

    def test_real_legacy_wrapper_preserves_primary_last_channel_order(self):
        self.prepare()
        primary = write(self.root / 'primary.png', np.zeros((80, 160), np.uint8))
        extra = write(self.root / 'extra.png', np.full((80, 160), 128, np.uint8))
        target = write(self.root / 'color.png', np.zeros((80, 160, 3), np.uint8))
        self.settings.update(modulation=primary, guides=[dict(source=self.job['image_synthesis']['style'],
                             target=target, weight=2, modulation=extra)])
        import sys
        Engine = sys.modules['ezsynth.main_ez'].ImageSynthBase
        original = Engine.__init__
        spec = importlib.util.spec_from_file_location('isolated_eb', Path(__file__).parent / 'ezsynth/utils/_eb.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        seen = []
        low = module.EbsynthRunner()
        library = types.SimpleNamespace(ebsynthRun=lambda *a: seen.append(a))
        low.libebsynth = library
        def initialize(runner, *args, **kwargs):
            original(runner, *args, **kwargs)
            runner.eb.runner = low
            runner.eb.run = lambda style, guides: low.run(style, guides)
        with patch.object(Engine, '__init__', initialize):
            self.run_job()
        packed = np.frombuffer(seen[0][10], np.uint8).reshape(80, 160, 4)
        self.assertTrue(np.all(packed[..., :3] == 128))
        self.assertTrue(np.all(packed[..., 3] == 0))
        self.assertIs(low.libebsynth, library)
        metadata = json.loads((self.output / 'modulation_manifest.json').read_text())
        self.assertEqual([g['guide'] for g in metadata['layouts'][0]], ['Additional guide 1', 'Primary guide'])

    def test_invalid_image_map_rejected_before_engine(self):
        captured = self.prepare()
        self.settings['modulation'] = write(self.root / 'wrong.png', np.zeros((128, 128), np.uint8))
        with self.assertRaisesRegex(ValueError, 'target dimensions'):
            self.run_job()
        self.assertNotIn('runner', captured)
        self.assertFalse((self.output / 'COMPLETE.txt').exists())

    def test_cpu_modulation_rejected_before_image_engine(self):
        captured = self.prepare()
        self.settings['modulation'] = write(self.root / 'valid.png', np.zeros((80, 160), np.uint8))
        self.job['render_options'] = dict(ebsynth_backend='cpu')
        with self.assertRaisesRegex(ValueError, 'explicit CUDA'):
            self.run_job()
        self.assertNotIn('runner', captured)
        self.assertFalse((self.output / 'COMPLETE.txt').exists())

    def test_manifest_write_failure_prevents_completion(self):
        self.prepare()
        self.settings['modulation'] = write(self.root / 'valid.png', np.zeros((80, 160), np.uint8))
        from reezsynth_engines import FUOUM
        self.job['render_options'] = dict(engine=FUOUM)
        # Exercise the actual image adapter without requiring a FuouM checkout.
        from reezsynth_image import render_image_job
        with patch('reezsynth_fuoum.synthesize_image', return_value=(
                np.zeros((80, 160, 3), np.uint8), np.zeros((80, 160), np.float32))), \
             patch('reezsynth_modulation.write_manifest', side_effect=OSError('metadata blocked')), \
             self.assertRaisesRegex(OSError, 'metadata blocked'):
            render_image_job(self.job, lambda *a, **kw: None)
        self.assertFalse((self.output / 'COMPLETE.txt').exists())

    def test_fuoum_image_mapping_is_primary_first(self):
        self.prepare()
        self.settings['modulation'] = write(self.root / 'primary.png', np.zeros((80, 160), np.uint8))
        self.settings['guides'] = [dict(source=self.settings['source'], target=self.settings['target'], weight=2)]
        from reezsynth_engines import FUOUM
        self.job['render_options'] = dict(engine=FUOUM, fuoum_backend='torch')
        from reezsynth_image import render_image_job
        with patch('reezsynth_fuoum.synthesize_image', return_value=(
                np.zeros((80, 160, 3), np.uint8), np.zeros((80, 160), np.float32))) as synthesize:
            render_image_job(self.job, lambda *a, **kw: None)
        packed = synthesize.call_args.kwargs['modulation']
        self.assertTrue(np.all(packed[..., 0] == 0))
        self.assertTrue(np.all(packed[..., 1] == 255))
        self.assertEqual(json.loads((self.output / 'image_manifest.json').read_text())['backend'], 'torch')


class ModulationGuiTests(GuiFixture):
    def test_presets_restore_image_and_video_maps_and_lock_controls(self):
        w = self.window()
        o = w.options
        w.image_synthesis.modulation.setText('primary.png')
        w.image_synthesis.add_guide(dict(source='a.png', target='b.png', weight=2, modulation='extra.png'))
        settings = w.image_synthesis.settings()
        o.store.save('image', 'Maps', settings)
        o.apply('image', {})
        o.apply('image', PresetStore(o.store.path).groups['image']['Maps'])
        self.assertEqual(w.image_synthesis.settings(), settings)
        widgets = o.widgets['render']
        self.assertFalse(widgets['modulation_dir'].isEnabled())
        widgets['modulation_guide'].setCurrentText('Video guide')
        widgets['modulation_dir'].setText('D:/maps')
        o.store.save('render', 'Maps', o.snapshot('render'))
        o.apply('render', PresetStore(o.store.path).groups['render']['Maps'])
        self.assertEqual(o.render()['modulation_dir'], 'D:/maps')
        self.assertTrue(o.modulation_browse.isEnabled())
        w.set_busy(True)
        self.assertFalse(o.modulation_browse.isEnabled())
        self.assertFalse(w.image_synthesis.modulation.isEnabled())
        w.set_busy(False)
        self.assertTrue(o.modulation_browse.isEnabled())
        self.assertEqual(validate_image_settings({'guides': [dict(source='', target='', weight=1)]})['modulation'], '')


class ModulationQueueTests(LifecycleFixture):
    def test_queue_freezes_map_paths_and_recovers_input_fingerprints(self):
        video, _, _, _ = gui.build_plan(self.w.video_dir.text(), self.w.keyframe_dir.text())
        folder = self.root / 'modulation'
        folder.mkdir()
        for number, path in video.items():
            shape = cv2.imread(str(path)).shape[:2]
            write(folder / f'map{number:04d}.png', np.full(shape, 128, np.uint8))
        self.w.options.widgets['render']['modulation_guide'].setCurrentText('Video guide')
        self.w.options.widgets['render']['modulation_dir'].setText(str(folder))
        self.run_queue(shared=True)
        self.until(lambda: not self.w.busy, 10)
        for path in self.w.batch.rglob('job.json'):
            job = json.loads(path.read_text())
            self.assertEqual([n for n, _ in job['modulation_frames']], [n for n, _ in job['frames']])
        journal = json.loads((self.w.batch / '.reezsynth-queue.json').read_text())
        self.assertTrue(all(any('modulation' in item['path'] for item in entry['inputs']) for entry in journal['entries']))


if __name__ == '__main__':
    unittest.main()
