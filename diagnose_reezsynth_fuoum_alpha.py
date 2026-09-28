"""Opt-in four-channel synthesis probe; does not enable transparent job routing."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np

from reezsynth_config import atomic_json, validate_render
from reezsynth_engines import FUOUM, prepare_runtime, activate_fuoum
from reezsynth_fuoum_alpha import associated_style, straight_output
from reezsynth_synthetic_inputs import frame, write


def worker(path):
    job = json.loads(Path(path).read_text(encoding='utf-8'))
    activate_fuoum(job['runtime'])
    from reezsynth_fuoum import synthesize_image
    source = frame((128, 128), 0, 3)
    drawing = np.zeros((128, 128, 4), np.uint8)
    cv2.circle(drawing, (64, 64), 35, (0, 0, 0, 255), 2, cv2.LINE_AA)
    cv2.circle(drawing, (54, 56), 5, (255, 255, 255, 255), -1, cv2.LINE_AA)
    cv2.ellipse(drawing, (65, 78), (12, 5), 0, 0, 180, (0, 0, 90, 255), -1, cv2.LINE_AA)
    half = np.full((128, 128, 4), [255, 255, 255, 128], np.uint8)
    results = []
    for name, raw in [('lineart', drawing), ('half', half)]:
        for vote in ('weighted', 'plain'):
            for cost in ('ssd', 'ncc'):
                options = validate_render(dict(engine=FUOUM, fuoum_backend=job['backend'],
                    fuoum_vote_mode=vote, fuoum_cost_function=cost, patchsize=3,
                    pyramidlevels=1, searchvoteiters=1, patchmatchiters=1,
                    extrapass3x3=True, uniformity=0))
                image, error = synthesize_image(associated_style(raw), [(source, source, 6)], options)
                if image.shape != raw.shape or image.dtype != np.uint8 or not np.isfinite(error).all():
                    raise RuntimeError('Invalid native RGBA synthesis result.')
                if name == 'half' and np.abs(image[..., 3].astype(np.int16) - 128).max() > 1:
                    raise RuntimeError('Constant opacity was not carried by native synthesis.')
                label = f'{name}_{vote}_{cost}'
                write(Path(job['output']) / (label + '.png'), straight_output(image))
                results.append(dict(case=label, channels=4, alpha_min=int(image[..., 3].min()),
                    alpha_max=int(image[..., 3].max()), finite_errors=True))
                print(f'{job["backend"]}: {label} passed', flush=True)
    atomic_json(Path(job['output']) / 'results.json', dict(passed=True, backend=job['backend'], cases=results))


def main():
    root = Path(__file__).resolve().parent
    report = root / 'diagnostic_outputs' / ('fuoum_alpha_probe_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    report.mkdir(parents=True)
    runtime = prepare_runtime({'engine': FUOUM}, {})
    for backend in ('cuda', 'torch'):
        output = report / backend; output.mkdir()
        path = output / 'probe.json'
        atomic_json(path, dict(runtime=runtime, backend=backend, output=str(output)))
        result = subprocess.run([runtime['python'], '-B', str(Path(__file__).resolve()), '--worker', str(path)],
            cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (output / 'probe.log').write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError(f'RGBA backend probe failed; inspect {output / "probe.log"}')
        print(result.stdout, end='', flush=True)
    print(f'Retained backend probe: {report}', flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        worker(sys.argv[2])
    else:
        main()
