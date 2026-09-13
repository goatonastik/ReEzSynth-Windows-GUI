"""Audit the pinned alternate backend against small mathematical invariants.

Runs each backend in its own worker. This is a readiness gate, not an artistic
quality comparison or a frontend backend selector. Failure reports are retained.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from reezsynth_config import atomic_json
from reezsynth_engines import ROOT, FUOUM, FUOUM_REVISION, prepare_runtime, activate_fuoum


def evaluate_result(image, error, nnf, *, target_size=(19, 17), patch=3,
                    weight=1, modulation=None, cost='ssd'):
    """Independent constant-style/cost oracle; no renderer or torch imports."""
    import numpy as np
    multiplier = 1 if modulation is None else modulation / 255
    # Flat-style NCC contributes patch_area / 3 in this pinned implementation.
    expected_error = patch * patch * (65025 * weight * multiplier + (1 / 3 if cost == 'ncc' else 0))
    finite = bool(np.isfinite(error).all())
    expected_shape = (*target_size[::-1], 3)
    constant_error = int(np.max(np.abs(image.astype(np.int16) - 127)))
    radius = patch // 2
    nnf_valid = bool(nnf.shape == (*target_size[::-1], 2) and
                    ((nnf[..., 0] >= radius) & (nnf[..., 0] < 19 - radius) &
                     (nnf[..., 1] >= radius) & (nnf[..., 1] < 17 - radius)).all())
    checks = dict(output_shape=image.shape == expected_shape,
                  error_shape=error.shape == expected_shape[:2], finite_error=finite,
                  constant_style_preserved=constant_error <= 1,
                  expected_guide_cost=finite and bool(np.allclose(error, expected_error, rtol=1e-4, atol=.01)),
                  valid_nnf=nnf_valid)
    return dict(passed=all(checks.values()), checks=checks,
                image_range=[int(image.min()), int(image.max())], max_constant_error=constant_error,
                mean_error=float(error.mean()) if finite else None, expected_error=expected_error,
                image_sha256=hashlib.sha256(image.tobytes()).hexdigest())


def render_case(backend, *, target_size=(19, 17), iterative=True,
                modulation=None, weight=1, vote='weighted', cost='ssd', patch=3):
    import numpy as np
    import torch
    from ezsynth.config import EbsynthParamsConfig, PipelineConfig
    from ezsynth.engines.synthesis_engine import EbsynthEngine
    from reezsynth_fuoum import install_final_pass_compatibility

    torch.manual_seed(1234)
    style = np.full((17, 19, 3), 127, np.uint8)
    source = np.zeros((17, 19, 1), np.uint8)
    target = np.full((*target_size[::-1], 1), 255, np.uint8)
    native = EbsynthParamsConfig(backend=backend, uniformity=0, patch_size=patch,
        search_vote_iters=1, patch_match_iters=1, extra_pass_3x3=False,
        stop_threshold=0, search_pruning_threshold=0, vote_mode=vote, cost_function=cost)
    pipeline = PipelineConfig(pyramid_levels=1, use_residual_transfer=iterative)
    engine = EbsynthEngine(native, pipeline)
    install_final_pass_compatibility(engine)
    mod = None if modulation is None else np.full(target.shape, modulation, np.uint8)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    image, error, nnf = engine.run(style, [(source, target, weight)],
                                 modulation_map=mod, output_nnf=True)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    return dict(evaluate_result(image, error, nnf, target_size=target_size, patch=patch,
                               weight=weight, modulation=modulation, cost=cost), seconds=elapsed,
                device=engine.device,
                peak_allocated_bytes=torch.cuda.max_memory_allocated() if torch.cuda.is_available() else None)


CASES = (
    ('constant_ssd', {}),
    ('constant_ncc', dict(cost='ncc')),
    ('retarget', dict(target_size=(23, 21))),
    ('noniterative', dict(iterative=False)),
    ('white_map', dict(modulation=255)),
    ('gray_map', dict(modulation=128)),
    ('black_map', dict(modulation=0)),
    ('weighted_high_cost', dict(weight=100, patch=7)),
    ('plain_high_cost', dict(weight=100, patch=7, vote='plain')),
)


def child(backend, output):
    runtime = prepare_runtime(dict(engine=FUOUM), {})
    activate_fuoum(runtime)
    source = Path(runtime['source'])
    inputs = [source / 'ezsynth/config.py', source / 'ezsynth/engines/synthesis_engine.py',
              *sorted((source / 'ezsynth/engines/backends').glob('*.py')),
              *sorted((source / 'ezsynth/torch_ops').glob('*.py')),
              *sorted(source.glob('ebsynth_torch*.pyd'))]
    from reezsynth_engines import file_sha256
    report = dict(backend=backend, revision=FUOUM_REVISION, cases=[], passed=False,
                  source_sha256={str(path.relative_to(source)): file_sha256(path) for path in inputs},
                  diagnostic_sha256=file_sha256(Path(__file__)))
    for label, options in CASES:
        try:
            result = render_case(backend, **options)
        except Exception as error:
            result = dict(passed=False, exception_type=type(error).__name__, exception=str(error))
        result['label'] = label
        report['cases'].append(result)
        print(json.dumps(result), flush=True)
        atomic_json(output, report)
    report['passed'] = all(case['passed'] for case in report['cases'])
    atomic_json(output, report)
    return 0 if report['passed'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('cuda', 'torch', 'both'), default='both')
    parser.add_argument('--child-output', type=Path)
    args = parser.parse_args(argv)
    if args.child_output:
        if args.backend == 'both':
            parser.error('A child must select exactly one backend.')
        return child(args.backend, args.child_output)
    runtime = prepare_runtime(dict(engine=FUOUM), {})
    base = ROOT / 'diagnostic_outputs' / ('torch_backend_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    base.mkdir(parents=True)
    report = dict(passed=False, revision=FUOUM_REVISION, backends=[])
    atomic_json(base / 'report.json', report)
    for backend in (('cuda', 'torch') if args.backend == 'both' else (args.backend,)):
        output = base / (backend + '.json')
        try:
            with (base / (backend + '.log')).open('w', encoding='utf-8') as log:
                result = subprocess.run([runtime['python'], '-B', str(Path(__file__).resolve()),
                    '--backend', backend, '--child-output', str(output)], cwd=ROOT, stdout=log,
                    stderr=subprocess.STDOUT, timeout=180,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            entry = json.loads(output.read_text(encoding='utf-8')) if output.is_file() else dict(passed=False)
            entry['exit_code'] = result.returncode
            entry['passed'] = bool(entry.get('passed') and result.returncode == 0)
        except subprocess.TimeoutExpired:
            entry = dict(backend=backend, passed=False, timed_out=True)
        report['backends'].append(entry)
        atomic_json(base / 'report.json', report)
        print(f'{backend}: {"PASS" if entry["passed"] else "FAIL"}', flush=True)
    report['passed'] = all(entry['passed'] for entry in report['backends'])
    atomic_json(base / 'report.json', report)
    print(('PASS: ' if report['passed'] else 'READINESS FAILED: ') + str(base), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
