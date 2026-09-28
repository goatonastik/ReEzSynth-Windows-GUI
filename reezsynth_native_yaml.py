"""Explicit projection of pinned FuouM native YAML; no Qt or engine imports.

This is interchange, not a claim of identical output from the native CLI.
Native project paths are deliberately not applied by settings import.
"""
import copy
import math
from pathlib import Path
import re

from reezsynth_config import validate_render, validate_weights, WEIGHTS
from reezsynth_engines import FUOUM, FUOUM_REVISION
from reezsynth_video_plan import validate_blend_options, validate_grouped_selection

DEFAULTS = {
    'project': dict(name='DefaultProject', content_dir='', style_path=[], style_indices=[],
        output_dir='', mask_dir=None, modulation_dir=None, cache_dir='cache/DefaultProject',
        force_recompute_flow=False, force_recompute_edge=False, force_style_size=True),
    'precomputation': dict(flow_engine='RAFT', flow_model='sintel', edge_method='Classic'),
    'pipeline': dict(pyramid_levels=1, use_residual_transfer=True,
        final_pass=dict(enabled=False, strength=1.0), alpha=.75, max_iter=200,
        flip_aug=False, content_loss=False, colorize=True,
        use_temporal_nnf_propagation=False, use_sparse_feature_guide=False),
    'blending': dict(poisson_solver='lsqr', poisson_maxiter=None,
        poisson_grad_weight_l=2.5, poisson_grad_weight_ab=.5),
    'ebsynth_params': dict(uniformity=3500.0, patch_size=7, vote_mode='weighted',
        search_vote_iters=12, patch_match_iters=6, stop_threshold=5,
        search_pruning_threshold=50.0, cost_function='ssd', backend='cuda',
        extra_pass_3x3=False, edge_weight=1.0, image_weight=6.0, pos_weight=2.0,
        warp_weight=.5, sparse_anchor_weight=10.0),
    'debug': dict(save_flow_viz=False, flow_viz_dir='debug/flow_viz'),
}
RENDER_MAP = {
    'ebsynth_params': dict(uniformity='uniformity', patch_size='patchsize',
        vote_mode='fuoum_vote_mode', search_vote_iters='searchvoteiters',
        patch_match_iters='patchmatchiters', stop_threshold='fuoum_stop_threshold',
        search_pruning_threshold='fuoum_search_pruning_threshold', cost_function='fuoum_cost_function',
        backend='fuoum_backend', extra_pass_3x3='extrapass3x3', sparse_anchor_weight='fuoum_sparse_anchor_weight'),
    'pipeline': dict(pyramid_levels='pyramidlevels', use_temporal_nnf_propagation='temporal_nnf',
        use_sparse_feature_guide='sparse_features'),
    'precomputation': dict(flow_engine='fuoum_flow_engine', edge_method='edge_method'),
    'project': dict(force_recompute_flow='fuoum_force_recompute_flow',
        force_recompute_edge='fuoum_force_recompute_edge'),
}
WEIGHT_MAP = dict(edge_weight='edg_wgt', image_weight='img_wgt', pos_weight='pos_wgt', warp_weight='wrp_wgt')
BLEND_MAP = dict(poisson_solver='fuoum_poisson_solver', poisson_maxiter='poisson_maxiter',
    poisson_grad_weight_l='fuoum_poisson_grad_weight_l', poisson_grad_weight_ab='fuoum_poisson_grad_weight_ab')
BASE_NOTES = [
    f'Target schema: FuouM revision {FUOUM_REVISION}.',
    'Interchange does not guarantee native CLI output parity: the GUI uses its own orchestration, output numbering, cache validation and compatibility adapters.',
]


def read_native_yaml(path):
    """Reject ambiguous duplicate mappings and recursive/container aliases."""
    from reezsynth_serialization import _yaml
    yaml = _yaml()
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Native YAML must be no larger than 1 MiB.')
    class Loader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            keys = set()
            for key, _ in node.value:
                value = self.construct_object(key, deep=False)
                if not isinstance(value, str) or value in keys:
                    raise ValueError('Native YAML keys must be unique text keys (merge keys are not supported).')
                keys.add(value)
            return super().construct_mapping(node, deep=deep)
    try:
        data = yaml.load(path.read_text(encoding='utf-8-sig'), Loader=Loader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ValueError('Malformed native YAML. Check its syntax and nesting.') from exc
    # Validate a small, shallow, tree-shaped native document before translation.
    seen = set()
    def check(value, depth=0):
        if depth > 6:
            raise ValueError('Native YAML nesting is too deep.')
        if isinstance(value, (dict, list)):
            if id(value) in seen:
                raise ValueError('Native YAML container aliases are not supported.')
            seen.add(id(value))
            if len(value) > 4096:
                raise ValueError('Native YAML collection is too large.')
            for item in (value.values() if isinstance(value, dict) else value):
                check(item, depth + 1)
        elif value is not None and type(value) not in (str, bool, int, float):
            raise ValueError('Unsupported native YAML value type.')
    check(data)
    return data


def write_native_yaml(path, data, notes):
    """Carry the compatibility report as comments readable by the native loader."""
    from reezsynth_serialization import _yaml
    validate_native(data)
    path = Path(path)
    comments = ['# Native FuouM interchange — compatibility report']
    for note in notes:
        comments.extend('# ' + line for line in note.splitlines())
    text = '\n'.join(comments) + '\n\n' + _yaml().safe_dump(data, allow_unicode=True, sort_keys=False)
    temporary = path.with_suffix(path.suffix + '.tmp')
    try:
        temporary.write_text(text, encoding='utf-8', newline='\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_native(data):
    if not isinstance(data, dict) or 'format' in data:
        raise ValueError('Expected native FuouM YAML, not a frontend project/preset document.')
    if any(not isinstance(key, str) for key in data):
        raise ValueError('Native section names must be text.')
    for section in ('project', 'precomputation', 'pipeline', 'ebsynth_params'):
        if section not in data:
            raise ValueError(f'Native YAML requires a {section} section.')
    notes = list(BASE_NOTES)
    for section in data.keys() - DEFAULTS.keys():
        notes.append(f'Unsupported native section: {section}; not imported.')
    result = copy.deepcopy(DEFAULTS)
    for section, defaults in DEFAULTS.items():
        values = data.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(f'{section} must be a mapping.')
        for name, value in values.items():
            if name not in defaults:
                notes.append(f'Unsupported native field: {section}.{name}; not imported.')
                continue
            default = defaults[name]
            field = f'{section}.{name}'
            if section == 'project' and name == 'style_path':
                if isinstance(value, str):
                    value = [value]
                if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
                    raise ValueError('project.style_path must contain nonempty path strings.')
            elif section == 'project' and name == 'style_indices':
                if not isinstance(value, list) or not value or any(type(v) is not int or v < 0 for v in value) or len(value) != len(set(value)):
                    raise ValueError('project.style_indices must contain unique nonnegative integers.')
            elif default is None:
                if name == 'poisson_maxiter':
                    if value is not None and (type(value) is not int or value < 1):
                        raise ValueError(f'{field} must be null or a positive integer.')
                elif value is not None and not isinstance(value, str):
                    raise ValueError(f'{field} must be null or a path string.')
            elif isinstance(default, dict):
                if not isinstance(value, dict):
                    raise ValueError(f'{field} must be a mapping.')
                for key in value.keys() - default.keys():
                    notes.append(f'Unsupported native field: {field}.{key}; not imported.')
                value = dict(default, **{k: v for k, v in value.items() if k in default})
                if type(value['enabled']) is not bool or type(value['strength']) not in (int, float) or not math.isfinite(value['strength']) or value['strength'] < 0:
                    raise ValueError('Invalid pipeline.final_pass values.')
            elif type(default) is bool:
                if type(value) is not bool:
                    raise ValueError(f'{field} must be true or false.')
            elif type(default) is int:
                if type(value) is not int:
                    raise ValueError(f'{field} must be an integer.')
            elif type(default) is float:
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError(f'{field} must be a finite number.')
            elif not isinstance(value, str):
                raise ValueError(f'{field} must be text.')
            result[section][name] = value
    project = result['project']
    for name in ('content_dir', 'output_dir', 'style_path', 'style_indices'):
        if not project[name]:
            raise ValueError(f'project.{name} is required.')
    if len(project['style_path']) != len(project['style_indices']):
        raise ValueError('Style paths and style indices must have equal lengths.')
    if not 0 <= result['pipeline']['alpha'] <= 1:
        raise ValueError('pipeline.alpha must be between zero and one.')
    return result, notes


def import_settings(data):
    native, notes = validate_native(data)
    if not 1 <= native['pipeline']['pyramid_levels'] <= 32:
        raise ValueError('Native pyramid_levels must be 1–32 for GUI interchange; native negative/zero values are not the GUI automatic-depth sentinel.')
    render = dict(engine=FUOUM)
    for section, mapping in RENDER_MAP.items():
        for field, control in mapping.items():
            render[control] = native[section][field]
    for field in ('vote_mode', 'cost_function', 'backend'):
        render[RENDER_MAP['ebsynth_params'][field]] = native['ebsynth_params'][field].lower()
    render['edge_method'] = render['edge_method'].upper() if render['edge_method'].lower() in ('pst', 'page') else render['edge_method'].title()
    engine = native['precomputation']['flow_engine'].upper()
    render['fuoum_flow_engine'] = {'RAFT': 'RAFT', 'NEUFLOW': 'NeuFlow'}.get(engine, engine)
    model = native['precomputation']['flow_model']
    if engine == 'RAFT':
        render['fuoum_raft_model'] = model
    else:
        render['fuoum_neuflow_model'] = model
    weights = dict(WEIGHTS)
    for field, control in WEIGHT_MAP.items():
        weights[control] = native['ebsynth_params'][field]
    blend = {control: native['blending'][field] for field, control in BLEND_MAP.items()}
    blend['fuoum_poisson_solver'] = blend['fuoum_poisson_solver'].lower()
    blend['use_lsqr'] = blend['fuoum_poisson_solver'] == 'lsqr'
    supported_pipeline = RENDER_MAP['pipeline']
    for field, value in native['pipeline'].items():
        if field not in supported_pipeline and value != DEFAULTS['pipeline'][field]:
            notes.append(f'pipeline.{field} has no GUI equivalent; its native value is NOT applied.')
    if native['debug'] != DEFAULTS['debug']:
        notes.append('Native debug settings are not imported; GUI artifact exports are reset to disabled.')
    notes.extend([
        'Settings-only import: content/style paths, positional style indices, output/cache paths and project name are NOT applied. Current GUI inputs, selection and output naming stay unchanged.',
        'Native indices are zero-based positions, not the numbered frame labels used by the GUI.',
        'Native mask/modulation directories and force_style_size are NOT applied. GUI masks/modulation are disabled; native implicit style resizing is not reproduced.',
        'Rendering, guide weights and blending are replaced. Processing resolution resets to Original, iteration schedules/edge tuning use defaults, auxiliary/video exports are disabled. Application and image-synthesis settings are unchanged.',
    ])
    notes.append('Native input reference (not applied): ' + native['project']['content_dir'])
    if native['project']['force_recompute_flow'] or native['project']['force_recompute_edge']:
        notes.append('Recompute flags are mapped to fresh per-render computation. Unlike native CLI recomputation, GUI shared caches are not overwritten.')
    settings = dict(render_options=validate_render(render), guide_weights=validate_weights(weights),
                    blend_options=validate_blend_options(blend))
    for group, values in settings.items():
        for field, value in values.items():
            if type(value) is float and round(value, 6) != value:
                values[field] = round(value, 6)
                notes.append(f'{group}.{field} rounded to six decimal places to match GUI precision.')
    return settings, notes


def export_project(video, keys, selection, options, weights, blend, output_dir, *, mask_dir='', context=None):
    """Export full source-folder projects only; never copy media or create outputs."""
    options, weights, blend = validate_render(options), validate_weights(weights), validate_blend_options(blend)
    if options['engine'] != FUOUM:
        raise ValueError('Select FuouM before exporting native YAML.')
    numbers = sorted(video)
    if not numbers or any(b != a + 1 for a, b in zip(numbers, numbers[1:])):
        raise ValueError('Native export requires consecutive numbered source frames.')
    selection = validate_grouped_selection(selection)
    start = numbers[0] if selection['start'] is None else selection['start']
    end = numbers[-1] if selection['end'] is None else selection['end']
    if start not in video or end not in video:
        raise ValueError('Native export range endpoints must exist in the source folder.')
    selected = sorted(keys) if selection['keyframes'] is None else selection['keyframes']
    if not selected or any(n not in keys or n not in video or not start <= n <= end for n in selected):
        raise ValueError('Select at least one styled keyframe inside the export range.')
    plan = dict(frames=[[n, str(video[n])] for n in numbers if start <= n <= end],
                styles=[[n, str(keys[n])] for n in selected])
    if [n for n, _ in plan['frames']] != numbers:
        raise ValueError('Native YAML reads the whole content folder. Select the full source range before export; no frames will be silently added.')
    source = Path(video[numbers[0]]).resolve().parent
    from reezsynth_jobs import scan_images
    found, _ = scan_images(source, source=True)
    if {n: Path(p).resolve() for n, p in video.items()} != found:
        raise ValueError('Source folder contents changed. Rebuild the queue before native export.')
    # Pinned native loader sorts naturally by stem, not by final frame number.
    extensions = {'.jpg', '.jpeg', '.png'}
    native_paths = [p.resolve() for p in source.iterdir() if p.suffix.lower() in extensions]
    try:
        native_paths.sort(key=lambda p: [int(c) if c.isdigit() else c for c in re.split('([0-9]+)', p.stem)])
    except TypeError as exc:
        raise ValueError('Native source ordering is ambiguous; use consistent numbered filenames.') from exc
    ordered = [Path(video[n]).resolve() for n in numbers]
    if native_paths != ordered:
        raise ValueError('Native image loading differs from GUI frame ordering or includes extra images. Clean up the source folder before export.')
    native = copy.deepcopy(DEFAULTS)
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise ValueError('Choose a new native output folder. Native CLI outputs are not protected by the GUI queue.')
    if output == source or source.is_relative_to(output):
        raise ValueError('Native output folder must not contain the source folder.')
    cache = output.parent / (output.name + '_cache')
    if cache.exists():
        raise ValueError('The derived native cache folder already exists. Choose a different output folder to avoid stale native cache reuse.')
    from reezsynth_jobs import validate_video_dimensions
    validate_video_dimensions(video, dict(plan['styles']))
    from reezsynth_alpha import read_style
    if any(read_style(path).shape[2] == 4 for _, path in plan['styles']):
        raise ValueError('The pinned native CLI discards style alpha. Use the GUI for transparent FuouM renders; native YAML export cannot preserve these keyframes.')
    native['project'].update(name=output.name, content_dir=str(source),
        style_path=[str(Path(path).resolve()) for _, path in plan['styles']],
        style_indices=[numbers.index(n) for n, _ in plan['styles']], output_dir=str(output),
        cache_dir=str(cache), force_style_size=False,
        mask_dir=str(Path(mask_dir).resolve()) if options['do_mask'] and mask_dir else None)
    for section, mapping in RENDER_MAP.items():
        for field, control in mapping.items():
            native[section][field] = options[control]
    automatic_pyramid = options['pyramidlevels'] == -1
    if automatic_pyramid:
        native['pipeline']['pyramid_levels'] = 32
    native['precomputation']['flow_model'] = options['fuoum_raft_model'] if options['fuoum_flow_engine'] == 'RAFT' else options['fuoum_neuflow_model']
    ratio = weights['key_wgt']
    for field, control in WEIGHT_MAP.items():
        native['ebsynth_params'][field] = weights[control] / ratio
    native['ebsynth_params']['sparse_anchor_weight'] = options['fuoum_sparse_anchor_weight'] / ratio
    for field, control in BLEND_MAP.items():
        native['blending'][field] = blend[control]
    notes = list(BASE_NOTES)
    if automatic_pyramid:
        notes.append('GUI Automatic pyramid depth is exported as the native fixed maximum of 32 levels. Native results can differ from the GUI\'s size-dependent automatic depth.')
    notes.append('Full source folder exported. Native style_indices are zero-based frame positions; native output filenames restart at 00000. Inputs are absolute Windows paths, not portable media bundles.')
    notes.append('Native output and cache paths are separate from GUI jobs. Running the native CLI is manual; this action only writes YAML.')
    if ratio != 1:
        notes.append('Guide and sparse-anchor weights are divided by the GUI key weight. Native YAML has no separate key-weight setting; import uses key weight 1.')
    omitted = []
    for name in ('custom_edge_guides', 'fuoum_bidirectional_flow', 'stream_frames', 'pre_mask', 'feather'):
        if options[name]:
            omitted.append(name)
    for name in ('searchvote_schedule', 'patchmatch_schedule'):
        if options[name]:
            omitted.append(name)
    if options['modulation_guide'] != 'Off':
        omitted.append('guide-specific modulation (native modulation_dir is left null)')
    from reezsynth_edges import EDGE_DEFAULTS
    if any(options[name] != value for name, value in EDGE_DEFAULTS.items()):
        omitted.append('advanced edge tuning')
    if weights['mask_wgt']:
        omitted.append('mask guide weight')
    if blend['only_mode'] != 'none':
        omitted.append('forward/reverse-only mode (native CLI uses normal blending)')
    if blend['use_gpu'] or blend['use_poisson_cupy']:
        omitted.append('legacy GPU/CuPy blending')
    context = context or {}
    if context.get('processing_size') or context.get('max_width'):
        omitted.append('processing resize (native CLI reads original-size source images)')
    if any(context.get('exports', {}).values()) or context.get('video_export', {}).get('enabled'):
        omitted.append('GUI auxiliary/video exports')
    if omitted:
        notes.append('NOT represented in native YAML: ' + ', '.join(omitted) + '. Native results can differ.')
    if options['do_mask']:
        notes.append('Mask directory exported, but native masking/compositing is not guaranteed equivalent to GUI mask handling.')
    if options['fuoum_force_recompute_flow'] or options['fuoum_force_recompute_edge']:
        notes.append('Native recompute flags may rewrite its cache; GUI recompute preserves existing shared caches.')
    if options['fuoum_backend'] == 'torch':
        notes.append('Native torch does not include the GUI compatibility implementation; equivalence is not guaranteed.')
    validate_native(native)
    return native, notes
