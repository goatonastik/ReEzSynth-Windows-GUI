"""Install/check pinned FlowDiffuser dependencies and offline Twin-SVT weights."""
import argparse
import hashlib
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
PACKAGES = {'timm': '1.0.29', 'huggingface_hub': '1.31.0', 'safetensors': '0.8.0'}
BACKBONES = {
    'twins_svt_large': ('timm/twins_svt_large.in1k', '9985cdd56ac6164db09e464008c512fb7b75228a',
                        'a8d1d667816af8b2ebe28ad4b16f2884d3e43f8aa9713facfb0272df3e0c8a8c'),
    'twins_svt_small': ('timm/twins_svt_small.in1k', '42c9bf4b9fdc569b3d75adad47bfcf4d2fb580aa',
                        '719c6faf2eda26c7ac4ff09b111ca5046d9d93591b647346229c17648e0f25ab'),
}
MODEL_DIR = ROOT / 'ezsynth/utils/flow_utils/flow_diffusion_models'


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check():
    for name, expected in PACKAGES.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(f'FlowDiffuser dependency is missing: {name} {expected}') from exc
        if actual != expected:
            raise RuntimeError(f'FlowDiffuser requires {name} {expected}; found {actual}.')
    for name, (_, _, expected) in BACKBONES.items():
        path = MODEL_DIR / f'{name}.pth'
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f'Pinned FlowDiffuser backbone is missing or changed: {path}')
    import timm
    import torch
    for name in BACKBONES:
        model = timm.create_model(name, pretrained=False)
        state = torch.load(MODEL_DIR / f'{name}.pth', map_location='cpu', weights_only=True)
        model.load_state_dict(state, strict=True)
        del model, state
    print('FlowDiffuser dependencies and offline Twin-SVT weights passed checks.')


def install():
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
                    '-r', str(ROOT / 'requirements-flowdiffuser.txt'),
                    '-c', str(ROOT / 'reezsynth-working-requirements.txt')], check=True)
    from huggingface_hub import hf_hub_download
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, (repository, revision, expected) in BACKBONES.items():
        target = MODEL_DIR / f'{name}.pth'
        if target.exists():
            if sha256(target) != expected:
                raise RuntimeError(f'Existing backbone differs and was not replaced: {target}')
            continue
        source = hf_hub_download(repository, 'pytorch_model.bin', revision=revision)
        if sha256(source) != expected:
            raise RuntimeError(f'Downloaded {name} backbone failed its checksum.')
        temporary = target.with_suffix('.pth.part')
        shutil.copyfile(source, temporary)
        temporary.replace(target)
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
    check()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    arguments = parser.parse_args()
    check() if arguments.check_only else install()
