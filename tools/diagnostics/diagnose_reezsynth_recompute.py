"""Opt-in small real FuouM warm/reuse/forced-cache diagnostic on synthetic inputs."""

# Support direct execution from any working directory.
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datetime import datetime
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np

from reezsynth_config import quality_profile, validate_render
from reezsynth_engines import FUOUM, file_sha256, prepare_runtime
from reezsynth_synthetic_inputs import frame, style, write


def main():
    root = Path(__file__).resolve().parents[2]
    report = root / 'diagnostic_outputs' / ('recompute_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    report.mkdir(parents=True)
    inputs = report / 'inputs'
    inputs.mkdir()
    frames = []
    for index in range(2):
        path = inputs / f'frame{index:03d}.png'
        write(path, frame((128, 128), index, 3))
        frames.append([index, str(path)])
    drawing = inputs / 'style000.png'
    write(drawing, style(frame((128, 128), 0, 3)))
    options = validate_render(dict(quality_profile('Preview'), engine=FUOUM, fuoum_bidirectional_flow=True))
    runtime = prepare_runtime(options, {})
    cache = report / 'cache'
    def snapshot():
        return {path.relative_to(cache).as_posix(): file_sha256(path)
                for path in cache.rglob('*') if path.is_file()}
    preserved = None
    for label, forced in (('warm', False), ('reuse', False), ('forced', True)):
        output = report / label
        output.mkdir()
        selected = dict(options, fuoum_force_recompute_flow=forced, fuoum_force_recompute_edge=forced)
        job = dict(key=0, style=str(drawing), frames=frames, padding=3, quality='Preview',
                   max_width=0, output=str(output), render_options=selected, engine_runtime=runtime,
                   precompute_cache=str(cache))
        path = report / f'{label}.json'
        path.write_text(json.dumps(job), encoding='utf-8')
        result = subprocess.run([runtime['python'], '-B', str(root / 'reezsynth_jobs.py'), str(path)],
            cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        log = result.stdout + '\n' + result.stderr
        (report / f'{label}.log').write_text(log, encoding='utf-8')
        if result.returncode or not (output / 'COMPLETE.txt').is_file():
            raise RuntimeError(f'{label} failed; inspect {report / (label + ".log")}')
        images = list(output.glob('*.png'))
        assert len(images) == 2, images
        for image in images:
            decoded = cv2.imdecode(np.frombuffer(image.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            assert decoded is not None and decoded.shape == (128, 128, 3)
        if label == 'warm':
            preserved = snapshot()
            assert len([name for name in preserved if name.endswith('flow.npy')]) == 2
            assert len([name for name in preserved if name.endswith('edge.npy')]) == 2
        else:
            assert snapshot() == preserved, 'Shared cache files changed.'
        if label == 'reuse':
            assert 'Reused 2 validated optical-flow pair(s)' in log
            assert 'Reused 2 validated edge maps' in log
        elif forced:
            assert 'Optical flow: forced recomputation' in log
            assert 'Automatic edges: forced recomputation' in log
            assert 'Reused ' not in log
            manifest = json.loads((output / 'engine_manifest.json').read_text())
            settings = manifest['effective_settings']['render_options']
            assert settings['fuoum_force_recompute_flow'] and settings['fuoum_force_recompute_edge']
        print(f'{label}: passed (128x128, two frames, both flow directions).', flush=True)
    (report / 'summary.json').write_text(json.dumps(dict(passed=True, size=[128, 128], frames=2,
        bidirectional=True, shared_cache_unchanged=True, cache_sha256=preserved), indent=2), encoding='utf-8')
    print(f'Retained diagnostic: {report}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
