"""Opt-in real image/video/grouped smoke checks, including optional CuPy blending."""
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
from reezsynth_synthetic_inputs import frame, image_case, style, write


def gpu_memory():
    result = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,memory.free', '--format=csv,noheader,nounits'],
                            capture_output=True, text=True, timeout=10)
    return result.stdout.strip() if result.returncode == 0 else 'unavailable'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('legacy', 'fuoum'), default='fuoum')
    parser.add_argument('--fuoum-source', default='', help='Test a custom pinned source checkout.')
    parser.add_argument('--fuoum-python', default='', help='Test a custom FuouM worker interpreter.')
    parser.add_argument('--memory-efficient', action='store_true', help='Legacy RAFT only.')
    parser.add_argument('--four-k', action='store_true', help='Legacy video at 3840x2160; requires --memory-efficient.')
    parser.add_argument('--flow-arch', choices=('RAFT', 'EF_RAFT', 'FLOW_DIFF'), default='RAFT',
                        help='Legacy optical-flow architecture to exercise.')
    parser.add_argument('--flow-model', default='', help='Legacy checkpoint name for the selected architecture.')
    parser.add_argument('--gpu-blending', action='store_true',
                        help='Legacy grouped job: use CuPy histogram/matrix acceleration.')
    parser.add_argument('--cupy-poisson', action='store_true',
                        help='Legacy grouped job: also solve Poisson reconstruction with CuPy.')
    parser.add_argument('--export-video', action='store_true',
                        help='Encode video/grouped frame outputs to render.mp4.')
    parser.add_argument('--audio', default='', help='Optional separate audio file for --export-video.')
    args = parser.parse_args()
    if args.four_k and (args.engine != 'legacy' or not args.memory_efficient):
        parser.error('--four-k requires legacy --memory-efficient')
    if args.memory_efficient and args.engine != 'legacy':
        parser.error('--memory-efficient is for the legacy engine')
    if args.flow_arch != 'RAFT' and args.engine != 'legacy':
        parser.error('--flow-arch is for the legacy engine')
    if args.memory_efficient and args.flow_arch != 'RAFT':
        parser.error('--memory-efficient requires --flow-arch RAFT')
    if args.gpu_blending and args.engine != 'legacy':
        parser.error('--gpu-blending is for the legacy engine')
    if args.cupy_poisson and not args.gpu_blending:
        parser.error('--cupy-poisson requires --gpu-blending')
    if args.audio and not args.export_video:
        parser.error('--audio requires --export-video')
    audio = str(Path(args.audio).expanduser().resolve()) if args.audio else ''
    engine = FUOUM if args.engine == 'fuoum' else LEGACY
    model = args.flow_model or {'RAFT': 'sintel', 'EF_RAFT': '25000_ours-sintel',
                                'FLOW_DIFF': 'FlowDiffuser-things'}[args.flow_arch]
    options = validate_render(dict(PREVIEW, engine=engine, memory_efficient_raft=args.memory_efficient,
                                   flow_arch=args.flow_arch, flow_model=model))
    runtime = prepare_runtime(options, dict(fuoum_source=args.fuoum_source, fuoum_python=args.fuoum_python))
    architecture = '' if args.flow_arch == 'RAFT' else '_' + args.flow_arch.lower()
    blending = '_cupy_poisson' if args.cupy_poisson else ('_cupy_blend' if args.gpu_blending else '')
    base = ROOT / 'diagnostic_outputs' / ('engines_' + args.engine + architecture + blending + '_'
                                         + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    base.mkdir(parents=True)
    inputs = base / 'inputs'
    size = [3840, 2160] if args.four_k else [256, 144]
    jobs = []
    for kind in (('video',) if args.four_k else ('image', 'video', 'grouped')):
        output = base / kind
        output.mkdir()
        job = dict(output=str(output), quality='Preview', processing_size=size,
                   render_options=options, engine_runtime=runtime)
        if kind == 'image':
            job.update(type='image_synthesis', image_synthesis=image_case(
                inputs, 'image', source_size=tuple(size), target_size=tuple(size)))
        else:
            images = [frame(tuple(size), n, 11) for n in range(3)]
            paths = [write(inputs / f'frame_{n:03d}.png', image) for n, image in enumerate(images)]
            first_style = write(inputs / 'style_100.png', style(images[0], 0))
            last_style = write(inputs / 'style_102.png', style(images[2], 2))
            job.update(key=100, style=first_style, padding=3,
                       frames=[[100 + n, path] for n, path in enumerate(paths)],
                       video_export=dict(enabled=args.export_video, fps=12.0, audio=audio))
            if kind == 'grouped':
                job.update(type='grouped_video', styles=[[100, first_style], [102, last_style]],
                           blend_options=dict(use_gpu=args.gpu_blending,
                                              use_poisson_cupy=args.cupy_poisson,
                                              use_lsqr=False, poisson_maxiter=10))
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
        if job.get('video_export', {}).get('enabled'):
            video = output / 'render.mp4'
            metadata = json.loads((output / 'rendered_video.json').read_text(encoding='utf-8'))
            if not video.is_file() or video.stat().st_size == 0 or metadata['frames'] != 3 or metadata['fps'] != 12.0:
                raise RuntimeError(f'Invalid rendered-video export: {video}')
        if job.get('type') == 'image_synthesis':
            error = np.load(output / 'error.npy', allow_pickle=False)
            if error.shape != (size[1], size[0]) or not np.isfinite(error).all():
                raise RuntimeError('Invalid image error map.')
        if not list((output / PREVIEW_DIR).glob('*.png')):
            raise RuntimeError(f'No preview produced: {output}')
    print('PASS: requested output cases, engine provenance, previews, numbering and shared-worker exit.')


if __name__ == '__main__':
    main()
