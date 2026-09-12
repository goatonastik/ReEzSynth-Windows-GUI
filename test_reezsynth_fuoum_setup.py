"""Installer safety and compatibility patch regressions; no network or CUDA."""
import contextlib
import hashlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from setup_fuoum import ensure_asset, install
from reezsynth_engines import ROOT


class InstallerTests(unittest.TestCase):
    def test_plan_creates_nothing_and_runs_no_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with patch('setup_fuoum.command') as command, contextlib.redirect_stdout(io.StringIO()):
                install(base / 'source', base / 'env', plan=True, neuflow=True)
            command.assert_not_called()
            self.assertEqual(list(base.iterdir()), [])

    def test_existing_environment_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'keep.txt'
            marker.write_text('preserve')
            with self.assertRaisesRegex(RuntimeError, 'already exists'):
                install(Path(directory) / 'source', directory)
            self.assertEqual(marker.read_text(), 'preserve')

    def test_checkpoint_copy_is_verified_and_never_replaces_changed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            source.write_bytes(b'checkpoint')
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            ensure_asset(target, expected, local=source)
            ensure_asset(target, expected, check=True)
            target.write_bytes(b'user checkpoint')
            with self.assertRaisesRegex(RuntimeError, 'not replaced'):
                ensure_asset(target, expected, local=source)
            self.assertEqual(target.read_bytes(), b'user checkpoint')
            self.assertFalse(list(Path(directory).glob('*.part')))

    def test_bad_download_leaves_no_destination_or_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'weight.pth'
            with patch('setup_fuoum.urllib.request.urlopen', return_value=io.BytesIO(b'wrong')):
                with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                    ensure_asset(target, '0' * 64, url='https://example.invalid/weight')
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_zero_context_patch_applies_and_reverse_checks_on_clean_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            headers = base / 'ebsynth_extension'
            headers.mkdir()
            for name, line, include in (('dispatch.h', 3, 'extension'), ('integral_image.h', 3, 'extension'),
                                        ('kernels.h', 6, 'all')):
                (headers / name).write_text('// header\n' * (line - 1) + f'#include <torch/{include}.h>\n')
            compatibility = ROOT / 'patches/fuoum-windows-torch-types.patch'
            subprocess.run(['git', 'apply', '--unidiff-zero', str(compatibility)], cwd=base, check=True, capture_output=True)
            subprocess.run(['git', 'apply', '--unidiff-zero', '--reverse', '--check', str(compatibility)],
                           cwd=base, check=True, capture_output=True)
            self.assertTrue(all('#include <torch/types.h>' in file.read_text() for file in headers.iterdir()))


if __name__ == '__main__':
    unittest.main()
