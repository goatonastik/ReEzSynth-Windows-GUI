"""Release packaging policy and installer safety checks."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parent


class PackagingTests(unittest.TestCase):
    def test_tracked_tree_has_no_bundled_raster_media(self):
        tracked = subprocess.run(
            ['git', 'ls-files'], cwd=ROOT, check=True, capture_output=True,
            text=True, encoding='utf-8', errors='strict').stdout.splitlines()
        raster = {'.bmp', '.gif', '.jpeg', '.jpg', '.png', '.tif', '.tiff', '.webp'}
        self.assertEqual([name for name in tracked if Path(name).suffix.lower() in raster], [])
        self.assertFalse(any(name == 'examples' or name.startswith('examples/') for name in tracked))

    def test_runtime_distribution_keeps_only_reviewed_assets_and_notices(self):
        tracked = set(subprocess.run(
            ['git', 'ls-files'], cwd=ROOT, check=True, capture_output=True,
            text=True, encoding='utf-8', errors='strict').stdout.splitlines())
        manifest = json.loads((ROOT / 'runtime-assets.json').read_text(encoding='utf-8'))
        expected = {
            'ezsynth/utils/ebsynth.dll',
            'ezsynth/utils/flow_utils/models/raft-sintel.pth',
            'ezsynth/utils/flow_utils/models/raft-kitti.pth',
            'wheels/reezsynth_alt_cuda_corr-0.2.0-cp311-cp311-win_amd64.whl',
        }
        self.assertEqual(set(manifest['files']), expected)
        self.assertTrue(expected <= tracked)
        self.assertFalse((ROOT / 'ezsynth' / 'utils' / 'flow_utils' / 'models' /
                          'raft-small.pth').exists())
        self.assertTrue({
            'LICENSE',
            'licenses/FuouM-MIT.txt',
            'licenses/NeuFlow-Apache-2.0.txt',
            'third_party/raft_alt_cuda_corr/LICENSE',
        } <= tracked)
        self.assertTrue((ROOT / 'THIRD_PARTY_NOTICES.md').is_file())
        self.assertTrue((ROOT / 'CLEAN_MACHINE_TEST.md').is_file())
        self.assertTrue((ROOT / 'licenses' / 'EF-RAFT-BSD-3-Clause.txt').is_file())
        notices = (ROOT / 'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
        self.assertIn('b198f2d7051eee542c4efc51c2d43dc442630bbf', notices)
        self.assertIn('imageio-ffmpeg 0.6.0', notices)
        self.assertIn("embedded in ReEzSynth's release artifacts", notices)

    def test_builder_requires_reviewed_commit_and_rejects_private_inputs(self):
        script = (ROOT / 'build_release.ps1').read_text(encoding='utf-8')
        for required in (
                'status --porcelain --untracked-files=normal',
                'git -C $root archive',
                "'/examples/'", "'/diagnostic_outputs/'", "'/.engine_envs/'",
                "'/output_synth/'", "'/.reezsynth-cache/'",
                '$forbiddenExtensions', 'SHA256SUMS.txt', 'RELEASE_MANIFEST.json'):
            self.assertIn(required, script)
        self.assertNotIn('gh release', script.lower())

    def test_installer_is_per_user_and_heavy_setup_is_opt_in(self):
        installer = (ROOT / 'installer' / 'ReEzSynth.iss').read_text(encoding='utf-8')
        self.assertIn(r'DefaultDirName={localappdata}\Programs\ReEzSynth', installer)
        self.assertIn('PrivilegesRequired=lowest', installer)
        setup_line = next(line for line in installer.splitlines()
                          if line.startswith('Filename:') and 'setup_reezsynth.ps1' in line)
        self.assertIn('postinstall', setup_line)
        self.assertIn('unchecked', setup_line)
        self.assertIn(r'Filename: "{app}\THIRD_PARTY_NOTICES.md"', installer)
        self.assertIn(r'Filename: "{app}\CLEAN_MACHINE_TEST.md"', installer)
        clean_test = (ROOT / 'CLEAN_MACHINE_TEST.md').read_text(encoding='utf-8')
        self.assertNotIn('check_reezsynth_engines.py --all', clean_test)
        self.assertIn('--fuoum-source engine_sources\\fuoum_reezsynth', clean_test)
        self.assertIn(r'--fuoum-python .engine_envs\fuoum\Scripts\python.exe', clean_test)

    def test_package_workflow_only_builds_manual_candidates(self):
        workflow = (ROOT / '.github' / 'workflows' / 'package.yml').read_text(encoding='utf-8')
        parsed = yaml.safe_load(workflow)
        self.assertEqual(set(parsed['on']), {'workflow_dispatch'})
        self.assertNotIn('actions/create-release', workflow)
        self.assertNotIn('softprops/action-gh-release', workflow)
        self.assertIn('retention-days: 14', workflow)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows PowerShell packaging check')
    def test_source_builder_runs_in_windows_powershell_and_rejects_raster(self):
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        with tempfile.TemporaryDirectory(prefix='reezsynth packaging test ') as directory:
            probe = Path(directory)
            shutil.copy2(ROOT / 'build_release.ps1', probe)
            shutil.copy2(ROOT / 'LICENSE', probe)
            (probe / '.gitignore').write_text('/dist/\n', encoding='utf-8')
            (probe / 'app.py').write_text('print("packaging test")\n', encoding='utf-8')
            subprocess.run(['git', 'init', '--quiet'], cwd=probe, check=True)
            self.commit_probe(probe, 'clean fixture')

            command = [str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass',
                       '-File', str(probe / 'build_release.ps1'),
                       '-Version', '0.1.0-preview.1', '-SourceOnly']
            completed = subprocess.run(command, cwd=probe, text=True, encoding='utf-8',
                                       errors='replace', capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            dist = probe / 'dist'
            manifest = json.loads((dist / 'RELEASE_MANIFEST.json').read_text(encoding='utf-8'))
            head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=probe, check=True,
                                  text=True, capture_output=True).stdout.strip()
            self.assertEqual(manifest['commit'], head)
            self.assertTrue((dist / 'SHA256SUMS.txt').is_file())
            self.assertEqual(len(list(dist.glob('*-source.zip'))), 1)

            (probe / 'forbidden.png').write_bytes(b'not an image')
            self.commit_probe(probe, 'forbidden fixture')
            rejected = subprocess.run(command, cwd=probe, text=True, encoding='utf-8',
                                      errors='replace', capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('forbidden local/example media paths', rejected.stdout + rejected.stderr)

    @staticmethod
    def commit_probe(probe, message):
        subprocess.run(['git', 'add', '--all'], cwd=probe, check=True)
        subprocess.run(['git', '-c', 'user.name=ReEzSynth Test',
                        '-c', 'user.email=test@invalid.example',
                        'commit', '--quiet', '-m', message], cwd=probe, check=True)


if __name__ == '__main__':
    unittest.main()
