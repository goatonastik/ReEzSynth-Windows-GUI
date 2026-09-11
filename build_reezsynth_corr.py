"""Build the optional RAFT CUDA extension using the current Python environment."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='Install the built wheel into this Python environment (no dependencies).')
    parser.add_argument('--arch', help='CUDA architecture list, e.g. 7.5;8.6;8.9;12.0. Defaults to the current GPU.')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise RuntimeError('This build helper supports Windows only.')
    if (Path(sys.prefix) / 'Scripts/conda.exe').exists():
        raise RuntimeError('Activate the ReEzSynth environment; do not build/install into base Conda.')
    import torch
    from torch.utils.cpp_extension import CUDA_HOME
    if not CUDA_HOME or not (Path(CUDA_HOME) / 'bin/nvcc.exe').is_file():
        raise RuntimeError('Install a CUDA toolkit matching PyTorch and set CUDA_HOME. See INSTALL_WINDOWS.md.')
    nvcc = subprocess.check_output([str(Path(CUDA_HOME) / 'bin/nvcc.exe'), '--version'], text=True)
    version = re.search(r'release (\d+\.\d+)', nvcc)
    if not version or version[1] != torch.version.cuda:
        raise RuntimeError(f'CUDA toolkit must match PyTorch CUDA {torch.version.cuda}.')
    arch = args.arch or '.'.join(map(str, torch.cuda.get_device_capability()))
    if not re.fullmatch(r'\d+\.\d+(?:\+PTX)?(?:;\d+\.\d+(?:\+PTX)?)*', arch):
        raise ValueError('Specify CUDA architectures separated by semicolons, e.g. 7.5;8.6;8.9;12.0.')
    vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    installations = json.loads(subprocess.check_output([
        str(vswhere), '-products', '*', '-version', '[17.0,18.0)', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-format', 'json'], text=True, encoding='utf-8'))
    if not installations:
        raise RuntimeError('Visual Studio 2022 C++ build tools are required for CUDA 12.8.')
    vcvars = Path(installations[0]['installationPath']) / 'VC/Auxiliary/Build/vcvars64.bat'
    # Fixed command structure; the path comes from the Visual Studio installation registry.
    result = subprocess.run(f'cmd.exe /d /s /c ""{vcvars}" >nul && set"',
                            capture_output=True, text=True, check=True)
    env = os.environ.copy()
    for line in result.stdout.splitlines():
        name, separator, value = line.partition('=')
        if separator and name:
            env[name] = value
    env.update(DISTUTILS_USE_SDK='1', TORCH_CUDA_ARCH_LIST=arch, CUDA_HOME=CUDA_HOME)
    print(f'Building for {sys.executable}; PyTorch {torch.__version__}; CUDA architecture {arch}', flush=True)
    source = ROOT / 'third_party/raft_alt_cuda_corr'
    subprocess.run([sys.executable, 'setup.py', 'build_ext', '--force', 'bdist_wheel'], cwd=source, env=env, check=True)
    wheels = list((source / 'dist').glob('reezsynth_alt_cuda_corr-*.whl'))
    wheel = max(wheels, key=lambda path: path.stat().st_mtime)
    print(f'Built: {wheel}', flush=True)
    if args.install:
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--force-reinstall', str(wheel)], check=True)
        subprocess.run([sys.executable, '-c', 'import torch,alt_cuda_corr; print(alt_cuda_corr.__file__)'], check=True)


if __name__ == '__main__':
    main()
