"""Transparent FuouM representation, GUI, and render-adapter contracts."""
import unittest
import numpy as np
import types
import sys
from unittest.mock import patch
from reezsynth_fuoum_alpha import associated_style, straight_output, clip_artwork, composite_source


class FuoumAlphaTests(unittest.TestCase):
    def test_preview_thumbnail_ignores_hidden_rgb_and_preserves_input(self):
        import tempfile
        import time
        import json
        import cv2
        from pathlib import Path
        from reezsynth_preview_transport import PreviewPublisher
        with tempfile.TemporaryDirectory() as temporary:
            publisher = PreviewPublisher(temporary)
            publisher.root.mkdir()
            publisher.request.write_text(json.dumps(dict(updated=time.time(), channels=[[0, 'Forward']])))
            pixels = np.full((2, 2, 4), [255, 255, 255, 0], np.uint8)
            pixels[0, 0] = [0, 0, 0, 255]
            original = pixels.copy()
            with patch('reezsynth_preview_transport.MAX_EDGE', 1):
                message = publisher.publish(0, 'Forward', 1, pixels)
            self.assertIsNotNone(message)
            result = cv2.imdecode(np.frombuffer(Path(message['path']).read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
            np.testing.assert_array_equal(result[0, 0], [0, 0, 0, 64])
            np.testing.assert_array_equal(pixels, original)
            self.assertFalse(list(publisher.root.glob('*.part')))

    def test_hidden_colors_have_no_influence(self):
        a = np.full((8, 8, 4), [0, 0, 0, 0], np.uint8)
        a[2:6, 2:6] = [0, 0, 0, 255]
        b = a.copy(); b[b[..., 3] == 0, :3] = 255
        for size in (None, (4, 4), (12, 12)):
            np.testing.assert_array_equal(associated_style(a, size), associated_style(b, size))

    def test_black_strokes_and_accents(self):
        raw = np.array([[[0, 0, 0, 0], [0, 0, 0, 64], [255, 255, 255, 128], [0, 0, 90, 255]]], np.uint8)
        np.testing.assert_array_equal(straight_output(associated_style(raw)), raw)

    def test_alpha_survives_without_opaque_background(self):
        for opacity in (0, 1, 128, 255):
            raw = np.full((4, 4, 4), [255, 255, 255, opacity], np.uint8)
            out = straight_output(associated_style(raw))
            np.testing.assert_array_equal(out[..., 3], raw[..., 3])
            self.assertTrue(np.all(out[..., :3] == (255 if opacity else 0)))

    def test_resize_does_not_make_white_hidden_color_halo(self):
        raw = np.full((2, 2, 4), [255, 255, 255, 0], np.uint8)
        raw[0, 0] = [0, 0, 0, 255]
        out = straight_output(associated_style(raw, (1, 1)))
        np.testing.assert_array_equal(out[0, 0], [0, 0, 0, 64])

    def test_mask_clips_color_and_alpha_together(self):
        raw = np.full((2, 3, 4), [255, 255, 255, 128], np.uint8)
        mask = np.tile(np.array([0, 128, 255], np.uint8), (2, 1))
        out = straight_output(clip_artwork(associated_style(raw), mask))
        np.testing.assert_array_equal(out[0, :, 3], [0, 64, 128])
        np.testing.assert_array_equal(out[0, 1:, :3], [[255] * 3] * 2)

    def test_invalid_payloads_rejected(self):
        for raw in (np.zeros((3, 3, 3), np.uint8), np.zeros((3, 3, 4), np.uint16)):
            with self.assertRaises(ValueError):
                associated_style(raw)
        with self.assertRaises(ValueError):
            associated_style(np.zeros((3, 3, 4), np.uint8), (0, 3))
        with self.assertRaises(ValueError):
            clip_artwork(np.zeros((3, 3, 4), np.uint8), np.zeros((2, 2), np.uint8))

    def test_composite_is_explicitly_opaque(self):
        source = np.full((2, 2, 3), 200, np.uint8)
        style = associated_style(np.full((2, 2, 4), [0, 0, 0, 128], np.uint8))
        out = composite_source(style, source, np.full((2, 2), 255, np.uint8))
        np.testing.assert_array_equal(out[..., 3], np.full((2, 2), 255, np.uint8))
        np.testing.assert_array_equal(out[..., :3], np.full((2, 2, 3), 100, np.uint8))
        transparent = composite_source(np.zeros((2, 2, 4), np.uint8), source, np.full((2, 2), 255, np.uint8))
        np.testing.assert_array_equal(transparent[..., :3], source)
        with self.assertRaises(ValueError):
            composite_source(style, [[[]]], np.full((2, 2), 255, np.uint8))

    def test_reconstruction_receives_rgb_only_and_alpha_follows_errors(self):
        from reezsynth_fuoum_pipeline import blend_aligned
        a = np.full((8, 8, 4), [30, 30, 30, 64], np.uint8)
        b = np.full((8, 8, 4), [40, 40, 40, 192], np.uint8)
        ea = np.zeros((8, 8), np.float32); eb = np.ones_like(ea)
        ea[:, 4:] = 2
        class Reconstructor:
            def __init__(self, **kwargs):
                pass
            def run(self, hist, forward, backward, masks):
                assert forward[0].shape[2] == backward[0].shape[2] == 3
                return hist
        config = types.SimpleNamespace(model_dump=lambda: dict(poisson_solver='disabled',
            poisson_maxiter=None, poisson_grad_weight_l=2.5, poisson_grad_weight_ab=.5))
        with patch.dict(sys.modules, {'ezsynth.utils.blend_logic': types.SimpleNamespace(Reconstructor=Reconstructor),
                'ezsynth.utils.warp_utils': types.SimpleNamespace(Warp=lambda *args: None)}):
            result = blend_aligned([a], [b], [ea], [eb], [], config)[0]
        self.assertEqual(result.shape, (8, 8, 4))
        np.testing.assert_array_equal(result[:, :4, 3], 64)
        np.testing.assert_array_equal(result[:, 4:, 3], 192)


from tests.test_reezsynth_gui import GuiFixture

class FuoumAlphaGuiTests(GuiFixture):
    def test_preview_checkerboard_and_opaque_pixels(self):
        from PySide6.QtGui import QImage, QPixmap
        from reezsynth_preview import PreviewTile
        tile = PreviewTile('')
        self.addCleanup(tile.close)
        tile.resize(256, 256)
        image = QImage(256, 256, QImage.Format.Format_ARGB32)
        image.fill(0)
        tile.pixmap = QPixmap.fromImage(image)
        tile.show(); self.app.processEvents()
        capture = tile.grab().toImage()
        self.assertEqual(capture.pixelColor(8, 72).name(), '#eeeeee')
        self.assertEqual(capture.pixelColor(24, 72).name(), '#c8c8c8')
        image.fill(0xff000000)
        tile.pixmap = QPixmap.fromImage(image); tile.update(); self.app.processEvents()
        self.assertEqual(tile.grab().toImage().pixelColor(8, 72).name(), '#000000')

    def test_mask_toggle_persistence_and_relevance(self):
        from reezsynth_engines import FUOUM, LEGACY
        window = self.window()
        options = window.options
        controls = options.widgets['render']
        controls['engine'].setCurrentText(FUOUM)
        self.assertFalse(controls['fuoum_alpha_mask_mode'].isEnabled())
        controls['do_mask'].setChecked(True)
        self.assertTrue(controls['fuoum_alpha_mask_mode'].isEnabled())
        controls['fuoum_alpha_mask_mode'].setCurrentText('Composite onto source')
        saved = options.snapshot('render')
        options.store.save('render', 'Composite alpha', saved)
        controls['fuoum_alpha_mask_mode'].setCurrentText('Transparent artwork')
        options.apply('render', options.store.groups['render']['Composite alpha'])
        self.assertEqual(options.render()['fuoum_alpha_mask_mode'], 'Composite onto source')
        controls['engine'].setCurrentText(LEGACY)
        self.assertFalse(controls['fuoum_alpha_mask_mode'].isEnabled())


import tests.test_reezsynth_render_adapter as adapter

class FuoumAlphaAdapterTests(unittest.TestCase):
    setUp = adapter.RenderAdapterTests.setUp
    run_job = adapter.RenderAdapterTests.run_job

    def prepare(self, stream=False):
        from reezsynth_engines import FUOUM
        self.job.update(frames=self.frames[:1], render_options=dict(engine=FUOUM, stream_frames=stream),
            engine_runtime=dict(engine=FUOUM, source=str(self.root), python=sys.executable, revision='mock'))
        self.enterContext(patch('reezsynth_fuoum.activate_fuoum'))
        self.enterContext(patch('reezsynth_fuoum.write_engine_manifest'))

    def save_style(self, raw):
        from pathlib import Path
        import cv2
        Path(self.job['style']).write_bytes(cv2.imencode('.png', raw)[1].tobytes())

    def output_pixels(self):
        import cv2
        return cv2.imread(str(self.output / '000.png'), cv2.IMREAD_UNCHANGED)

    def test_exact_payload_and_storage_cleanup(self):
        self.prepare(True)
        raw = np.full((128, 128, 4), [220, 40, 80, 0], np.uint8)
        raw[30:90, 30:90] = [30, 90, 120, 1]
        self.save_style(raw)
        self.run_job()
        np.testing.assert_array_equal(self.output_pixels(), raw)
        self.assertTrue((self.output / 'COMPLETE.txt').is_file())
        self.assertFalse(list(self.output.glob('.frame-storage-*')))
        self.assertTrue((self.output / 'alpha_manifest.json').is_file())

    def test_both_mask_modes(self):
        from pathlib import Path
        import cv2
        self.prepare()
        raw = np.zeros((128, 128, 4), np.uint8)
        self.save_style(raw)
        mask = self.root / 'mask.png'; mask.write_bytes(cv2.imencode('.png', np.full((128, 128), 255, np.uint8))[1].tobytes())
        self.job.update(masks=[[0, str(mask)]])
        self.job['render_options']['do_mask'] = True
        self.run_job()
        self.assertTrue(np.all(self.output_pixels()[..., 3] == 0))
        (self.output / 'COMPLETE.txt').unlink()
        self.job['render_options']['fuoum_alpha_mask_mode'] = 'Composite onto source'
        self.run_job()
        np.testing.assert_array_equal(self.output_pixels(), np.full((128, 128, 4), [40, 40, 40, 255], np.uint8))

    def test_inactive_premask_does_not_round_exact_key(self):
        self.prepare()
        self.job['render_options']['pre_mask'] = True
        raw = np.full((128, 128, 4), [70, 90, 110, 1], np.uint8)
        self.save_style(raw); self.run_job()
        np.testing.assert_array_equal(self.output_pixels(), raw)

    def test_transparent_mp4_rejected_without_complete_marker(self):
        self.prepare()
        self.save_style(np.zeros((128, 128, 4), np.uint8))
        self.job['video_export'] = {'enabled': True}
        with patch('reezsynth_video_export.ffmpeg_executable', return_value='ffmpeg'), \
                self.assertRaisesRegex(ValueError, 'cannot preserve alpha'):
            self.run_job()
        self.assertFalse((self.output / 'COMPLETE.txt').exists())

    def test_resized_keyframe_ignores_hidden_rgb_and_preserves_inputs(self):
        import cv2
        import json
        from pathlib import Path
        self.prepare()
        source_path = Path(self.job['frames'][0][1])
        source_path.write_bytes(cv2.imencode('.png', np.full((256, 256, 3), 40, np.uint8))[1].tobytes())
        raw = np.full((256, 256, 4), [255, 255, 255, 0], np.uint8)
        raw[0, 0] = [0, 0, 0, 255]
        self.save_style(raw)
        style_path = Path(self.job['style'])
        original_source, original_style = source_path.read_bytes(), style_path.read_bytes()
        self.job['processing_size'] = [128, 128]
        self.run_job()
        np.testing.assert_array_equal(self.output_pixels(), straight_output(associated_style(raw, (128, 128))))
        np.testing.assert_array_equal(self.output_pixels()[0, 0], [0, 0, 0, 64])
        self.assertEqual(source_path.read_bytes(), original_source)
        self.assertEqual(style_path.read_bytes(), original_style)
        manifest = json.loads((self.output / 'alpha_manifest.json').read_text())
        self.assertFalse(manifest['exact_keyframes'])

    def test_nonopaque_16_bit_keyframe_rejected_without_completion(self):
        self.prepare()
        self.save_style(np.full((128, 128, 4), [0, 0, 0, 32768], np.uint16))
        with self.assertRaisesRegex(ValueError, '8-bit RGBA'):
            self.run_job()
        self.assertFalse((self.output / 'COMPLETE.txt').exists())

    def prepare_opaque_export(self):
        import cv2
        self.prepare(True)
        self.save_style(np.full((128, 128, 4), [0, 0, 0, 128], np.uint8))
        mask = self.root / 'mask.png'
        mask.write_bytes(cv2.imencode('.png', np.full((128, 128), 255, np.uint8))[1].tobytes())
        self.job.update(masks=[[0, str(mask)]], video_export={'enabled': True})
        self.job['render_options'].update(do_mask=True, fuoum_alpha_mask_mode='Composite onto source')
        self.enterContext(patch('reezsynth_video_export.ffmpeg_executable', return_value='ffmpeg'))

    def test_composite_export_commits_only_after_encoder_success(self):
        self.prepare_opaque_export()
        def encode(output, numbers, padding, settings, **kwargs):
            self.assertFalse((output / 'COMPLETE.txt').exists())
            self.assertTrue((output / 'alpha_manifest.json').is_file())
            self.assertTrue(np.all(self.output_pixels()[..., 3] == 255))
            (output / 'render.mp4').write_bytes(b'mock encoded artifact')
        with patch('reezsynth_video_export.export_rendered_video', side_effect=encode) as encoder:
            self.run_job()
        encoder.assert_called_once()
        self.assertTrue((self.output / 'COMPLETE.txt').is_file())
        self.assertFalse(list(self.output.glob('.frame-storage-*')))

    def test_composite_encoder_failure_does_not_commit_and_cleans_storage(self):
        self.prepare_opaque_export()
        with patch('reezsynth_video_export.export_rendered_video', side_effect=RuntimeError('encoder failed')), \
                self.assertRaisesRegex(RuntimeError, 'encoder failed'):
            self.run_job()
        self.assertFalse((self.output / 'COMPLETE.txt').exists())
        self.assertFalse(list(self.output.glob('.frame-storage-*')))
