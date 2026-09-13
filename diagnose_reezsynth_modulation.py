"""Verify native modulation semantics on a controlled constant-image problem."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from reezsynth_config import atomic_json, validate_render
from reezsynth_engines import ROOT, FUOUM, LEGACY, prepare_runtime, activate_fuoum
from reezsynth_modulation import pack_maps, legacy_modulation


def probe(engine, backend='cuda'):
    style = np.zeros((17, 19, 3), np.uint8)
    source = np.zeros((17, 19, 1), np.uint8)
    target = np.full((17, 19, 1), 255, np.uint8)
    pairs = [(source, target, 1.0)]
    options = validate_render(dict(engine=engine, uniformity=0, patchsize=3, pyramidlevels=1,
        searchvoteiters=1, patchmatchiters=1, extrapass3x3=False, fuoum_stop_threshold=0,
        fuoum_search_pruning_threshold=0))
    if engine == FUOUM:
        runtime = prepare_runtime(options, {})
        activate_fuoum(runtime)
        from reezsynth_fuoum import build_configs
        from ezsynth.engines.synthesis_engine import EbsynthEngine
        native, pipeline, _ = build_configs(options)
        runner = EbsynthEngine(native, pipeline)
    else:
        from ezsynth.utils._ebsynth import ebsynth
        runner = ebsynth(uniformity=0, patchsize=3, pyramidlevels=1,
                          searchvoteiters=1, patchmatchiters=1, extrapass3x3=False)
        runner.runner.initialize_libebsynth()
        runner.backend = runner.backends[backend]
    def render(pairs, maps):
        packed = pack_maps(pairs, maps)
        if engine == FUOUM:
            image, error = runner.run(style, guides=pairs, modulation_map=packed)
        else:
            with legacy_modulation(runner, packed):
                image, error = runner.run(style, pairs)
        if not np.isfinite(error).all() or np.any(image):
            raise RuntimeError('Invalid output for the constant-style native probe.')
        return float(error.mean())
    metrics = {}
    for value in (None, 255, 128, 0):
        metrics[str(value)] = render(pairs, [None if value is None else np.full(target.shape[:2], value, np.uint8)])
    if metrics['None'] <= 0 or not np.isclose(metrics['255'], metrics['None'], rtol=1e-4) or metrics['0'] != 0:
        raise RuntimeError(f'Unexpected native black/white modulation semantics: {metrics}')
    metrics['gray_ratio'] = metrics['128'] / metrics['255']
    if not np.isclose(metrics['gray_ratio'], 128 / 255, rtol=1e-5):
        raise RuntimeError('Native grayscale modulation is not the expected linear multiplier.')
    pairs = [(source, target, 1), (np.repeat(source, 3, 2), np.repeat(target, 3, 2), 3)]
    zero = np.zeros(target.shape[:2], np.uint8)
    combined = render(pairs, [None, None])
    metrics['disable_first_ratio'] = render(pairs, [zero, None]) / combined
    metrics['disable_second_ratio'] = render(pairs, [None, zero]) / combined
    if not np.allclose([metrics['disable_first_ratio'], metrics['disable_second_ratio']], [.75, .25], rtol=1e-5):
        raise RuntimeError('Native modulation was applied to the wrong guide channels.')
    print('@@MODULATION@@' + json.dumps(dict(engine=engine, backend=backend, metrics=metrics)), flush=True)
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('legacy', 'fuoum', 'both'), default='both')
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--legacy-backend', choices=('cuda', 'cpu', 'auto'), default='cuda')
    args = parser.parse_args()
    if args.child:
        probe(FUOUM if args.engine == 'fuoum' else LEGACY, args.legacy_backend)
        return
    base = ROOT / 'diagnostic_outputs' / ('modulation_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    base.mkdir(parents=True)
    report = dict(passed=False, probes=[])
    try:
        for name in (('legacy', 'fuoum') if args.engine == 'both' else (args.engine,)):
            runtime = prepare_runtime(dict(engine=FUOUM if name == 'fuoum' else LEGACY), {})
            result = subprocess.run([runtime['python'], '-B', str(Path(__file__).resolve()),
                '--engine', name, '--child', '--legacy-backend', args.legacy_backend], cwd=ROOT, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=180,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            (base / (name + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
            if result.returncode:
                raise RuntimeError(f'{name} native probe failed: {base / (name + ".log")}')
            entry = next(json.loads(line.split('@@MODULATION@@', 1)[1])
                         for line in result.stdout.splitlines() if '@@MODULATION@@' in line)
            report['probes'].append(entry)
            print(entry, flush=True)
        report['passed'] = True
    finally:
        atomic_json(base / 'report.json', report)
    print('PASS:', base)


if __name__ == '__main__':
    main()
