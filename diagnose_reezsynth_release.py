"""Repeatable real-render release checks; all generated material goes to diagnostic_outputs."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import queue
import subprocess
import threading
import time

import cv2
import numpy as np
from reezsynth_config import atomic_json, quality_profile, validate_render
from reezsynth_engines import ROOT, LEGACY, FUOUM, prepare_runtime
from diagnose_reezsynth_engines import gpu_memory


def rss_mib(pid):
    # Windows venv python.exe is a small launcher; include its actual worker child.
    value = subprocess.check_output(['powershell', '-NoProfile', '-Command',
        f'$ids = @({int(pid)}); $all = @(Get-CimInstance Win32_Process); '
        'do { $new = @($all | Where-Object { $_.ParentProcessId -in $ids -and $_.ProcessId -notin $ids } | '
        'ForEach-Object { $_.ProcessId }); $ids += $new } while ($new.Count); '
        '(Get-Process -Id $ids -ErrorAction SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum'], text=True, timeout=15,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return int(value.strip()) / 1048576


def write(path, value):
    if not cv2.imwrite(str(path), value):
        raise RuntimeError(f'Could not write diagnostic input: {path}')
    return str(path)


def selected_keyframes(frames, anchors, style_family):
    defaults = [frames[0][0], frames[len(frames) // 2][0], frames[-1][0]]
    return anchors if style_family == 'painting' and len(anchors) >= 2 else defaults


def make_jobs(base, engine, count, repeats, extended, style_family='poster', images=False,
              size=(256, 144), quality='Preview', bidirectional=False, stream_frames=False,
              iteration_schedules=False, modulation=False, synthesis_backend='cuda'):
    inputs = base / 'inputs'
    inputs.mkdir()
    modulation_inputs = inputs / 'modulation'
    if modulation:
        modulation_inputs.mkdir()
    sources = sorted((ROOT / 'examples/input').glob('*.jpg'))
    if len(sources) < 3:
        raise RuntimeError('Bundled video example is missing.')
    frames, styles, masks, edges, anchors, modulation_frames = [], {}, [], [], [], []
    width, height = size
    paintings = {0: ROOT / 'examples/gui_keyframes_v03/style000.jpg',
                 6: ROOT / 'examples/gui_keyframes_v03/style006.png',
                 10: ROOT / 'examples/gui_keyframes_v03/style010.png'}
    for i in range(count):
        # Ping-pong the real clip to exercise repeated motion without hard cuts.
        phase = i % (2 * (len(sources) - 1))
        source_index = min(phase, 2 * (len(sources) - 1) - phase)
        source = sources[source_index]
        image = cv2.resize(cv2.imread(str(source)), size)
        frames.append([100 + i, write(inputs / f'{i:04d}.png', image)])
        stylized = np.clip((image.astype(np.int16) // 48) * 48 + 24, 0, 255).astype(np.uint8)
        if style_family == 'flat':
            stylized[:] = (40, 100, 170)
        elif style_family == 'painting' and source_index in paintings:
            stylized = cv2.resize(cv2.imread(str(paintings[source_index])), size)
            anchors.append(100 + i)
        styles[100 + i] = write(inputs / f'style_{i:04d}.png', stylized)
        mask = np.zeros((height, width), np.uint8)
        mask[:, width // 4:3 * width // 4] = 255
        masks.append([100 + i, write(inputs / f'mask_{i:04d}.png', mask)])
        edges.append([100 + i, write(inputs / f'edge_{i:04d}.png', cv2.Canny(image, 50, 150))])
        if modulation:
            values = np.broadcast_to(np.linspace(0, 255, width, dtype=np.uint8), (height, width)).copy()
            values = np.roll(values, i * 7, axis=1)
            modulation_frames.append([100 + i, write(modulation_inputs / f'map{100 + i:04d}.png', values)])
    options = validate_render(dict(quality_profile(quality), engine=engine,
                                   fuoum_bidirectional_flow=bidirectional, stream_frames=stream_frames,
                                   fuoum_backend=synthesis_backend))
    if iteration_schedules:
        options.update(searchvote_schedule=[8, 4, 2], patchmatch_schedule=[4, 2, 1])
    if modulation:
        options.update(modulation_guide='Video guide', modulation_dir=str(modulation_inputs))
    runtime = prepare_runtime(options, {})
    cases = [('video', {}, {}), ('grouped', {}, {})]
    if modulation:
        cases += [('modulation_' + mode.split()[0].lower(), dict(modulation_guide=mode), {})
                  for mode in ('All guides', 'Edge guide', 'Position guide', 'Warped-style guide')]
        cases += [('modulation_reverse', dict(modulation_guide='All guides', do_mask=True,
                                             pre_mask=True, custom_edge_guides=True), {'only_mode': 'reverse'})]
        if engine == FUOUM:
            cases += [('modulation_ncc', dict(modulation_guide='All guides', fuoum_cost_function='ncc',
                                             fuoum_search_pruning_threshold=0), {})]
    if iteration_schedules:
        cases += [('schedule_one_level', dict(pyramidlevels=1), {}),
                  ('schedule_auto', dict(pyramidlevels=-1), {}),
                  ('schedule_scalar_fallback', dict(searchvote_schedule=[]), {})]
    if extended:
        cases += [('mask_edges', dict(do_mask=True, pre_mask=True, custom_edge_guides=True), {}),
                  ('forward', {}, {'only_mode': 'forward'}), ('reverse', {}, {'only_mode': 'reverse'})]
        if engine == FUOUM:
            cases += [('edge_' + method, {'edge_method': method}, {}) for method in ('PST', 'PAGE')]
            cases += [('raft_kitti', {'fuoum_raft_model': 'kitti'}, {}),
                      ('no_temporal_sparse', dict(temporal_nnf=False, sparse_features=False), {}),
                      ('feather_mask', dict(do_mask=True, feather=9, pre_mask=False), {})]
            cases += [('native_ncc', dict(fuoum_vote_mode='plain', fuoum_cost_function='ncc',
                                         fuoum_search_pruning_threshold=0.0), {})]
            cases += [(f'solver_{s}', {}, {'fuoum_poisson_solver': s})
                      for s in ('lsqr', 'cg', 'amg', 'seamless', 'disabled')]
            cases += [(m, dict(fuoum_flow_engine='NeuFlow', fuoum_neuflow_model=m), {})
                      for m in ('neuflow_sintel', 'neuflow_mixed', 'neuflow_things')]
        else:
            cases += [('compiled_raft', dict(memory_efficient_raft=True), {})]
    jobs = []
    for repeat in range(repeats):
        for label, overrides, blend in cases:
            output = base / f'{repeat:02d}_{label}'
            output.mkdir()
            keyframes = selected_keyframes(frames, anchors, style_family)
            job = dict(output=str(output), quality=quality, processing_size=list(size), padding=3,
                frames=frames, style=styles[keyframes[0]], key=keyframes[0], engine_runtime=runtime,
                render_options=dict(options, **overrides), guide_weights={'mask_wgt': 2.0},
                masks=masks, edge_guides=edges, modulation_frames=modulation_frames,
                exports={'maps': extended, 'flow': extended},
                blend_options=dict(use_lsqr=False, poisson_maxiter=12, **blend))
            if label != 'video' and label != 'compiled_raft':
                job.update(type='grouped_video', styles=[[n, styles[n]] for n in keyframes])
            atomic_json(output / 'job.json', job)
            jobs.append((label, job))
    if images:
        for name, style_name, primary, extras in (
                ('facestyle', 'source_painting.png', 'Gapp', ['Gseg', 'Gpos']),
                ('stylit', 'source_style.png', 'fullgi', ['dirdif', 'dirspc', 'indirb']),
                ('texbynum', 'source_photo.png', 'segment', [])):
            sample = ROOT / 'examples' / name
            def resized(filename, target=False):
                value = cv2.imread(str(sample / filename), cv2.IMREAD_UNCHANGED)
                value = cv2.resize(value, (384, 128) if target else (256, 256), interpolation=cv2.INTER_NEAREST)
                return write(inputs / (name + '_' + filename), value)
            settings = dict(style=resized(style_name), source=resized('source_' + primary + '.png'),
                target=resized('target_' + primary + '.png', True),
                guides=[dict(source=resized('source_' + extra + '.png'),
                             target=resized('target_' + extra + '.png', True), weight=1.0) for extra in extras])
            if modulation:
                map_path = write(inputs / (name + '_modulation.png'),
                                 np.tile(np.linspace(0, 255, 384, dtype=np.uint8), (128, 1)))
                settings['modulation'] = map_path
                if settings['guides']:
                    settings['guides'][-1]['modulation'] = map_path
            output = base / ('image_' + name)
            output.mkdir()
            job = dict(type='image_synthesis', output=str(output), quality=quality, max_width=0,
                render_options=options, engine_runtime=runtime, image_synthesis=settings)
            atomic_json(output / 'job.json', job)
            jobs.append(('image_' + name, job))
    return runtime, jobs


def verify(label, job):
    output = Path(job['output'])
    if not (output / 'COMPLETE.txt').is_file():
        raise RuntimeError(f'{label}: missing completion marker')
    if job['render_options'].get('engine') == FUOUM:
        manifest = json.loads((output / 'engine_manifest.json').read_text())
        implementation = manifest['effective_settings']['synthesis_implementation']
        if implementation['backend'] != job['render_options'].get('fuoum_backend', 'cuda'):
            raise RuntimeError(f'{label}: synthesis backend provenance differs from the requested backend')
        if implementation['backend'] == 'torch':
            from reezsynth_torch_backend import VERSION
            if implementation['implementation'] != VERSION or 'reezsynth_torch_backend.py' not in manifest['adapter_sha256']:
                raise RuntimeError(f'{label}: missing repaired backend identity')
    image_job = job.get('type') == 'image_synthesis'
    image = job.get('image_synthesis', {})
    if ((image_job and any(g.get('modulation') for g in [image, *image.get('guides', [])]))
            or (not image_job and job['render_options'].get('modulation_guide', 'Off') != 'Off')):
        metadata = json.loads((output / 'modulation_manifest.json').read_text())
        if metadata['multiplier'] != 'value / 255' or not metadata['layouts']:
            raise RuntimeError(f'{label}: missing modulation channel mapping')
        if not image_job:
            numbers = {n for n, _ in job['frames']}
            if {item['frame'] for item in metadata['frames']} != numbers or not set(metadata['synthesis_targets']) <= numbers:
                raise RuntimeError(f'{label}: modulation target identities differ from the source range')
    from reezsynth_iterations import active, resolve
    if active(job['render_options']):
        schedule = json.loads((output / 'iteration_schedule.json').read_text())
        if not schedule['resolved'] or any(plan != resolve(job['render_options'], plan['levels'])
                                           for plan in schedule['resolved']):
            raise RuntimeError(f'{label}: invalid resolved iteration schedule')
    if job.get('type') == 'image_synthesis':
        image = cv2.imread(str(output / 'image.png'))
        error = np.load(output / 'error.npy', allow_pickle=False)
        if image is None or image.shape != (128, 384, 3) or error.shape != (128, 384) or not np.isfinite(error).all():
            raise RuntimeError(f'{label}: invalid retargeted image/error dimensions or values')
        return dict(pixel_std=float(image.std()))
    width, height = job['processing_size']
    images = [cv2.imread(str(output / f'{n:03d}.png')) for n, _ in job['frames']]
    if any(f is None or f.shape != (height, width, 3) or not np.isfinite(f).all() for f in images):
        raise RuntimeError(f'{label}: invalid result shape/content')
    if job['render_options']['do_mask']:
        for image, (_, path), (_, mask_path) in zip(images, job['frames'], job['masks']):
            original = cv2.imread(path)
            mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
            feather = job['render_options']['feather']
            if feather:
                mask = cv2.GaussianBlur(mask, (feather, feather), 0)
            if not np.array_equal(image[mask == 0], original[mask == 0]):
                raise RuntimeError('Masked render modified the unmasked background.')
    if job['engine_runtime']['engine'] == FUOUM and not job['render_options']['do_mask']:
        for number, path in job.get('styles', [[job['key'], job['style']]]):
            if not np.array_equal(images[number - 100], cv2.imread(path)):
                raise RuntimeError(f'{label}: a styled keyframe changed.')
    if any(job['exports'].values()):
        manifest = json.loads((output / 'auxiliary/manifest.json').read_text())
        if not manifest['artifacts']:
            raise RuntimeError('Requested auxiliary outputs are empty.')
        for entry in manifest['artifacts']:
            for kind in ('synthesis_error', 'selection_mask'):
                if kind in entry:
                    error = np.load(output / 'auxiliary' / entry[kind]['file'], allow_pickle=False)
                    if not np.isfinite(error).all():
                        raise RuntimeError('Nonfinite raw error export.')
    adjacent = [float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))
                for a, b in zip(images, images[1:])]
    # Descriptive only: motion contributes to this number, so it is not a quality score.
    return dict(mean_adjacent_difference=float(np.mean(adjacent)), max_adjacent_difference=max(adjacent))


def run(engine, count, repeats, extended, style_family='poster', images=False,
        size=(256, 144), quality='Preview', bidirectional=False, stream_frames=False,
        iteration_schedules=False, modulation=False, synthesis_backend='cuda', only=None):
    base = ROOT / 'diagnostic_outputs' / ('release_' + ('fuoum' if engine == FUOUM else 'legacy') +
                                         '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    base.mkdir(parents=True)
    runtime, jobs = make_jobs(base, engine, count, repeats, extended, style_family, images, size, quality,
                              bidirectional, stream_frames, iteration_schedules, modulation, synthesis_backend)
    if only:
        unknown = set(only) - {label for label, _ in jobs}
        if unknown:
            raise ValueError(f'Unknown requested diagnostic case(s): {sorted(unknown)}')
        jobs = [(label, job) for label, job in jobs if label in only]
    process = subprocess.Popen([runtime['python'], '-B', '-X', 'utf8', '-u', str(ROOT / 'reezsynth_shared_worker.py')],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    lines = queue.Queue()
    def reader():
        with (base / 'worker.log').open('w', encoding='utf-8') as log:
            for line in process.stdout:
                log.write(line)
                log.flush()
                if '@@REEZSYNTH_SESSION@@' in line:
                    lines.put(line)
        lines.put(None)
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    report = dict(engine=engine, frames=count, repeats=repeats, style_family=style_family,
                  quality=quality, size=size, bidirectional=bidirectional, stream_frames=stream_frames,
                  iteration_schedules=iteration_schedules, modulation=modulation, synthesis_backend=synthesis_backend,
                  gpu_before=gpu_memory(), jobs=[], passed=False)
    stop_samples, samples = threading.Event(), []
    def sample_gpu():
        while not stop_samples.is_set():
            try:
                samples.append(int(gpu_memory().split(',')[0]))
            except (ValueError, subprocess.SubprocessError):
                pass
            stop_samples.wait(.5)
    sampler = threading.Thread(target=sample_gpu, daemon=True)
    sampler.start()
    try:
        for label, job in jobs:
            started = time.monotonic()
            process.stdin.write(json.dumps(dict(action='run', job=str(Path(job['output']) / 'job.json'))) + '\n')
            process.stdin.flush()
            event = lines.get(timeout=600)
            if event is None or 'job_done' not in event:
                raise RuntimeError(f'Worker failed during {label}; see {base / "worker.log"}')
            metrics = verify(label, job)
            metrics.update(label=label, seconds=time.monotonic() - started,
                           rss_mib=rss_mib(process.pid),
                           gpu_after_job=gpu_memory())
            report['jobs'].append(metrics)
            atomic_json(base / 'report.json', report)
            print(json.dumps(metrics), flush=True)
        process.stdin.write('{"action":"quit"}\n')
        process.stdin.flush()
        if process.wait(timeout=30) != 0:
            raise RuntimeError('Worker did not exit normally.')
        report['passed'] = True
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)
        thread.join(timeout=5)
        stop_samples.set()
        sampler.join(timeout=12)
        report['aggregate_gpu_peak_mib'] = max(samples, default=None)
        report['gpu_after_exit'] = gpu_memory()
        atomic_json(base / 'report.json', report)
    print('PASS:', base, flush=True)
    return base


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=['legacy', 'fuoum'], required=True)
    parser.add_argument('--frames', type=int, default=33)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--extended', action='store_true')
    parser.add_argument('--style', choices=['poster', 'painting', 'flat'], default='poster')
    parser.add_argument('--quality', choices=['Preview', 'Standard', 'Highest'], default='Preview')
    parser.add_argument('--bidirectional', action='store_true', help='Estimate both FuouM flow directions.')
    parser.add_argument('--stream-frames', action='store_true', help='Use disk-backed clip arrays.')
    parser.add_argument('--iteration-schedules', action='store_true', help='Exercise nonuniform per-level iteration counts.')
    parser.add_argument('--modulation', action='store_true', help='Exercise per-guide image and target-frame video modulation.')
    parser.add_argument('--synthesis-backend', choices=('cuda', 'torch'), default='cuda',
                        help='FuouM synthesis implementation; torch uses the frontend repair layer.')
    parser.add_argument('--only', nargs='+', help='Run only these generated case labels (other flags still define cases).')
    parser.add_argument('--images', action='store_true', help='Include three multiguide image retargeting examples.')
    parser.add_argument('--size', nargs=2, type=int, default=[256, 144], metavar=('WIDTH', 'HEIGHT'))
    args = parser.parse_args()
    if args.synthesis_backend == 'torch' and args.engine != 'fuoum':
        parser.error('The alternate PyTorch backend is FuouM-only.')
    if args.frames < 3 or args.repeats < 1:
        parser.error('At least 3 frames and 1 repeat are required.')
    if min(args.size) < 128:
        parser.error('Multi-frame flow requires dimensions of at least 128 pixels.')
    run(FUOUM if args.engine == 'fuoum' else LEGACY, args.frames, args.repeats, args.extended,
        args.style, args.images, tuple(args.size), args.quality, args.bidirectional, args.stream_frames,
        args.iteration_schedules, args.modulation, args.synthesis_backend, args.only)
