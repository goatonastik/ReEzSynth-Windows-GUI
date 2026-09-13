"""Resolved job settings for output metadata; no engine, Qt or GPU imports."""
from reezsynth_engines import FUOUM
from reezsynth_iterations import SCHEDULE_FIELDS


def iteration_settings(result, options):
    """Omit overridden scalars and link the runtime-resolved pyramid mapping."""
    for schedule, scalar in zip(SCHEDULE_FIELDS, ('searchvoteiters', 'patchmatchiters')):
        if options.get(schedule):
            result['render_options'].pop(scalar, None)
            result['iteration_schedule'] = dict(file='iteration_schedule.json',
                order='coarse_to_fine', alignment='finest',
                missing_coarse_levels='repeat_first', excess_coarse_entries='drop')


def effective_settings(job):
    from reezsynth_config import (quality_profile, validate_render, validate_weights,
                                  validate_processing_settings)
    from reezsynth_image import SYNTHESIS_FIELDS, validate_image_settings
    from reezsynth_video_plan import validate_blend_options
    from reezsynth_artifacts import validate_exports

    quality = job.get('quality', 'Standard')
    options = validate_render(dict(quality_profile(quality), **job.get('render_options', {})))
    fuoum = options['engine'] == FUOUM
    image = job.get('type') == 'image_synthesis'
    copy = not image and len(job.get('frames', [])) == 1
    result = dict(kind='image' if image else 'keyframe_copy' if copy else 'video',
                  quality=quality, processing=validate_processing_settings(job))
    if not image:
        from reezsynth_video_export import validate_video_export
        result['video_export'] = validate_video_export(job.get('video_export'))
    native_extra = ('fuoum_vote_mode', 'fuoum_cost_function', 'fuoum_stop_threshold',
                    'fuoum_search_pruning_threshold')
    if copy:
        fields = ['do_mask']
        if options['do_mask']:
            fields += ['feather'] + (['pre_mask'] if fuoum else [])
        result['render_options'] = {name: options[name] for name in fields}
        return result
    if image:
        fields = (*SYNTHESIS_FIELDS, *SCHEDULE_FIELDS, 'ebsynth_backend', *(native_extra if fuoum else ()))
        result['render_options'] = {name: options[name] for name in fields}
        iteration_settings(result, options)
        settings = validate_image_settings(job.get('image_synthesis'))
        result['image_synthesis'] = settings
        result['normalized_guide_weights'] = [settings['source_weight'] / settings['key_weight'],
            *(guide['weight'] / settings['key_weight'] for guide in settings['guides'])]
        result['native_style_weight'] = 1.0
        return result

    resolved = dict(options)
    resolved.pop('engine')
    if fuoum:
        for name in ('flow_arch', 'flow_model', 'memory_efficient_raft'):
            resolved.pop(name)
        inactive_model = 'fuoum_neuflow_model' if options['fuoum_flow_engine'] == 'RAFT' else 'fuoum_raft_model'
        resolved.pop(inactive_model)
        if not options['sparse_features']:
            resolved.pop('fuoum_sparse_anchor_weight')
    else:
        resolved = {name: value for name, value in resolved.items()
                    if not name.startswith('fuoum_') and name not in ('temporal_nnf', 'sparse_features')}
    if options['custom_edge_guides']:
        resolved.pop('edge_method')
    if not options['do_mask']:
        resolved.pop('pre_mask')
        resolved.pop('feather')
    result['render_options'] = resolved
    iteration_settings(result, options)
    weights = validate_weights(job.get('guide_weights'))
    guides = ('edg_wgt', 'img_wgt', 'pos_wgt', 'wrp_wgt') + (('mask_wgt',) if options['do_mask'] else ())
    result['normalized_guide_weights'] = {name: weights[name] / weights['key_wgt'] for name in guides}
    if fuoum and options['sparse_features']:
        result['normalized_guide_weights']['sparse_anchor_weight'] = options['fuoum_sparse_anchor_weight'] / weights['key_wgt']
    result['native_style_weight'] = 1.0
    result['exports'] = validate_exports(job.get('exports'))
    result['blend_options'] = {}
    if job.get('type') == 'grouped_video':
        blend = validate_blend_options(job.get('blend_options'))
        effective = dict(only_mode=blend['only_mode'])
        if blend['only_mode'] == 'none':
            if fuoum:
                solver = blend['fuoum_poisson_solver']
                effective['fuoum_poisson_solver'] = solver
                if solver in ('lsqr', 'lsmr', 'cg', 'amg'):
                    effective.update({name: blend[name] for name in ('poisson_maxiter',
                        'fuoum_poisson_grad_weight_l', 'fuoum_poisson_grad_weight_ab')})
                    if solver == 'amg' and effective['poisson_maxiter'] is None:
                        effective['poisson_maxiter'] = 100
            else:
                effective.update(use_gpu=blend['use_gpu'], use_poisson_cupy=blend['use_poisson_cupy'])
                if not blend['use_poisson_cupy']:
                    effective['use_lsqr'] = blend['use_lsqr']
                if blend['use_poisson_cupy'] or not blend['use_lsqr']:
                    effective['poisson_maxiter'] = blend['poisson_maxiter']
        result['blend_options'] = effective
    return result
