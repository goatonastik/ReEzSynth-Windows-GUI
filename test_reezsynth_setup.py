"""Installation safeguards and launcher checks; no installs or rendering."""
import hashlib
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import check_reezsynth_engines

from check_reezsynth import EF_RAFT_MODELS, FLOW_DIFFUSION_MODEL, flow_extra_readiness, verify_assets
from diagnose_reezsynth_adapter import (cancel_worker, render as run_adapter_diagnostic,
                                        render_parallel)
from reezsynth_config import install_optional_flow_files, optional_flow_status, OPTIONAL_FLOW_HASHES
import setup_flowdiffuser
from setup_flowdiffuser import BACKBONES, PACKAGES

ROOT = Path(__file__).resolve().parent


class SetupTests(unittest.TestCase):
    def test_combined_engine_checker_runs_both_components_and_combines_failures(self):
        with contextlib.redirect_stdout(io.StringIO()), \
             patch.object(check_reezsynth_engines, 'run', side_effect=[1, 0]) as run:
            result = check_reezsynth_engines.main([
                '--fuoum-source', 'D:/source',
                '--fuoum-python', 'D:/venv/Scripts/python.exe'])
        self.assertEqual(result, 1)
        self.assertEqual(run.call_count, 2)
        self.assertIn('--raft-extension', run.call_args_list[0].args[0])
        self.assertIn('--check-only', run.call_args_list[1].args[0])
        self.assertIn('--neuflow', run.call_args_list[1].args[0])

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
        self.assertEqual(verify_assets(ROOT), 4)

    def test_optional_flow_readiness_needs_pinned_dependencies_and_backbones(self):
        flow = self.root / 'ezsynth' / 'utils' / 'flow_utils'
        readiness = flow_extra_readiness(self.root, find_spec=lambda _: None)
        self.assertIn('missing weights', readiness['EF-RAFT'][0])
        self.assertIn('missing/incompatible Python packages', readiness['FlowDiffuser'][0])
        self.assertIn('missing offline backbones', readiness['FlowDiffuser'][1])
        self.assertIn(f'missing weights: {FLOW_DIFFUSION_MODEL}', readiness['FlowDiffuser'])
        (flow / 'ef_raft_models').mkdir(parents=True)
        (flow / 'flow_diffusion_models').mkdir()
        for model in EF_RAFT_MODELS:
            (flow / 'ef_raft_models' / f'{model}.pth').write_bytes(b'placeholder')
        (flow / 'flow_diffusion_models' / FLOW_DIFFUSION_MODEL).write_bytes(b'placeholder')
        for backbone in BACKBONES:
            (flow / 'flow_diffusion_models' / f'{backbone}.pth').write_bytes(b'placeholder')
        with patch('reezsynth_config.importlib.metadata.version', side_effect=PACKAGES.__getitem__):
            readiness = flow_extra_readiness(self.root, find_spec=lambda _: object())
        self.assertEqual(readiness, {'EF-RAFT': [], 'FlowDiffuser': []})

    def test_flowdiffuser_requirements_pin_the_tested_dependency_set(self):
        requirements = (ROOT / 'requirements-flowdiffuser.txt').read_text(encoding='utf-8')
        for name, version in PACKAGES.items():
            self.assertIn(f'{name}=={version}', requirements)
        self.assertEqual(set(BACKBONES), {'twins_svt_large', 'twins_svt_small'})

    def test_cupy_cuda13_requirements_pin_the_validated_quarantine_set(self):
        requirements = (ROOT / 'requirements-cupy-cuda13.txt').read_text(encoding='utf-8')
        for requirement in ('cupy-cuda13x[ctk]==14.2.0', 'cuda-toolkit==13.4.1.0',
                            'nvidia-cuda-nvrtc==13.4.59', 'nvidia-cusolver==12.3.2.15'):
            self.assertIn(requirement, requirements)

    def test_flowdiffuser_setup_never_overwrites_an_unexpected_backbone(self):
        model_dir = self.root / 'flow-models'
        model_dir.mkdir()
        (model_dir / 'fixture.pth').write_bytes(b'unexpected')
        downloads = []
        fake_hub = SimpleNamespace(
            hf_hub_download=lambda *args, **kwargs: downloads.append((args, kwargs)))
        fixture_backbones = {
            'fixture': ('official/repository', 'pinned-revision',
                        hashlib.sha256(b'expected').hexdigest())
        }
        with (patch.object(setup_flowdiffuser, 'MODEL_DIR', model_dir),
              patch.object(setup_flowdiffuser, 'BACKBONES', fixture_backbones),
              patch.dict(sys.modules, {'huggingface_hub': fake_hub}),
              patch.object(setup_flowdiffuser.subprocess, 'run')):
            with self.assertRaisesRegex(RuntimeError, 'was not replaced'):
                setup_flowdiffuser.install()
        self.assertEqual(downloads, [])

    def test_optional_flow_file_installer_copies_only_recognized_checkpoints(self):
        source = self.root / 'downloads'
        source.mkdir()
        ef = source / 'ours_sintel.pth'
        ef.write_bytes(b'checkpoint')
        with patch.dict(OPTIONAL_FLOW_HASHES, {'ours_sintel.pth': hashlib.sha256(b'checkpoint').hexdigest()}):
            copied = install_optional_flow_files('EF_RAFT', [ef], self.root)
        self.assertEqual(copied[0].read_bytes(), b'checkpoint')
        self.assertEqual(optional_flow_status(self.root, find_spec=lambda _: None)['EF_RAFT']['models'], ['ours_sintel'])
        replacement = source / 'replacement' / 'ours_sintel.pth'
        replacement.parent.mkdir()
        replacement.write_bytes(b'different checkpoint')
        with patch.dict(OPTIONAL_FLOW_HASHES, {'ours_sintel.pth': hashlib.sha256(b'different checkpoint').hexdigest()}), \
                self.assertRaisesRegex(ValueError, 'already installed'):
            install_optional_flow_files('EF_RAFT', [replacement], self.root)
        self.assertEqual(copied[0].read_bytes(), b'checkpoint')
        invalid = source / 'unknown.pth'
        invalid.write_bytes(b'checkpoint')
        with self.assertRaisesRegex(ValueError, 'recognized'):
            install_optional_flow_files('FLOW_DIFF', [invalid], self.root)

    def test_shared_worker_diagnostic_requires_completion_event_and_normal_exit(self):
        job = self.root / 'job.json'
        second = self.root / 'second.json'
        job.write_text('{}', encoding='utf-8')
        second.write_text('{}', encoding='utf-8')
        event = ''.join('@@REEZSYNTH_SESSION@@' + json.dumps(
            {'event': 'job_done', 'job': str(path.resolve())}, ensure_ascii=True)
            for path in (job, second))
        with patch('diagnose_reezsynth_adapter.subprocess.run',
                   return_value=SimpleNamespace(returncode=0, stdout=event, stderr='')) as run, \
             patch('sys.stdout', new_callable=io.StringIO):
            run_adapter_diagnostic([job, second], self.root, shared_worker=True)
        self.assertEqual(run.call_args.kwargs['cwd'], self.root)
        commands = [json.loads(line) for line in run.call_args.kwargs['input'].splitlines()]
        self.assertEqual(commands, [
            {'action': 'run', 'job': str(job.resolve())},
            {'action': 'run', 'job': str(second.resolve())},
            {'action': 'quit'},
        ])
        with patch('diagnose_reezsynth_adapter.subprocess.run',
                   return_value=SimpleNamespace(returncode=0, stdout='', stderr='')), \
             patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaisesRegex(RuntimeError, 'did not report'):
                run_adapter_diagnostic(job, self.root, shared_worker=True)

    def test_cancellation_diagnostic_kills_only_after_synthesis_begins(self):
        job = self.root / 'job.json'
        job.write_text('{}', encoding='utf-8')
        class Process:
            def __init__(self):
                self.stdin = io.StringIO()
                self.stdout = io.StringIO('@@REEZSYNTH_PROGRESS@@{"stage": "Synthesis 0/23"}\n')
                self.returncode = None
                self.killed = False
            def poll(self):
                return self.returncode
            def wait(self, timeout):
                return self.returncode
            def kill(self):
                self.killed = True
                self.returncode = -9
        process = Process()
        with patch('diagnose_reezsynth_adapter.subprocess.Popen', return_value=process), \
             patch('sys.stdout', new_callable=io.StringIO):
            cancel_worker(job, self.root)
        self.assertTrue(process.killed)

    def test_parallel_diagnostic_starts_one_isolated_process_per_job(self):
        jobs = [self.root / 'one.json', self.root / 'two.json']
        for job in jobs:
            job.write_text('{}', encoding='utf-8')
        completed = SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch('diagnose_reezsynth_adapter.subprocess.run', return_value=completed) as run, \
             patch('sys.stdout', new_callable=io.StringIO):
            render_parallel(jobs, self.root)
        self.assertEqual(run.call_count, 2)
        self.assertEqual({Path(call.args[0][-1]) for call in run.call_args_list}, {job.resolve() for job in jobs})

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
        self.assertIn('setup_fuoum.py', result.stdout)
        self.assertIn('--preflight', result.stdout)
        self.assertIn('--neuflow', result.stdout)
        self.assertEqual(list(self.root.iterdir()), [self.root / 'setup_reezsynth.ps1'])


@unittest.skipUnless(sys.platform == 'win32', 'Windows setup orchestration')
class DualEngineSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='reezsynth dual setup ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copy2(ROOT / 'setup_reezsynth.ps1', self.root)

    def run_setup(self, *, check=False, fail_flag=''):
        # Replace Conda at its process boundary; no actual environment/package install.
        conda = self.root / 'fake conda.ps1'
        conda.write_text('''$arguments = @($args | ForEach-Object { [string]$_ })
$record = ConvertTo-Json -InputObject $arguments -Compress
[IO.File]::AppendAllText((Join-Path $PSScriptRoot 'calls.jsonl'), $record + [Environment]::NewLine)
$global:LASTEXITCODE = 0
if ($arguments[0] -eq 'env') { Write-Output '{"envs":[]}' }
if ('__FAIL_FLAG__' -and $arguments -contains '__FAIL_FLAG__') { $global:LASTEXITCODE = 9 }
'''.replace('__FAIL_FLAG__', fail_flag), encoding='utf-8')
        args = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                str(self.root / 'setup_reezsynth.ps1'), '-CondaExe', str(conda)]
        if check:
            args.append('-CheckOnly')
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        calls = [json.loads(line) for line in (self.root / 'calls.jsonl').read_text().splitlines()]
        return result, calls

    def test_default_installs_both_and_only_then_writes_launcher_configuration(self):
        result, calls = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        preflight = next(i for i, call in enumerate(calls) if '--preflight' in call)
        packages = next(i for i, call in enumerate(calls) if 'pip' in call and 'install' in call)
        fuoum = next(i for i, call in enumerate(calls) if '--neuflow' in call)
        base_check = next(i for i, call in enumerate(calls) if '--gui-smoke' in call)
        self.assertLess(preflight, packages)
        self.assertLess(base_check, fuoum)
        self.assertEqual(fuoum, len(calls) - 1)
        self.assertIn('Both synthesis engines are installed and checked', result.stdout)
        self.assertTrue((self.root / '.reezsynth-conda-path.txt').is_file())
        self.assertTrue((self.root / '.reezsynth-env-name.txt').is_file())

    def test_fuoum_failure_does_not_report_success_or_write_launcher_configuration(self):
        result, calls = self.run_setup(fail_flag='--neuflow')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--neuflow', calls[-1])
        self.assertNotIn('Both synthesis engines are installed and checked', result.stdout)
        self.assertFalse(list(self.root.glob('.reezsynth-*.txt')))

    def test_missing_prerequisites_stop_before_package_downloads(self):
        result, calls = self.run_setup(fail_flag='--preflight')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--preflight', calls[-1])
        self.assertFalse(any('pip' in call and 'install' in call for call in calls))
        self.assertFalse(list(self.root.glob('.reezsynth-*.txt')))

    def test_check_only_verifies_both_engines_without_installing(self):
        result, calls = self.run_setup(check=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertIn('--gui-smoke', calls[0])
        self.assertIn('--check-only', calls[1])
        self.assertIn('--neuflow', calls[1])
        self.assertTrue(Path(calls[1][-3]).is_absolute())
        self.assertFalse(list(self.root.glob('.reezsynth-*.txt')))

    def test_check_only_rejects_an_incomplete_fuoum_installation(self):
        result, calls = self.run_setup(check=True, fail_flag='--neuflow')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('Both synthesis engines passed', result.stdout)

    def test_existing_fuoum_environment_stops_before_creating_a_conda_environment(self):
        existing = self.root / '.engine_envs/fuoum'
        existing.mkdir(parents=True)
        marker = existing / 'keep.txt'
        marker.write_text('existing installation')
        result, calls = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [['env', 'list', '--json']])
        self.assertEqual(marker.read_text(), 'existing installation')


if __name__ == '__main__':
    unittest.main()
