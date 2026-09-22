"""Opt-in real Legacy CPU/Auto frontend checks with CUDA hidden from each worker."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import cv2
import numpy as np

from reezsynth_config import PREVIEW, atomic_json, validate_render
from reezsynth_engines import LEGACY, LEGACY_REVISION, ROOT
from reezsynth_synthetic_inputs import frame, image_case, style, write


def make_jobs(base, backend):
    options = validate_render(dict(PREVIEW, engine=LEGACY, ebsynth_backend=backend,
                                   edge_method='Classic', memory_efficient_raft=False))
    runtime = dict(engine=LEGACY, revision=LEGACY_REVISION,
                   source=str(ROOT), python=sys.executable)
    jobs = []
    inputs = base / backend / 'inputs'
    for kind in ('image', 'video'):
        output = base / backend / kind
        output.mkdir(parents=True)
        job = dict(output=str(output), quality='Preview', processing_size=[256, 144],
                   render_options=options, engine_runtime=runtime)
        if kind == 'image':
            job.update(type='image_synthesis', image_synthesis=image_case(
                inputs, 'image', source_size=(256, 144), target_size=(256, 144)))
        else:
            images = [frame((256, 144), index, 11) for index in range(2)]
            paths = [write(inputs / f'frame_{index:03d}.png', image)
                     for index, image in enumerate(images)]
            job.update(key=100, style=write(inputs / 'style_100.png', style(images[0])), padding=3,
                       frames=[[100 + index, path] for index, path in enumerate(paths)])
        atomic_json(output / 'job.json', job)
        jobs.append((kind, job))
    return jobs


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(kind, job, backend):
    output = Path(job['output'])
    if not (output / 'COMPLETE.txt').is_file():
        raise RuntimeError(f'{backend}/{kind}: missing completion marker')
    manifest = json.loads((output / 'engine_manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('engine') != LEGACY or manifest.get('revision') != LEGACY_REVISION or
            manifest.get('effective_settings', {}).get('render_options', {}).get('ebsynth_backend') != backend):
        raise RuntimeError(f'{backend}/{kind}: incorrect engine/effective backend provenance')
    names = ['image.png'] if kind == 'image' else ['100.png', '101.png']
    hashes = {}
    for name in names:
        path = output / name
        image = cv2.imread(str(path))
        if image is None or image.shape != (144, 256, 3) or not np.isfinite(image).all() or image.std() == 0:
            raise RuntimeError(f'{backend}/{kind}: invalid output {path}')
        hashes[name] = sha256(path)
    if kind == 'image':
        error = np.load(output / 'error.npy', allow_pickle=False)
        image_manifest = json.loads((output / 'image_manifest.json').read_text(encoding='utf-8'))
        if (error.shape != (144, 256) or not np.isfinite(error).all() or
                image_manifest.get('backend') != backend or image_manifest.get('engine') != LEGACY):
            raise RuntimeError(f'{backend}/{kind}: invalid image error/backend metadata')
    return hashes


def run_backend(base, backend, allow_cuda=False):
    jobs = make_jobs(base, backend)
    commands = ''.join(json.dumps(dict(action='run', job=str(Path(job['output']) / 'job.json'))) + '\n'
                       for _, job in jobs) + '{"action":"quit"}\n'
    environment = dict(os.environ)
    if not allow_cuda:
        # Set before torch or the native CUDA runtime is imported in the worker.
        environment['CUDA_VISIBLE_DEVICES'] = '-1'
    started = time.perf_counter()
    process = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-u',
                              str(ROOT / 'reezsynth_shared_worker.py')],
                             input=commands, capture_output=True, text=True,
                             encoding='utf-8', errors='replace', cwd=ROOT,
                             env=environment, timeout=600)
    elapsed = time.perf_counter() - started
    log = process.stdout + '\n' + process.stderr
    backend_root = base / backend
    (backend_root / 'worker.log').write_text(log, encoding='utf-8')
    if process.returncode or log.count('"event": "job_done"') != len(jobs):
        raise RuntimeError(f'{backend} worker failed; see {backend_root / "worker.log"}')
    if not allow_cuda and log.count('Optical flow device: CPU') != 1:
        raise RuntimeError(f'{backend}: video did not confirm CPU optical flow')
    hashes = {kind: verify(kind, job, backend) for kind, job in jobs}
    return dict(backend=backend, cuda_hidden=not allow_cuda, seconds=elapsed,
                jobs=len(jobs), output_hashes=hashes)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backend', nargs='?', choices=('cpu', 'auto', 'cuda', 'both'), default='both')
    parser.add_argument('--allow-cuda', action='store_true',
                        help='Expose CUDA to workers (required for the explicit cuda backend).')
    args = parser.parse_args(argv)
    if args.backend == 'cuda' and not args.allow_cuda:
        parser.error('the cuda backend requires --allow-cuda')
    selected = ('cpu', 'auto') if args.backend == 'both' else (args.backend,)
    base = ROOT / 'diagnostic_outputs' / ('backend_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    base.mkdir(parents=True)
    report = dict(interpreter=sys.executable, cases=[], output=str(base), passed=False)
    try:
        for backend in selected:
            case = run_backend(base, backend, allow_cuda=args.allow_cuda)
            report['cases'].append(case)
            atomic_json(base / 'report.json', report)
            print(json.dumps(case, indent=2), flush=True)
        report['passed'] = True
        atomic_json(base / 'report.json', report)
    except Exception as exc:
        report['error'] = str(exc)
        atomic_json(base / 'report.json', report)
        raise
    print(f'PASS: {len(selected)} backend(s), real image/video outputs, CPU flow and provenance. {base}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
