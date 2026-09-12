"""Build the pinned FuouM CUDA extension in its dedicated Python runtime."""
import json
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

from reezsynth_engines import FUOUM, ROOT, prepare_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='', help='Optional pinned FuouM checkout.')
    parser.add_argument('--force', action='store_true', help='Force recompilation for maintenance.')
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.prefix == sys.base_prefix:
        raise RuntimeError('Run this helper with the separate FuouM virtual environment on Windows.')
    runtime = prepare_runtime({'engine': FUOUM}, {'fuoum_python': sys.executable, 'fuoum_source': args.source}, require_native=False)
    compatibility = ROOT / 'patches' / 'fuoum-windows-torch-types.patch'
    applied = subprocess.run(['git', 'apply', '--unidiff-zero', '--reverse', '--check', str(compatibility)],
                             cwd=runtime['source'], capture_output=True)
    if applied.returncode:
        subprocess.run(['git', 'apply', '--unidiff-zero', '--check', str(compatibility)], cwd=runtime['source'], check=True)
        subprocess.run(['git', 'apply', '--unidiff-zero', str(compatibility)], cwd=runtime['source'], check=True)
    import torch
    from torch.utils.cpp_extension import CUDA_HOME
    if not CUDA_HOME:
        raise RuntimeError('A CUDA toolkit matching PyTorch is required to build the FuouM extension.')
    nvcc = subprocess.check_output([str(Path(CUDA_HOME) / 'bin/nvcc.exe'), '--version'], text=True)
    version = re.search(r'release (\d+\.\d+)', nvcc)
    if not version or version[1] != torch.version.cuda:
        raise RuntimeError(f'CUDA toolkit must match PyTorch CUDA {torch.version.cuda}.')
    vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    installations = json.loads(subprocess.check_output([
        str(vswhere), '-products', '*', '-version', '[17.0,18.0)', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-format', 'json'], text=True, encoding='utf-8'))
    if not installations:
        raise RuntimeError('Visual Studio 2022 C++ tools are required.')
    vcvars = Path(installations[0]['installationPath']) / 'VC/Auxiliary/Build/vcvars64.bat'
    command = 'cmd.exe /d /s /c ""' + str(vcvars) + '" >nul && set"'
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    # Windows names are case-insensitive; avoid duplicate Path/PATH entries.
    environment = {name.upper(): value for name, value in os.environ.items()}
    for line in result.stdout.splitlines():
        name, separator, value = line.partition('=')
        if separator and name:
            environment[name.upper()] = value
    architecture = '.'.join(map(str, torch.cuda.get_device_capability()))
    environment.update(DISTUTILS_USE_SDK='1', TORCH_CUDA_ARCH_LIST=architecture, CUDA_HOME=CUDA_HOME,
                       MAX_JOBS='2')
    # BuildExtension discovers ninja through PATH, even when Python is invoked by full path.
    environment['PATH'] = str(Path(sys.executable).parent) + os.pathsep + environment.get('PATH', '')
    print(f'Building FuouM {runtime["revision"]} for CUDA architecture {architecture}', flush=True)
    build = [sys.executable, 'setup.py', 'build_ext']
    if args.force:
        build.append('--force')
    build.append('--inplace')
    subprocess.run(build, cwd=runtime['source'],
                   env=environment, check=True)
    subprocess.run([sys.executable, '-c', 'import torch, ebsynth_torch; print(ebsynth_torch.__file__)'],
                   cwd=runtime['source'], env=environment, check=True)


if __name__ == '__main__':
    main()
