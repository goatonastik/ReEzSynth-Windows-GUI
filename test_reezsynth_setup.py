"""Installation safeguards and launcher checks; no installs or rendering."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from check_reezsynth import verify_assets

ROOT = Path(__file__).resolve().parent


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reezsynth setup (test) ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def manifest(self, name='asset.bin'):
        (self.root / 'runtime-assets.json').write_text(json.dumps({
            'version': 1, 'files': {name: hashlib.sha256(b'known asset').hexdigest()}
        }), encoding='utf-8')

    def test_asset_missing_corrupt_and_valid(self):
        self.manifest()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            verify_assets(self.root)
        asset = self.root / 'asset.bin'
        asset.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'differs'):
            verify_assets(self.root)
        asset.write_bytes(b'known asset')
        self.assertEqual(verify_assets(self.root), 1)

    def test_asset_traversal_rejected(self):
        self.manifest('../outside.bin')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            verify_assets(self.root)

    def test_bundled_raft_extension_is_hash_pinned(self):
        requirement = (ROOT / 'requirements-raft-extension.txt').read_text(encoding='utf-8')
        wheel = ROOT / 'wheels' / 'reezsynth_alt_cuda_corr-0.2.0-cp311-cp311-win_amd64.whl'
        with wheel.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        self.assertIn('./wheels/' + wheel.name, requirement)
        self.assertIn('sha256:' + digest, requirement)
        self.assertEqual(verify_assets(ROOT), 3)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows launcher')
    def test_launcher_active_environment_and_argument_forwarding(self):
        self.launch_probe(active=True)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows launcher')
    def test_launcher_saved_custom_conda_location(self):
        self.launch_probe(active=False)

    def launch_probe(self, active):
        conda = Path(sys.prefix).parent.parent / 'Scripts' / 'conda.exe'
        if not active and not conda.is_file():
            self.skipTest('Requires a named Conda environment')
        shutil.copy2(ROOT / 'run_reezsynth.bat', self.root)
        (self.root / 'probe.py').write_text(
            'import json,sys\nprint("PROBE:"+json.dumps([sys.executable,sys.argv[1:]]))\n',
            encoding='utf-8')
        env = os.environ.copy()
        for key in list(env):
            if key.startswith('CONDA_'):
                env.pop(key)
        env.pop('REEZSYNTH_ENV', None)
        env['CONDA_DEFAULT_ENV'] = 'reezsynth-probe' if active else ''
        env['CONDA_PREFIX'] = sys.prefix if active else ''
        env.pop('CONDA_EXE', None)
        name = 'reezsynth-probe' if active else Path(sys.prefix).name
        (self.root / '.reezsynth-env-name.txt').write_text(name, encoding='utf-8')
        (self.root / '.reezsynth-conda-path.txt').write_text(str(conda), encoding='utf-8')
        result = subprocess.run(
            'cmd.exe /d /c run_reezsynth.bat probe.py "argument with spaces" 42',
            cwd=self.root, env=env, input='', capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        line = next(line for line in result.stdout.splitlines() if line.startswith('PROBE:'))
        executable, args = json.loads(line[6:])
        self.assertEqual(Path(executable).resolve(), Path(sys.executable).resolve())
        self.assertEqual(args, ['argument with spaces', '42'])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows setup')
    def test_setup_plan_leaves_no_local_configuration(self):
        shutil.copy2(ROOT / 'setup_reezsynth.ps1', self.root)
        # Plan needs an existing executable path, but must never invoke it.
        result = subprocess.run([
            'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            str(self.root / 'setup_reezsynth.ps1'), '-Plan', '-CondaExe', sys.executable,
        ], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Plan only', result.stdout)
        self.assertIn('requirements-raft-extension.txt', result.stdout)
        self.assertEqual(list(self.root.iterdir()), [self.root / 'setup_reezsynth.ps1'])


if __name__ == '__main__':
    unittest.main()
