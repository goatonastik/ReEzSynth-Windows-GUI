import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from reezsynth_video_export import export_rendered_video, validate_video_export


class RenderedVideoExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reezsynth video export ')
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        for number in (7, 8, 9):
            (self.output / f'{number:03d}.png').write_bytes(b'png')

    def test_validation_defaults_limits_and_missing_audio(self):
        self.assertEqual(validate_video_export(), {'enabled': False, 'fps': 24.0, 'audio': ''})
        for invalid in ({'extra': 1}, {'enabled': 1}, {'fps': 0}, {'fps': float('nan')}, {'audio': 1}):
            with self.assertRaises(ValueError):
                validate_video_export(invalid)
        with self.assertRaisesRegex(ValueError, 'audio file is missing'):
            validate_video_export({'enabled': True, 'audio': str(self.output / 'missing.wav')},
                                  check_audio=True)

    def test_disabled_export_does_not_run_encoder(self):
        called = []
        self.assertIsNone(export_rendered_video(self.output, [7, 8, 9], 3, {},
                          run=lambda *args, **kwargs: called.append(args), ffmpeg_exe='ffmpeg'))
        self.assertEqual(called, [])

    def test_video_only_export_is_atomic_and_records_metadata(self):
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            Path(command[-1]).write_bytes(b'mp4')
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        result = export_rendered_video(self.output, [7, 8, 9], 3,
            {'enabled': True, 'fps': 23.976}, run=run, ffmpeg_exe='ffmpeg')
        self.assertEqual(result, self.output.resolve() / 'render.mp4')
        self.assertFalse((self.output / 'render.part.mp4').exists())
        self.assertIn(str(self.output.resolve() / '%03d.png'), commands[0])
        self.assertIn('-an', commands[0])
        metadata = json.loads((self.output / 'rendered_video.json').read_text(encoding='utf-8'))
        self.assertEqual((metadata['fps'], metadata['frames']), (23.976, 3))

    def test_audio_is_separate_optional_input_and_failure_cleans_partial(self):
        audio = self.output / 'sound.wav'
        audio.write_bytes(b'wav')
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            Path(command[-1]).write_bytes(b'partial')
            return SimpleNamespace(returncode=1, stdout='', stderr='encoder failed')
        with self.assertRaisesRegex(RuntimeError, 'encoder failed'):
            export_rendered_video(self.output, [7, 8, 9], 3,
                {'enabled': True, 'audio': str(audio)}, run=run, ffmpeg_exe='ffmpeg')
        self.assertIn(str(audio.resolve()), commands[0])
        self.assertIn('apad', commands[0])
        self.assertIn('-t', commands[0])
        self.assertIn('-frames:v', commands[0])
        self.assertFalse((self.output / 'render.part.mp4').exists())
        self.assertFalse((self.output / 'render.mp4').exists())

    def test_missing_or_nonconsecutive_frames_are_rejected_before_encoder(self):
        with self.assertRaisesRegex(ValueError, 'consecutive'):
            export_rendered_video(self.output, [7, 9], 3, {'enabled': True}, ffmpeg_exe='ffmpeg')
        (self.output / '008.png').unlink()
        with self.assertRaisesRegex(ValueError, 'frame is missing'):
            export_rendered_video(self.output, [7, 8, 9], 3, {'enabled': True}, ffmpeg_exe='ffmpeg')


if __name__ == '__main__':
    unittest.main()
