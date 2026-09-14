"""Compare the real Legacy exact-key adapter with preserved Windows beta PNGs.

Usage: python -B diagnose_reezsynth_alpha.py diagnostic_outputs/beta_alpha_847bae6e2489
Writes only a new frontend_rgba directory/report. Never overwrites beta evidence.
CPU, one thread, six one-frame jobs; no optical-flow model or sequence render.
This is a differential, not a byte-parity assertion between different engines.
"""
import argparse
import json
import os
from pathlib import Path


def difference(left, right):
    import numpy as np
    def rgba(value):
        if value.shape[2] == 3:
            value = np.dstack((value, np.full(value.shape[:2], 255, np.uint8)))
        return value.astype(np.float64)
    left, right = rgba(left), rgba(right)
    delta = np.abs(left - right)
    def composite(value):
        alpha = value[..., 3:4] / 255
        return value[..., :3] * alpha + 127 * (1 - alpha)
    return dict(rgb_mae=float(delta[..., :3].mean()), rgb_max=float(delta[..., :3].max()),
                alpha_mae=float(delta[..., 3].mean()), alpha_max=float(delta[..., 3].max()),
                composite_gray127_mae=float(np.abs(composite(left) - composite(right)).mean()),
                equal_pixels=int((delta == 0).all(-1).sum()))


def main(reference):
    os.environ['OMP_NUM_THREADS'] = '1'
    import cv2
    import numpy as np
    from reezsynth_jobs import render_job
    reference = Path(reference).resolve()
    cases = json.loads((reference / 'report.json').read_text(encoding='utf-8'))['cases']
    output = reference / 'frontend_rgba'
    output.mkdir(exist_ok=False)
    def read(path):
        result = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
        if result is None:
            raise ValueError(f'Cannot decode {path}')
        return result
    rows = []
    values = {}
    for case in cases:
        name, key = case['case'], case['key']
        folder = output / name
        folder.mkdir()
        style = reference / 'keys' / f'{key:03}.png'
        job = dict(key=key, style=str(style), frames=[[key, str(reference / 'video' / f'{key:03}.png')]],
            output=str(folder), padding=3, quality='Preview', max_width=0,
            render_options=dict(ebsynth_backend='cpu', patchsize=3, pyramidlevels=1,
                searchvoteiters=4, patchmatchiters=4, extrapass3x3=False, uniformity=0,
                stream_frames=False, edge_method='Classic'),
            guide_weights=dict(key_wgt=1, edg_wgt=0, img_wgt=6, pos_wgt=0, wrp_wgt=0, mask_wgt=0))
        path = folder / 'job.json'
        path.write_text(json.dumps(job, indent=2), encoding='utf-8')
        render_job(path)
        result = read(folder / f'{key:03}.png')
        values[name] = result
        rows.append(dict(case=name, shape=list(result.shape),
            vs_beta=difference(result, read(reference / 'beta' / name / f'{key:03}.png')),
            vs_input=difference(result, read(style))))
    report = dict(thread_count=1, scope='Exact keyframes only; no optical flow. RGB jobs retain copy semantics.',
        cases=rows, hidden_payload_effect=difference(values['hidden_black'], values['hidden_white']),
        rgb_vs_opaque=difference(values['rgb'], values['opaque']))
    (output / 'comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


def rgb_identity(reference):
    """Measure the RGB identity-synthesis route without changing RGB production policy."""
    import cv2
    import numpy as np
    from ezsynth.utils._ebsynth import ebsynth
    from reezsynth_alpha import keyframe_guides
    reference = Path(reference).resolve()
    destination = reference / 'frontend_rgb_identity'
    destination.mkdir(exist_ok=False)
    read = lambda path: cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
    style = read(reference / 'keys' / '042.png')
    source = read(reference / 'video' / '042.png')
    eb = ebsynth(uniformity=0, patchsize=3, pyramidlevels=1, searchvoteiters=4,
                 patchmatchiters=4, extrapass3x3=False, backend='cpu')
    eb.runner.initialize_libebsynth()
    result, error = eb.run(style, keyframe_guides(style, source, np.zeros(source.shape[:2], np.uint8),
        dict(edg_wgt=0, img_wgt=6, pos_wgt=0, wrp_wgt=0)))
    if result.shape != style.shape or error.shape != style.shape[:2]:
        raise RuntimeError('Unexpected RGB identity-synthesis output shape.')
    (destination / '042.png').write_bytes(cv2.imencode('.png', result)[1].tobytes())
    report = dict(scope='Direct Legacy RGB identity synthesis; diagnostic only, not production RGB policy.',
        style_shape=list(style.shape), output_shape=list(result.shape),
        vs_beta=difference(result, read(reference / 'beta' / 'rgb' / '042.png')),
        vs_input=difference(result, style))
    (destination / 'comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference')
    parser.add_argument('--rgb-identity', action='store_true')
    args = parser.parse_args()
    (rgb_identity if args.rgb_identity else main)(args.reference)
