"""Generated diagnostic media and media-free release diagnostic contracts."""
import ast
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import diagnose_reezsynth_release as release
from reezsynth_engines import LEGACY
from reezsynth_synthetic_inputs import frame, image_case, mask, style


class SyntheticInputTests(unittest.TestCase):
    def test_frames_styles_and_masks_are_deterministic_and_nontrivial(self):
        first = frame((96, 64), 0, 5)
        repeat = frame((96, 64), 0, 5)
        last = frame((96, 64), 4, 5)
        self.assertEqual(first.shape, (64, 96, 3))
        self.assertEqual(first.dtype, np.uint8)
        self.assertTrue(np.array_equal(first, repeat))
        self.assertFalse(np.array_equal(first, last))
        self.assertGreater(style(first).std(), 0)
        selection = mask((96, 64), 2, 5)
        self.assertEqual(selection.shape, (64, 96))
        self.assertGreater(np.count_nonzero(selection), 0)
        self.assertGreater(np.count_nonzero(selection == 0), 0)
        with self.assertRaisesRegex(ValueError, 'three-channel'):
            style(selection)

    def test_image_case_writes_only_generated_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = image_case(directory, 'case', 2, (80, 60), (120, 40))
            self.assertEqual(len(settings['guides']), 2)
            self.assertEqual(cv2.imread(settings['source']).shape, (60, 80, 3))
            self.assertEqual(cv2.imread(settings['target']).shape, (40, 120, 3))
            self.assertEqual(cv2.imread(settings['guides'][0]['source'], cv2.IMREAD_UNCHANGED).ndim, 3)
            self.assertEqual(cv2.imread(settings['guides'][1]['source'], cv2.IMREAD_UNCHANGED).ndim, 2)
            self.assertTrue(all(Path(item[key]).is_file()
                                for item in settings['guides'] for key in ('source', 'target')))

    def test_operational_python_has_no_example_directory_dependency(self):
        root = Path(__file__).resolve().parent
        tracked = subprocess.run(
            ['git', 'ls-files', '*.py'], cwd=root, text=True, encoding='utf-8',
            errors='strict', check=True, capture_output=True).stdout.splitlines()
        offenders = []
        for relative in tracked:
            if Path(relative).name.startswith('test_'):
                continue
            tree = ast.parse((root / relative).read_text(encoding='utf-8-sig'), filename=relative)
            if any(isinstance(node, ast.Constant) and isinstance(node.value, str) and
                   (node.value == 'examples' or 'examples/' in node.value or
                    'examples\\' in node.value) for node in ast.walk(tree)):
                offenders.append(relative)
        self.assertEqual(offenders, [])

    def test_release_jobs_have_no_bundled_media_dependency(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(release, 'prepare_runtime', return_value={
                    'engine': LEGACY, 'revision': 'test', 'source': '.', 'python': 'python'}):
            runtime, jobs = release.make_jobs(Path(directory), LEGACY, 5, 1, False, images=True)
            self.assertEqual(runtime['engine'], LEGACY)
            self.assertEqual(len(jobs), 5)
            paths = []
            for _, job in jobs:
                if job.get('type') == 'image_synthesis':
                    image = job['image_synthesis']
                    paths.extend([image['style'], image['source'], image['target']])
                else:
                    paths.extend(path for _, path in job['frames'])
                    paths.append(job['style'])
            self.assertTrue(all(Path(path).is_file() for path in paths))
            self.assertTrue(all('examples' not in Path(path).parts for path in paths))


if __name__ == '__main__':
    unittest.main()
