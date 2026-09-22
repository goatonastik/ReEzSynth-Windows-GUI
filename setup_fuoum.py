"""FuouM component installer for the standard Windows setup; also supports maintenance checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

from reezsynth_engines import ROOT, FUOUM, FUOUM_REVISION, default_runtime, prepare_runtime, source_revision

NEUFLOW_REVISION = '204b5e3744461d90303b9ff82caa7a1bb56a2ca2'
NEUFLOW_HASHES = {
    'sintel': '9bc12c9ef8298e3cca08a33a04bf99b63dc989e16808daca0c10ac5be4291eb1',
    'mixed': '76152c8068f247a7d073aa13e61da8cb4c3c6a798076d4dc8e20f7995fcc019f',
    'things': '733d13b1b2202adefcc99bd1f0fceb89fc90da5479f9826fa3f17ff42c4bdbe0',
}


def check_build_prerequisites(source):
    """Check source/build prerequisites using only the standard library, without writes."""
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 11) or sys.maxsize < 2**32:
        raise RuntimeError('Use Python 3.11 on 64-bit Windows for the FuouM installation.')
    git = shutil.which('git')
    if not git:
        raise RuntimeError('Git is required to install and verify FuouM. Install Git for Windows and reopen your terminal.')
    source = Path(source).resolve()
    if source.exists():
        if source_revision(source) != FUOUM_REVISION:
            raise RuntimeError('Existing FuouM source is not the supported revision; it was not changed.')
        if list(source.glob('ebsynth_torch*.pyd')):
            return dict(git=git, native_build_required=False)
    cuda = os.environ.get('CUDA_HOME') or os.environ.get('CUDA_PATH')
    nvcc = str(Path(cuda) / 'bin/nvcc.exe') if cuda else shutil.which('nvcc')
    if not nvcc or not Path(nvcc).is_file():
        raise RuntimeError('Both engines are included in setup. Building FuouM requires the CUDA 12.8 toolkit. '
                           'Install it and set CUDA_HOME to its installation folder. See INSTALL_WINDOWS.md.')
    flags = dict(text=True, encoding='utf-8', errors='replace', timeout=30,
                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    version = subprocess.check_output([str(nvcc), '--version'], **flags)
    if not re.search(r'release 12\.8(?:\D|$)', version):
        raise RuntimeError('The standard installation requires the CUDA 12.8 toolkit to match its pinned PyTorch. '
                           'Set CUDA_HOME to that toolkit before retrying.')
    vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    if not vswhere.is_file():
        raise RuntimeError('Building FuouM requires Visual Studio 2022 C++ build tools and the Windows SDK. '
                           'See INSTALL_WINDOWS.md.')
    installations = json.loads(subprocess.check_output([
        str(vswhere), '-products', '*', '-version', '[17.0,18.0)', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-format', 'json'], **flags))
    if not installations or not (Path(installations[0]['installationPath']) / 'VC/Auxiliary/Build/vcvars64.bat').is_file():
        raise RuntimeError('Visual Studio 2022 C++ x64 build tools were not found. Install the C++ workload and Windows SDK.')
    return dict(git=git, native_build_required=True, cuda_compiler=str(nvcc),
                visual_studio=installations[0]['installationPath'])


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ensure_asset(destination, expected, *, local=None, url=None, check=False):
    destination = Path(destination)
    if destination.exists():
        if sha256(destination) != expected:
            raise RuntimeError(f'Existing file has an unexpected hash; it was not replaced: {destination}')
        return
    if check:
        raise RuntimeError(f'Missing checkpoint: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.part', delete=False) as stream:
        temporary = Path(stream.name)
    try:
        if local is not None:
            shutil.copyfile(local, temporary)
        else:
            parsed_url = urllib.parse.urlsplit(url)
            if parsed_url.scheme.lower() != 'https' or not parsed_url.netloc:
                raise RuntimeError(f'Refusing non-HTTPS checkpoint URL: {url!r}')
            # The scheme and host were validated directly above.
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as stream:  # nosec B310
                shutil.copyfileobj(response, stream)
        if sha256(temporary) != expected:
            raise RuntimeError(f'Checkpoint checksum mismatch: {destination.name}')
        # Windows rename refuses to overwrite a destination created concurrently.
        temporary.rename(destination)
    finally:
        temporary.unlink(missing_ok=True)


def command(args, **kwargs):
    print(subprocess.list2cmdline([str(a) for a in args]), flush=True)
    with subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **kwargs) as process:
        for line in process.stdout:
            print(line, end='', flush=True)
        if process.wait():
            raise subprocess.CalledProcessError(process.returncode, args)


def install(source, environment, *, plan=False, check=False, neuflow=False):
    source, environment = Path(source).resolve(), Path(environment).resolve()
    python = environment / 'Scripts/python.exe'
    if plan:
        print(json.dumps(dict(source=str(source), revision=FUOUM_REVISION,
            environment=str(environment), parent_python=sys.executable, inherit_parent_packages=True,
            steps=['Check Windows/Python/Git/CUDA/build tools', 'Clone pinned sparse source if absent',
                   'Create a NEW worker venv', 'Install requirements-fuoum.txt only there',
                   'Verify/copy local RAFT weights', 'Build native CUDA extension', 'Check imports and pip'],
            neuflow_downloads=[f'neuflow_{n}.pth' for n in NEUFLOW_HASHES] if neuflow else [],
            no_changes=True), indent=2))
        return
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 11) or sys.maxsize < 2**32:
        raise RuntimeError('Run with the working GUI Python 3.11 environment on 64-bit Windows.')
    if not check and environment.exists():
        raise RuntimeError(f'Environment already exists; use --check-only or choose a NEW --venv: {environment}')
    if not check:
        check_build_prerequisites(source)
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError('The parent GUI Python must have working CUDA PyTorch first.')
        # Verify local prerequisites before creating anything or downloading source.
        manifest = json.loads((ROOT / 'runtime-assets.json').read_text())['files']
        for model in ('sintel', 'kitti'):
            relative = f'ezsynth/utils/flow_utils/models/raft-{model}.pth'
            if not (ROOT / relative).is_file() or sha256(ROOT / relative) != manifest[relative]:
                raise RuntimeError(f'Missing or changed parent RAFT checkpoint: {relative}')
        if not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            command(['git', 'clone', '--filter=blob:none', '--sparse', 'https://github.com/FuouM/ReEzSynth.git', source])
            command(['git', '-C', source, 'sparse-checkout', 'set', 'ezsynth', 'ebsynth_extension', 'models'])
            command(['git', '-C', source, 'checkout', '--detach', FUOUM_REVISION])
        if source_revision(source) != FUOUM_REVISION:
            raise RuntimeError('Existing source is not the supported revision; it was not changed.')
        command([sys.executable, '-m', 'venv', '--system-site-packages', environment])
        command([python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', ROOT / 'requirements-fuoum.txt'])
    manifest = json.loads((ROOT / 'runtime-assets.json').read_text())['files']
    for model in ('sintel', 'kitti'):
        relative = f'ezsynth/utils/flow_utils/models/raft-{model}.pth'
        ensure_asset(source / f'models/raft/raft-{model}.pth', manifest[relative], local=ROOT / relative, check=check)
    if neuflow:
        for model, expected in NEUFLOW_HASHES.items():
            name = f'neuflow_{model}.pth'
            ensure_asset(source / 'models/neuflow' / name, expected, check=check,
                url=f'https://raw.githubusercontent.com/neufieldrobotics/NeuFlow_v2/{NEUFLOW_REVISION}/{name}')
    if not check and not list(source.glob('ebsynth_torch*.pyd')):
        command([python, '-B', ROOT / 'build_fuoum_engine.py', '--source', source])
    runtime = prepare_runtime({'engine': FUOUM}, {'fuoum_source': str(source), 'fuoum_python': str(python)})
    command([python, '-m', 'pip', 'check'])
    command([python, '-B', '-c', 'import torch, ebsynth_torch, cv2, pydantic, einops, pyamg; '
             'assert torch.cuda.is_available(); print(ebsynth_torch.__file__)'], cwd=source)
    print(json.dumps(dict(passed=True, runtime=runtime, render_test_performed=False), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=default_runtime()['fuoum_source'])
    parser.add_argument('--venv', default=str(ROOT / '.engine_envs/fuoum'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true', help='Print proposed work without changes or downloads.')
    mode.add_argument('--check-only', action='store_true', help='Validate an existing install without repairs.')
    mode.add_argument('--preflight', action='store_true', help='Check source/build prerequisites without changes, downloads or PyTorch imports.')
    parser.add_argument('--neuflow', action='store_true', help='Download/check all three official pinned NeuFlow checkpoints.')
    args = parser.parse_args()
    if args.preflight:
        print(json.dumps(dict(passed=True, **check_build_prerequisites(args.source)), indent=2))
    else:
        install(args.source, args.venv, plan=args.plan, check=args.check_only, neuflow=args.neuflow)
