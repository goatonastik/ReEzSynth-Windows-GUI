"""Installer safety and compatibility patch regressions; no network or CUDA."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from setup_fuoum import check_build_prerequisites, ensure_asset, install
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


class PrerequisiteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='reezsynth prerequisites ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(patch('setup_fuoum.sys.platform', 'win32'))
        self.enterContext(patch('setup_fuoum.sys.version_info', (3, 11)))
        self.enterContext(patch('setup_fuoum.shutil.which', side_effect=lambda name: 'git.exe' if name == 'git' else None))

    def test_missing_git_is_reported_without_writes(self):
        with patch('setup_fuoum.shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'Git is required'):
                check_build_prerequisites(self.root / 'source')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_cuda_is_reported_without_source_download(self):
        with patch.dict(os.environ, {'CUDA_HOME': str(self.root / 'missing')}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'CUDA 12.8 toolkit'):
                check_build_prerequisites(self.root / 'source')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_native_binary_needs_no_compiler_prerequisites(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'ebsynth_torch.test.pyd').write_bytes(b'existing binary')
        with patch('setup_fuoum.source_revision', return_value='aaa8d06170e6cc59054410aa9c422edd789f7ab2'), \
             patch('setup_fuoum.subprocess.check_output') as command:
            result = check_build_prerequisites(source)
        self.assertFalse(result['native_build_required'])
        command.assert_not_called()

    def test_fresh_build_requires_matching_cuda_and_cpp_tools(self):
        cuda = self.root / 'cuda'
        nvcc = cuda / 'bin/nvcc.exe'
        vswhere = self.root / 'Microsoft Visual Studio/Installer/vswhere.exe'
        vcvars = self.root / 'vs/VC/Auxiliary/Build/vcvars64.bat'
        for path in (nvcc, vswhere, vcvars):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'prerequisite placeholder')
        installations = json.dumps([{'installationPath': str(self.root / 'vs')}])
        with patch.dict(os.environ, {'CUDA_HOME': str(cuda), 'ProgramFiles(x86)': str(self.root)}, clear=True):
            with patch('setup_fuoum.subprocess.check_output', side_effect=['Cuda compilation tools, release 12.8, V12.8.93', installations]):
                self.assertTrue(check_build_prerequisites(self.root / 'source')['native_build_required'])
            with patch('setup_fuoum.subprocess.check_output', return_value='release 12.9, V12.9.1'):
                with self.assertRaisesRegex(RuntimeError, 'match its pinned PyTorch'):
                    check_build_prerequisites(self.root / 'source')
            with patch('setup_fuoum.subprocess.check_output', side_effect=['release 12.8, V12.8.93', '[]']):
                with self.assertRaisesRegex(RuntimeError, r'C\+\+ x64 build tools'):
                    check_build_prerequisites(self.root / 'source')
        self.assertFalse((self.root / 'source').exists())


if __name__ == '__main__':
    unittest.main()
