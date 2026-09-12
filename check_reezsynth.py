"""Local installation checks; no installs, downloads, model loading or rendering."""
import argparse
import ctypes
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
PACKAGES = {'PySide6': 'PySide6.QtWidgets', 'numpy': 'numpy', 'opencv-python': 'cv2',
            'torch': 'torch', 'torchvision': 'torchvision', 'phycv': 'phycv',
            'scipy': 'scipy', 'Pillow': 'PIL.Image', 'tqdm': 'tqdm'}
EF_RAFT_MODELS = ('25000_ours-sintel', 'ours_sintel', 'ours-things')
FLOW_DIFFUSION_MODEL = 'FlowDiffuser-things.pth'


def verify_assets(root=ROOT):
    manifest = json.loads((root / 'runtime-assets.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 1:
        raise ValueError('Unsupported runtime asset manifest.')
    for relative, expected in manifest['files'].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('Runtime manifest path escapes the project.')
        if not path.is_file():
            raise ValueError(f'Missing {relative}. See INSTALL_WINDOWS.md; do not download replacement DLLs from unrelated sites.')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != expected:
            raise ValueError(f'Runtime asset differs from the working checkout: {relative}. Verify its source before rendering.')
    return len(manifest['files'])


def flow_extra_readiness(root=ROOT, find_spec=importlib.util.find_spec):
    """Report optional flow architecture requirements without importing a model."""
    root = Path(root)
    flow_root = root / 'ezsynth' / 'utils' / 'flow_utils'
    ef_dir = flow_root / 'ef_raft_models'
    flow_diff_dir = flow_root / 'flow_diffusion_models'
    ef_missing = [model for model in EF_RAFT_MODELS if not (ef_dir / f'{model}.pth').is_file()]
    return {
        'EF-RAFT': [] if not ef_missing else [
            'missing weights: ' + ', '.join(f'{model}.pth' for model in ef_missing),
        ],
        'FlowDiffuser': (
            ([] if find_spec('timm') is not None else ['missing Python package: timm'])
            + ([] if (flow_diff_dir / FLOW_DIFFUSION_MODEL).is_file()
               else [f'missing weights: {FLOW_DIFFUSION_MODEL}'])
        ),
    }


def gui_smoke():
    # This child process owns temporary settings and directories, never the user's.
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from unittest.mock import patch
    from PySide6.QtCore import QSettings, QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    import reezsynth_gui as gui
    app = QApplication.instance() or QApplication([])
    app.setStyle(gui.QueueStyle('Fusion'))
    app.setStyleSheet(gui.THEME)
    errors = []
    with tempfile.TemporaryDirectory(prefix='reezsynth_setup_smoke_') as directory:
        def settings(*args):
            result = QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat)
            result.setFallbacksEnabled(False)
            return result
        with patch.object(gui, 'QSettings', settings), patch.object(gui, 'ROOT', Path(directory)), \
             patch.object(gui.Options, 'notify'), patch.object(sys, 'excepthook', lambda *error: errors.append(error)):
            window = gui.MainWindow()
            try:
                window.show()
                for index in range(window.tabs.count()):
                    window.tabs.setCurrentIndex(index)
                    app.processEvents()
                if errors:
                    raise RuntimeError(f'GUI callback error: {errors[0][1]}')
                assert window.process is None and not window.busy
            finally:
                window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    print('GUI construction and tab display passed using temporary settings.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui-smoke', action='store_true', help='Construct all tabs with isolated settings in a child process.')
    parser.add_argument('--cuda', action='store_true', help='Query CUDA availability; no models or rendering.')
    parser.add_argument('--native', action='store_true', help='Load the EbSynth DLL and check its entry point; no synthesis.')
    parser.add_argument('--raft-extension', action='store_true', help='Load the bundled memory-efficient RAFT extension; no model or synthesis.')
    parser.add_argument('--flow-extras', action='store_true', help='Check EF-RAFT and FlowDiffuser files/dependencies without loading models.')
    parser.add_argument('--_gui-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._gui_child:
        gui_smoke()
        return 0
    failures = []
    def check(label, action):
        try:
            detail = action()
            print(f'[OK] {label}' + (f': {detail}' if detail is not None else ''))
        except Exception as exc:
            failures.append(label)
            print(f'[FAIL] {label}: {exc}')
    print(f'Python: {sys.executable}\nVersion: {platform.python_version()}\nPlatform: {platform.platform()}')
    def interpreter():
        if sys.platform != 'win32' or sys.maxsize <= 2**32 or sys.version_info[:2] != (3, 11):
            raise RuntimeError('The supported setup uses 64-bit Windows and Python 3.11.')
    check('Interpreter', interpreter)
    expected = {}
    for line in (ROOT / 'requirements.txt').read_text().splitlines():
        if '==' in line and not line.startswith('#'):
            name, version = line.strip().split('==', 1)
            expected[name] = version
    for name, module in PACKAGES.items():
        def package(name=name, module=module):
            installed = importlib.metadata.version(name)
            importlib.import_module(module)
            if name in expected and installed != expected[name]:
                print(f'[NOTE] {name}: installed {installed}; tested pin is {expected[name]}.')
            return installed
        check(name, package)
    def pip_check():
        result = subprocess.run([sys.executable, '-m', 'pip', 'check'], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError((result.stdout + result.stderr).strip())
        return result.stdout.strip()
    check('Dependency consistency', pip_check)
    check('Runtime assets', lambda: f'{verify_assets()} hashes verified')
    if args.cuda:
        def cuda():
            import torch
            if torch.version.cuda is None or not torch.cuda.is_available():
                raise RuntimeError('CUDA is unavailable. Check NVIDIA driver/GPU support and the CUDA PyTorch wheel. GUI startup alone does not require a GPU.')
            return f'{torch.cuda.get_device_name(0)}; PyTorch CUDA {torch.version.cuda}'
        check('CUDA', cuda)
    if args.native:
        def native():
            import torch  # Load the environment's native runtime dependencies first.
            library = ctypes.CDLL(str(ROOT / 'ezsynth/utils/ebsynth.dll'))
            getattr(library, 'ebsynthRun')
            return 'ebsynthRun found (not called)'
        check('EbSynth native library', native)
    if args.raft_extension:
        def raft_extension():
            from reezsynth_raft import require_alt_cuda_corr
            extension = require_alt_cuda_corr()
            return f'{extension.__file__}; build {extension.reezsynth_build}'
        check('Memory-efficient RAFT extension', raft_extension)
    if args.flow_extras:
        for name, missing in flow_extra_readiness().items():
            check(name, lambda name=name, missing=missing: (
                f'{name} files and dependencies are present' if not missing
                else (_ for _ in ()).throw(RuntimeError('; '.join(missing)))
            ))
    if args.gui_smoke:
        def smoke():
            result = subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--_gui-child'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=60)
            if result.returncode:
                raise RuntimeError((result.stdout + result.stderr).strip())
            if result.stderr:
                print(result.stderr.strip())
            return result.stdout.strip()
        check('GUI smoke', smoke)
    print('No models loaded and no GPU synthesis performed.')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
