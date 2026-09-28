"""Shared edge-tuning schema and dispatch; importing this does not load an engine."""
import math

from reezsynth_engines import LEGACY

# Defaults match both pinned engines. Keys are frontend-owned, not RunConfig fields.
EDGE_SPECS = {
    'edge_pst_s': ('PST', 'S', 'Phase strength', .3, 0., 100.),
    'edge_pst_w': ('PST', 'W', 'Warp strength', 15., .000001, 1000.),
    'edge_pst_sigma': ('PST', 'sigma_LPF', 'Low-pass sigma', .15, .000001, 100.),
    'edge_pst_min': ('PST', 'thresh_min', 'Lower threshold', .05, 0., 1.),
    'edge_pst_max': ('PST', 'thresh_max', 'Upper threshold', .9, 0., 1.),
    'edge_pst_morph': ('PST', 'morph_flag', 'Morphological cleanup', True, None, None),
    'edge_page_mu1': ('PAGE', 'mu_1', 'First frequency center', 0., 0., 1.),
    'edge_page_mu2': ('PAGE', 'mu_2', 'Second frequency center', .35, 0., 1.),
    'edge_page_sigma1': ('PAGE', 'sigma_1', 'First frequency sigma', .05, .000001, 100.),
    'edge_page_sigma2': ('PAGE', 'sigma_2', 'Second frequency sigma', .8, .000001, 100.),
    'edge_page_s1': ('PAGE', 'S1', 'First phase strength', .8, 0., 100.),
    'edge_page_s2': ('PAGE', 'S2', 'Second phase strength', .8, 0., 100.),
    'edge_page_sigma': ('PAGE', 'sigma_LPF', 'Low-pass sigma', .1, .000001, 100.),
    'edge_page_min': ('PAGE', 'thresh_min', 'Lower threshold', 0., 0., 1.),
    'edge_page_max': ('PAGE', 'thresh_max', 'Upper threshold', .9, 0., 1.),
    'edge_page_morph': ('PAGE', 'morph_flag', 'Morphological cleanup', True, None, None),
}
EDGE_DEFAULTS = {name: spec[3] for name, spec in EDGE_SPECS.items()}


def validate_edge_settings(options=None, method=None):
    options = options or {}
    if method is None:
        method = options.get('edge_method')
    if method not in (None, 'Classic', 'PST', 'PAGE'):
        raise ValueError('Unknown edge method.')
    values = {name: options.get(name, default) for name, default in EDGE_DEFAULTS.items()}
    for name, value in values.items():
        _, _, label, default, low, high = EDGE_SPECS[name]
        if isinstance(default, bool):
            if type(value) is not bool:
                raise ValueError(f'{label} must be true or false.')
        elif type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{label} must be a finite number between {low} and {high}.')
    prefixes = {'Classic': (), 'PST': ('edge_pst',), 'PAGE': ('edge_page',)}.get(
        method, ('edge_pst', 'edge_page'))
    for prefix in prefixes:
        if values[prefix + '_min'] >= values[prefix + '_max']:
            raise ValueError(f'{method or prefix.removeprefix("edge_").upper()} edge lower threshold must be less than upper threshold.')
    return values


def edge_parameters(method, options=None):
    if method not in ('Classic', 'PST', 'PAGE'):
        raise ValueError('Unknown edge method.')
    values = validate_edge_settings(options, method)
    return {spec[1]: int(values[name]) if isinstance(spec[3], bool) else values[name]
            for name, spec in EDGE_SPECS.items() if spec[0] == method}


def compute_tuned_edge(detector, frame, method, options=None):
    """Use the selected engine's actual detector and existing postprocessing."""
    parameters = edge_parameters(method, options)
    if parameters == edge_parameters(method):
        return detector.compute_edge(frame)
    raw = (detector.pst_run(frame, **parameters) if method == 'PST'
           else detector.page_run(frame, **parameters))
    import numpy as np
    if not np.isfinite(raw).all():
        raise ValueError('Edge detector returned non-finite values. Adjust edge settings.')
    return detector.pst_page_postprocess(raw)


def compute_edge_frames(frames, method, options=None, engine=LEGACY):
    import numpy as np
    from reezsynth_sequence import array_sequence
    if engine == LEGACY:
        from ezsynth.edge_detection import EdgeDetector
    else:
        from ezsynth.edge.edge_detection import EdgeDetector
    detector = EdgeDetector(method)
    values = array_sequence()
    for frame in frames:
        edge = compute_tuned_edge(detector, frame, method, options)
        if engine != LEGACY and edge.ndim == 2:
            edge = np.stack([edge] * 3, axis=-1)
        if not np.isfinite(edge).all():
            raise ValueError('Edge detector returned non-finite values. Adjust edge settings.')
        values.append(edge)
    return values
