"""Opt-in real image/video/grouped smoke checks and shared-worker reuse for either engine."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
from reezsynth_config import PREVIEW, validate_render, atomic_json
from reezsynth_engines import ROOT, LEGACY, FUOUM, prepare_runtime
from reezsynth_preview_transport import PREVIEW_DIR, preview_channels


def gpu_memory():
    result = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,memory.free', '--format=csv,noheader,nounits'],
                            capture_output=True, text=True, timeout=10)
    return result.stdout.strip() if result.returncode == 0 else 'unavailable'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('legacy', 'fuoum'), default='fuoum')
    parser.add_argument('--memory-efficient', action='store_true', help='Legacy RAFT only.')
    parser.add_argument('--four-k', action='store_true', help='Legacy video at 3840x2160; requires --memory-efficient.')
    args = parser.parse_args()
    if args.four_k and (args.engine != 'legacy' or not args.memory_efficient):
        parser.error('--four-k requires legacy --memory-efficient')
    if args.memory_efficient and args.engine != 'legacy':
        parser.error('--memory-efficient is for the legacy engine')
    engine = FUOUM if args.engine == 'fuoum' else LEGACY
    options = validate_render(dict(PREVIEW, engine=engine, memory_efficient_raft=args.memory_efficient))
    runtime = prepare_runtime(options, {})
    base = ROOT / 'diagnostic_outputs' / ('engines_' + args.engine + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    base.mkdir(parents=True)
    size = [3840, 2160] if args.four_k else [256, 144]
    jobs = []
    for kind in (('video',) if args.four_k else ('image', 'video', 'grouped')):
        output = base / kind
        output.mkdir()
        job = dict(output=str(output), quality='Preview', processing_size=size,
                   render_options=options, engine_runtime=runtime)
        if kind == 'image':
            example = ROOT / 'examples' / 'texbynum'
            job.update(type='image_synthesis', image_synthesis=dict(style=str(example / 'source_photo.png'),
                       source=str(example / 'source_segment.png'), target=str(example / 'target_segment.png')))
        else:
            job.update(key=100, style=str(ROOT / 'examples/styles/style000.jpg'), padding=3,
                       frames=[[100 + n, str(ROOT / 'examples/input' / (str(n).zfill(3) + '.jpg'))] for n in range(3)])
            if kind == 'grouped':
                job.update(type='grouped_video', styles=[[100, job['style']], [102, str(ROOT / 'examples/styles/style002.png')]],
                           blend_options=dict(use_lsqr=False, poisson_maxiter=10))
        atomic_json(output / 'job.json', job)
        jobs.append(job)
    stopped = threading.Event()
    def renew_previews():
        while not stopped.is_set():
            for job in jobs:
                directory = Path(job['output']) / PREVIEW_DIR
                directory.mkdir(exist_ok=True)
                atomic_json(directory / 'request.json', dict(updated=time.time(), channels=preview_channels(job)))
            stopped.wait(1)
    renew = threading.Thread(target=renew_previews, daemon=True)
    renew.start()
    before = gpu_memory()
    samples = []
    def sample_memory():
        while not stopped.is_set():
            try:
                samples.append(int(gpu_memory().split(',')[0]))
            except (ValueError, subprocess.SubprocessError):
                pass
            stopped.wait(.5)
    memory_sampler = threading.Thread(target=sample_memory, daemon=True)
    memory_sampler.start()
    started = time.perf_counter()
    commands = ''.join(json.dumps(dict(action='run', job=str(Path(job['output']) / 'job.json'))) + '\n' for job in jobs)
    commands += json.dumps(dict(action='quit')) + '\n'
    try:
        result = subprocess.run([runtime['python'], '-X', 'utf8', '-u', str(ROOT / 'reezsynth_shared_worker.py')],
                                input=commands, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                cwd=ROOT, timeout=600 if args.four_k else 240)
    finally:
        stopped.set()
        renew.join(timeout=3)
        memory_sampler.join(timeout=12)
    log = result.stdout + '\n' + result.stderr
    (base / 'worker.log').write_text(log, encoding='utf-8')
    report = dict(engine=engine, seconds=time.perf_counter() - started, exit_code=result.returncode,
                  sampled_aggregate_peak_mib=max(samples) if samples else None,
                  aggregate_gpu_before_mib=before, aggregate_gpu_after_mib=gpu_memory(), outputs=str(base))
    atomic_json(base / 'report.json', report)
    print(json.dumps(report, indent=2))
    if result.returncode:
        print(log[-12000:])
        raise RuntimeError('Engine diagnostic worker failed; see worker.log.')
    if log.count('"event": "job_done"') != len(jobs):
        raise RuntimeError('Shared worker did not acknowledge every job.')
    for job in jobs:
        output = Path(job['output'])
        if not (output / 'COMPLETE.txt').is_file():
            raise RuntimeError(f'Missing completion marker: {output}')
        manifest = json.loads((output / 'engine_manifest.json').read_text(encoding='utf-8'))
        if manifest['engine'] != engine:
            raise RuntimeError('Output engine attribution is incorrect.')
        names = ['image.png'] if job.get('type') == 'image_synthesis' else ['100.png', '101.png', '102.png']
        for name in names:
            image = cv2.imread(str(output / name))
            if image is None or image.shape != (size[1], size[0], 3) or image.std() == 0:
                raise RuntimeError(f'Invalid output shape/content: {output / name}')
        if job.get('type') == 'image_synthesis':
            error = np.load(output / 'error.npy', allow_pickle=False)
            if error.shape != (size[1], size[0]) or not np.isfinite(error).all():
                raise RuntimeError('Invalid image error map.')
        if not list((output / PREVIEW_DIR).glob('*.png')):
            raise RuntimeError(f'No preview produced: {output}')
    print('PASS: requested output cases, engine provenance, previews, numbering and shared-worker exit.')


if __name__ == '__main__':
    main()
