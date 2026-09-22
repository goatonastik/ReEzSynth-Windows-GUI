"""Run small real checks through the frontend renderer adapter.

Generates three deterministic inputs at a 512-pixel processing width. It deliberately
exercises masks and custom edge guides, then verifies completion and output
dimensions.  Results are written only under ignored diagnostic_outputs/.
"""
from datetime import datetime
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import cv2
import numpy as np

from reezsynth_jobs import render_job
from reezsynth_preview_transport import PREVIEW_DIR
from reezsynth_synthetic_inputs import frame, image_case, style, write


def output_directory(root, label):
    output = root / 'diagnostic_outputs' / (label + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    output.mkdir(parents=True, exist_ok=False)
    return output


def render(job_paths, root, shared_worker=False):
    """Run a diagnostic job directly or through the normal persistent worker."""
    if isinstance(job_paths, (str, Path)):
        job_paths = [job_paths]
    job_paths = [Path(path).resolve() for path in job_paths]
    if not shared_worker:
        for job_path in job_paths:
            render_job(job_path)
        return
    command = [sys.executable, '-X', 'utf8', '-u', str(root / 'reezsynth_shared_worker.py')]
    commands = ''.join(json.dumps({'action': 'run', 'job': str(job_path)}) + '\n' for job_path in job_paths)
    commands += json.dumps({'action': 'quit'}) + '\n'
    completed = subprocess.run(command, input=commands, text=True, encoding='utf-8',
                               errors='replace', capture_output=True, timeout=180, cwd=root)
    print(completed.stdout, end='')
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end='')
    expected = ['@@REEZSYNTH_SESSION@@' + json.dumps(
        {'event': 'job_done', 'job': str(job_path)}, ensure_ascii=True) for job_path in job_paths]
    if completed.returncode != 0 or any(event not in completed.stdout for event in expected):
        raise RuntimeError('Shared worker did not report successful completion and normal exit.')


def cancel_worker(job_path, root):
    """Force-kill a real worker after it begins synthesis, like Stop Queue."""
    command = [sys.executable, '-X', 'utf8', '-u', str(root / 'reezsynth_shared_worker.py')]
    process = subprocess.Popen(command, cwd=root, text=True, encoding='utf-8', errors='replace',
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    cancelled = False
    try:
        process.stdin.write(json.dumps({'action': 'run', 'job': str(job_path.resolve())}) + '\n')
        process.stdin.flush()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and process.poll() is None:
            line = process.stdout.readline()
            if line:
                print(line, end='')
                if '"stage": "Synthesis 0/' in line:
                    process.kill()
                    cancelled = True
                    break
            else:
                time.sleep(.05)
        if not cancelled:
            raise RuntimeError('Worker ended or timed out before cancellation could begin.')
        process.wait(timeout=30)
        remaining = process.stdout.read()
        if remaining:
            print(remaining, end='')
        if process.returncode == 0:
            raise RuntimeError('Cancelled worker unexpectedly exited successfully.')
    finally:
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)


def render_parallel(job_paths, root):
    """Run independent job processes concurrently, like the parallel queue."""
    job_paths = [Path(path).resolve() for path in job_paths]
    command = lambda job_path: [sys.executable, '-X', 'utf8', '-u',
                                str(root / 'reezsynth_jobs.py'), str(job_path)]
    def run_one(job_path):
        return subprocess.run(command(job_path), cwd=root, text=True, encoding='utf-8',
                              errors='replace', capture_output=True, timeout=180)
    # Each thread drains one child's pipes as it runs; waiting on output streams
    # sequentially could deadlock a verbose pair of workers on Windows.
    with ThreadPoolExecutor(max_workers=len(job_paths)) as pool:
        results = list(pool.map(run_one, job_paths))
    for result in results:
        if result.stdout:
            print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, file=sys.stderr, end='')
        if result.returncode != 0:
            raise RuntimeError('Parallel diagnostic worker failed.')


def run_image(root, shared_worker=False):
    output = output_directory(root, 'image_adapter')
    settings = image_case(output / 'inputs', 'image', source_size=(512, 288),
                          target_size=(512, 288))
    settings['folder'] = 'image_adapter'
    job = {
        'type': 'image_synthesis',
        'output': str(output),
        'quality': 'Preview',
        'max_width': 512,
        'render_options': {'ebsynth_backend': 'cuda'},
        'image_synthesis': settings,
    }
    job_path = output / 'job.json'
    job_path.write_text(json.dumps(job, indent=2), encoding='utf-8')
    started = time.perf_counter()
    render(job_path, root, shared_worker)
    target = cv2.imread(settings['target'], cv2.IMREAD_UNCHANGED)
    image = cv2.imread(str(output / 'image.png'), cv2.IMREAD_COLOR)
    error = np.load(output / 'error.npy', allow_pickle=False)
    expected = (*target.shape[:2], 3)
    if image is None or image.shape != expected or error.shape != target.shape[:2]:
        raise RuntimeError('Image Synthesis adapter did not produce the expected output dimensions.')
    if not (output / 'image_manifest.json').is_file() or not (output / 'COMPLETE.txt').is_file():
        raise RuntimeError('Image Synthesis adapter did not complete its required artifacts.')
    print(f'Image adapter diagnostic passed in {time.perf_counter() - started:.3f}s.')
    print('Output folder:', output)


def run_video(root, shared_worker=False, live_preview=False, reuse_worker=False, cancel=False, parallel=False):
    output = root / 'diagnostic_outputs' / ('adapter_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    masks = output / 'masks'
    edges = output / 'edges'
    output.mkdir(parents=True, exist_ok=False)
    masks.mkdir()
    edges.mkdir()
    inputs = output / 'inputs'

    frames = []
    mask_entries = []
    edge_entries = []
    for number in range(3):
        image = frame((512, 288), number, 11)
        source = write(inputs / f'frame{number:03d}.png', image)
        mask = masks / f'mask{number:03d}.png'
        edge = edges / f'edge{number:03d}.png'
        if not cv2.imwrite(str(mask), np.full(image.shape[:2], 255, np.uint8)):
            raise RuntimeError(f'Could not create diagnostic mask: {mask}')
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if not cv2.imwrite(str(edge), cv2.Canny(gray, 80, 160)):
            raise RuntimeError(f'Could not create diagnostic edge guide: {edge}')
        frames.append([number, source])
        mask_entries.append([number, str(mask)])
        edge_entries.append([number, str(edge)])

    job = {
        'key': 0,
        'style': write(inputs / 'style000.png', style(frame((512, 288), 0, 11))),
        'frames': frames,
        'masks': mask_entries,
        'edge_guides': edge_entries,
        'output': str(output),
        'padding': 3,
        'quality': 'Preview',
        'max_width': 512,
        'render_options': {'do_mask': True, 'custom_edge_guides': True},
    }
    if cancel:
        # Reuse the three small generated inputs under consecutive frame numbers.
        # This keeps the diagnostic lightweight but guarantees enough work to stop.
        job['frames'] = [[number, frames[number % 3][1]]
                         for number in range(24)]
        job['masks'] = [[number, str(masks / f'mask{number % 3:03d}.png')] for number in range(24)]
        job['edge_guides'] = [[number, str(edges / f'edge{number % 3:03d}.png')] for number in range(24)]
    job_path = output / 'job.json'
    job_path.write_text(json.dumps(job, indent=2), encoding='utf-8')
    job_paths = [job_path]
    outputs = [output]
    if reuse_worker or parallel:
        second_output = output.parent / (output.name + '_second')
        second_output.mkdir()
        second_job = dict(job, output=str(second_output))
        second_path = second_output / 'job.json'
        second_path.write_text(json.dumps(second_job, indent=2), encoding='utf-8')
        job_paths.append(second_path)
        outputs.append(second_output)
    preview_path = output / PREVIEW_DIR / '0_forward.png'
    preview_stop = None
    preview_thread = None
    if live_preview:
        request = preview_path.parent / 'request.json'
        request.parent.mkdir()
        def renew_preview_request():
            temporary = request.with_suffix('.json.part')
            temporary.write_text(json.dumps({'updated': time.time(), 'channels': [[0, 'Forward']]}), encoding='utf-8')
            temporary.replace(request)

        renew_preview_request()
        preview_stop = threading.Event()
        def keep_preview_request_current():
            while not preview_stop.wait(1):
                renew_preview_request()
        preview_thread = threading.Thread(target=keep_preview_request_current,
                                          name='reezsynth-diagnostic-preview', daemon=True)
        preview_thread.start()
    started = time.perf_counter()
    try:
        if cancel:
            cancel_worker(job_path, root)
        elif parallel:
            render_parallel(job_paths, root)
        else:
            render(job_paths, root, shared_worker)
    finally:
        if preview_stop is not None:
            preview_stop.set()
            preview_thread.join(timeout=2)

    if cancel:
        if (output / 'COMPLETE.txt').exists():
            raise RuntimeError('Cancelled worker wrote COMPLETE.txt.')
        print(f'Worker cancellation diagnostic passed in {time.perf_counter() - started:.3f}s.')
        print('Output folder:', output)
        return

    expected = (288, 512, 3)
    for result_output in outputs:
        for number in range(3):
            image = cv2.imread(str(result_output / f'{number:03d}.png'), cv2.IMREAD_COLOR)
            if image is None or image.shape != expected or not np.isfinite(image).all():
                raise RuntimeError(f'Invalid adapter output for frame {number}: {None if image is None else image.shape}')
        if not (result_output / 'COMPLETE.txt').is_file():
            raise RuntimeError('Frontend adapter did not write COMPLETE.txt.')
    if live_preview:
        thumbnail = cv2.imread(str(preview_path), cv2.IMREAD_COLOR)
        if thumbnail is None or thumbnail.shape[2] != 3:
            raise RuntimeError('Live preview request did not receive a synthesized thumbnail.')
    print(f'Adapter diagnostic passed in {time.perf_counter() - started:.3f}s.')
    print('Output folder:', output)


def run_grouped(root, shared_worker=False):
    output = output_directory(root, 'grouped_adapter')
    inputs = output / 'inputs'
    images = [frame((512, 288), number, 11) for number in range(3)]
    frames = [[number, write(inputs / f'frame{number:03d}.png', image)]
              for number, image in enumerate(images)]
    styles = [[0, write(inputs / 'style000.png', style(images[0], 0))],
              [2, write(inputs / 'style002.png', style(images[2], 2))]]
    job = {
        'type': 'grouped_video',
        'key': 0,
        'style': styles[0][1],
        'styles': styles,
        'frames': frames,
        'output': str(output),
        'padding': 3,
        'quality': 'Preview',
        'max_width': 512,
        'blend_options': {'only_mode': 'none', 'use_gpu': False, 'use_lsqr': True,
                          'use_poisson_cupy': False, 'poisson_maxiter': None},
    }
    job_path = output / 'job.json'
    job_path.write_text(json.dumps(job, indent=2), encoding='utf-8')
    started = time.perf_counter()
    render(job_path, root, shared_worker)
    for number in range(3):
        image = cv2.imread(str(output / f'{number:03d}.png'), cv2.IMREAD_COLOR)
        if image is None or image.shape != (288, 512, 3) or not np.isfinite(image).all():
            raise RuntimeError(f'Invalid grouped adapter output for frame {number}.')
    if not (output / 'COMPLETE.txt').is_file():
        raise RuntimeError('Grouped adapter did not write COMPLETE.txt.')
    print(f'Grouped adapter diagnostic passed in {time.perf_counter() - started:.3f}s.')
    print('Output folder:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', action='store_true', help='Check Image Synthesis instead of video.')
    parser.add_argument('--grouped', action='store_true', help='Check grouped video blending instead of independent video.')
    parser.add_argument('--shared-worker', action='store_true',
                        help='Run the selected small job through the persistent worker and verify job_done/exit.')
    parser.add_argument('--live-preview', action='store_true',
                        help='Video only: request and verify a synthesized live-preview thumbnail.')
    parser.add_argument('--reuse-worker', action='store_true',
                        help='Video only: send two jobs through one shared worker and verify both complete.')
    parser.add_argument('--cancel-worker', action='store_true',
                        help='Video only: force-kill a worker after synthesis begins and require no completion marker.')
    parser.add_argument('--parallel-workers', action='store_true',
                        help='Video only: run two independent jobs concurrently, like parallel rendering.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.image and args.grouped:
        raise SystemExit('Choose either --image or --grouped.')
    if args.image:
        if args.live_preview or args.reuse_worker or args.cancel_worker or args.parallel_workers:
            raise SystemExit('Video-only diagnostic options were supplied with --image.')
        run_image(root, args.shared_worker)
    elif args.grouped:
        if args.live_preview or args.reuse_worker or args.cancel_worker or args.parallel_workers:
            raise SystemExit('Video-only diagnostic options were supplied with --grouped.')
        run_grouped(root, args.shared_worker)
    else:
        if sum(bool(option) for option in (args.live_preview, args.reuse_worker,
                                            args.cancel_worker, args.parallel_workers)) > 1:
            raise SystemExit('Choose only one of --live-preview, --reuse-worker, --cancel-worker, or --parallel-workers.')
        run_video(root, args.shared_worker or args.reuse_worker, args.live_preview,
                  args.reuse_worker, args.cancel_worker, args.parallel_workers)
