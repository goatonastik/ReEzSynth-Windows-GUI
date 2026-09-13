"""Adapter for the pinned FuouM engine, executed only in its own worker runtime."""
from pathlib import Path
from contextlib import contextmanager
import tempfile
import time

from reezsynth_engines import (FUOUM, activate_fuoum, preflight_flow,
                               validate_capabilities, write_engine_manifest)


def build_configs(options, weights=None, blend=None):
    from ezsynth.config import EbsynthParamsConfig, PipelineConfig, BlendingConfig
    weights, blend = weights or {}, blend or {}
    ratio = weights.get('key_wgt', 1.0)
    native = EbsynthParamsConfig(
        uniformity=options['uniformity'], patch_size=options['patchsize'],
        search_vote_iters=options['searchvoteiters'], patch_match_iters=options['patchmatchiters'],
        extra_pass_3x3=options['extrapass3x3'], backend='cuda',
        vote_mode=options['fuoum_vote_mode'], cost_function=options['fuoum_cost_function'],
        stop_threshold=options['fuoum_stop_threshold'],
        search_pruning_threshold=options['fuoum_search_pruning_threshold'],
        edge_weight=weights.get('edg_wgt', 1.0) / ratio,
        image_weight=weights.get('img_wgt', 6.0) / ratio,
        pos_weight=weights.get('pos_wgt', 2.0) / ratio,
        warp_weight=weights.get('wrp_wgt', .5) / ratio,
        sparse_anchor_weight=options['fuoum_sparse_anchor_weight'] / ratio)
    # FuouM clamps positive depth itself but does not implement the legacy -1 sentinel.
    pipeline = PipelineConfig(pyramid_levels=32 if options['pyramidlevels'] == -1 else options['pyramidlevels'],
                              use_temporal_nnf_propagation=options['temporal_nnf'],
                              use_sparse_feature_guide=options['sparse_features'])
    # The convenience API's use_lsqr argument is ignored by this pinned schema.
    blending = BlendingConfig(poisson_solver=blend.get('fuoum_poisson_solver',
                                                       'lsqr' if blend.get('use_lsqr', True) else 'lsmr'),
                             poisson_maxiter=blend.get('poisson_maxiter'),
                             poisson_grad_weight_l=blend.get('fuoum_poisson_grad_weight_l', 2.5),
                             poisson_grad_weight_ab=blend.get('fuoum_poisson_grad_weight_ab', .5))
    return native, pipeline, blending


def native_guides(pairs):
    import numpy as np
    def hwc(image):
        return np.ascontiguousarray(image[:, :, None] if image.ndim == 2 else image)
    return [(hwc(source), hwc(target), weight) for source, target, weight in pairs]


def install_final_pass_compatibility(engine):
    """Repair missing mode arguments in FuouM's optional final 3x3 pass."""
    backend = engine.backend
    original = backend.run_level
    vote_mode = engine.vote_mode_map[engine.ebsynth_config.vote_mode]
    cost_mode = engine.cost_function_map[engine.ebsynth_config.cost_function]

    def compatible(*args, **kwargs):
        values = list(args)
        if len(values) > 9 and values[9] is None:
            values[9] = vote_mode
        elif len(values) <= 9 and kwargs.get('vote_mode') is None:
            kwargs['vote_mode'] = vote_mode
        if len(values) > 14 and values[14] is None:
            values[14] = cost_mode
        elif len(values) <= 14 and kwargs.get('cost_function_mode') is None:
            kwargs['cost_function_mode'] = cost_mode
        return original(*values, **kwargs)

    backend.run_level = compatible
    return original


@contextmanager
def render_cache(output):
    """Own a private cache for exactly one render and report cleanup failures."""
    with tempfile.TemporaryDirectory(prefix='.fuoum-cache-', dir=output) as path:
        yield path


def synthesize_image(style, pairs, options):
    from ezsynth.engines.synthesis_engine import EbsynthEngine
    native, pipeline, _ = build_configs(options)
    engine = EbsynthEngine(native, pipeline)
    original = install_final_pass_compatibility(engine)
    try:
        return engine.run(style, guides=native_guides(pairs))
    finally:
        engine.backend.run_level = original


def render_fuoum_job(job, progress):
    from reezsynth_config import (validate_render, quality_profile, validate_processing_settings,
                                  validate_weights, validate_synthesis_dimensions)
    from reezsynth_video_plan import validate_blend_options
    from reezsynth_artifacts import validate_exports, save_artifacts, FlowVectorWriter
    options = validate_render(dict(quality_profile(job['quality']), **job.get('render_options', {})))
    blend = validate_blend_options(job.get('blend_options'))
    exports = validate_exports(job.get('exports'))
    from reezsynth_video_export import ffmpeg_executable, validate_video_export
    video_export = validate_video_export(job.get('video_export'), check_audio=True)
    video_ffmpeg = ffmpeg_executable() if video_export['enabled'] else None
    image_job = job.get('type') == 'image_synthesis'
    validate_capabilities(options, image=image_job, blend=job.get('blend_options'), exports=job.get('exports'))
    if options['engine'] != FUOUM:
        raise ValueError('FuouM adapter received a different engine selection.')
    runtime = job.get('engine_runtime')
    if not isinstance(runtime, dict) or runtime.get('engine') != FUOUM:
        raise ValueError('FuouM jobs need an engine_runtime prepared by the frontend.')
    if not image_job and len(job.get('frames', [])) > 1:
        preflight_flow(options, runtime)
    activate_fuoum(runtime)
    write_engine_manifest(job)
    if image_job:
        from reezsynth_image import render_image_job
        return render_image_job(job, progress)
    if job.get('type') not in (None, 'grouped_video'):
        raise ValueError('Unsupported FuouM job type.')

    import cv2
    import numpy as np
    processing = validate_processing_settings(job)
    from reezsynth_sequence import array_sequence, number_lookup, number_of, completion_path
    entries = job['frames']
    numbers = [entry[0] for entry in entries]
    if not numbers or any(type(n) is not int for n in numbers) or numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise ValueError('Video job frames must be consecutive and ordered.')
    style_entries = job.get('styles') if job.get('type') == 'grouped_video' else [[job['key'], job['style']]]
    key_numbers = [entry[0] for entry in style_entries]
    if not key_numbers or key_numbers != sorted(set(key_numbers)) or not set(key_numbers) <= set(numbers):
        raise ValueError('Styled keyframes must be ordered, unique and within the selected range.')
    if type(job.get('padding')) is not int or not 1 <= job['padding'] <= 32:
        raise ValueError('Invalid output frame-number padding.')
    def read(path):
        image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f'Cannot decode image: {path}')
        return image
    original_shape = read(entries[0][1]).shape
    width, height = original_shape[1], original_shape[0]
    scale = min(1.0, processing['max_width'] / width) if processing['max_width'] else 1.0
    size = tuple(processing['processing_size'] or (max(1, round(width * scale)), max(1, round(height * scale))))
    def load_frames(entries):
        values = array_sequence(numbers=[number for number, _ in entries])
        for _, path in entries:
            frame = read(path)
            if frame.shape != original_shape:
                raise ValueError('Source and styled frames must have matching dimensions.')
            values.append(cv2.resize(frame, size, interpolation=cv2.INTER_AREA))
        return values
    frames, styles = load_frames(entries), load_frames(style_entries)
    def load_guides(field, enabled, interpolation):
        if not enabled:
            return []
        entries = job.get(field, [])
        if [entry[0] for entry in entries] != numbers:
            raise ValueError(f'Job {field} frame numbers must match source frames.')
        values = array_sequence()
        for number, path in entries:
            gray = cv2.cvtColor(read(path), cv2.COLOR_BGR2GRAY)
            if gray.shape != original_shape[:2]:
                raise ValueError(f'{field} dimensions differ at frame {number}.')
            values.append(cv2.resize(gray, size, interpolation=interpolation))
        return values
    masks = load_guides('masks', options['do_mask'], cv2.INTER_NEAREST)
    edges = load_guides('edge_guides', options['custom_edge_guides'], cv2.INTER_AREA)
    weights = validate_weights(job.get('guide_weights'))
    originals = frames
    if masks and options['pre_mask']:
        frames = array_sequence(((frame * (mask[..., None].astype(np.float32) / 255)).astype(np.uint8)
                  for frame, mask in zip(frames, masks)), numbers=numbers)
        styles = array_sequence(((style * (masks[numbers.index(key)][..., None].astype(np.float32) / 255)).astype(np.uint8)
                  for key, style in zip(key_numbers, styles)), numbers=key_numbers)
    records, error_maps, flow_images = [], array_sequence(), array_sequence()
    if len(frames) > 1:
        if min(size) < 128:
            raise ValueError('RAFT video dimensions must both be at least 128 pixels.')
        validate_synthesis_dimensions(options['patchsize'], size)
    output = Path(job['output']).resolve()
    vectors = FlowVectorWriter(output, exports['flow_vectors'])
    from reezsynth_preview_transport import PreviewPublisher
    publisher = PreviewPublisher(output)
    if len(frames) == 1:
        results = styles
    else:
        from ezsynth.config import MainConfig, ProjectConfig, PrecomputationConfig, DebugConfig
        from ezsynth.data import ProjectData
        from reezsynth_fuoum_pipeline import extend_pipeline, work_count
        native, pipeline_config, blending = build_configs(options, weights, blend)
        positions = [numbers.index(number) for number in key_numbers]
        expected = work_count(len(frames), positions, blend['only_mode'])
        completed = 0
        lookup = number_lookup(frames, numbers)
        origins = number_lookup(styles, key_numbers)
        progress(10, 'Initializing FuouM synthesis')
        with render_cache(output) as cache:
            config = MainConfig(
                project=ProjectConfig(content_dir=str(output), style_path=[path for _, path in style_entries],
                                      style_indices=positions, output_dir=str(output), cache_dir=cache),
                precomputation=PrecomputationConfig(flow_engine=options['fuoum_flow_engine'],
                                                     flow_model=(options['fuoum_raft_model'] if options['fuoum_flow_engine'] == 'RAFT'
                                                                 else options['fuoum_neuflow_model']),
                                                     edge_method=options['edge_method']),
                pipeline=pipeline_config, blending=blending, ebsynth_params=native, debug=DebugConfig())
            data = ProjectData(config.project)
            # Data has already been validated/resized; bypass its directory scanning and implicit resize.
            data._content_frames, data._style_frames = frames, styles
            def capture_pass(sequence, start, end, forward, result):
                if not any(exports.values()):
                    return
                for i, error in enumerate(result[1]):
                    target = start + i + (1 if forward else 0)
                    lower = start + i
                    flow_from, flow_to = lower, lower + 1
                    if options['fuoum_bidirectional_flow'] and forward:
                        flow_from, flow_to = flow_to, flow_from
                    records.append(dict(sequence=sequence, synthesis_direction='forward' if forward else 'reverse',
                        error_frame=numbers[target], map_kind='synthesis_error',
                        flow_from=numbers[flow_from], flow_to=numbers[flow_to],
                        flow_grid_frame=numbers[flow_from],
                        scope='raw pass output before keyframe preservation and grouped reconstruction'))
                    if exports['maps']:
                        error_maps.append(error)
                    if exports['flow']:
                        flow = np.asarray(result[2][i], dtype=np.float32)
                        magnitude, angle = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                        hsv = np.zeros((*flow.shape[:2], 3), np.uint8)
                        hsv[..., 0] = np.mod(angle * (90 / np.pi), 180).astype(np.uint8)
                        hsv[..., 1] = 255
                        hsv[..., 2] = np.clip(magnitude * 255 / max(float(magnitude.max()), 1e-6), 0, 255).astype(np.uint8)
                        flow_images.append(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))
            pipeline = extend_pipeline(config, data, masks, edges, weights['mask_wgt'] / weights['key_wgt'],
                                       blend['only_mode'], capture_pass, cache_job=job, runtime=runtime,
                                       bidirectional=options['fuoum_bidirectional_flow'],
                                       on_flow=lambda a, b, f: vectors.add(numbers[a], numbers[b], f))
            backend_run_level = install_final_pass_compatibility(pipeline.synthesis_engine)
            original = pipeline.synthesis_engine.run
            def tracked(style, guides, **kwargs):
                nonlocal completed
                started = time.perf_counter()
                result = original(style, guides=native_guides(guides), **kwargs)
                completed += 1
                target = number_of(guides[1][1], lookup)
                origin = number_of(style, origins)
                preview = None
                if target is not None and origin is not None:
                    preview = publisher.publish(origin, 'Backward' if target < origin else 'Forward', target, result[0])
                progress(15 + 65 * completed / max(1, expected), f'FuouM synthesis {completed}/{expected}', preview=preview)
                print(f'[Timing] FuouM frame {completed}/{expected}: {time.perf_counter() - started:.3f}s', flush=True)
                return result
            pipeline.synthesis_engine.run = tracked
            try:
                progress(12, 'Computing optical flow and edge guides')
                results = pipeline.run()
            finally:
                pipeline.synthesis_engine.run = original
                pipeline.synthesis_engine.backend.run_level = backend_run_level
            if completed != expected:
                raise RuntimeError(f'FuouM produced {completed} synthesis calls; expected {expected}.')
    if len(results) != len(frames):
        raise RuntimeError(f'FuouM returned {len(results)} frames; expected {len(frames)}.')
    for index, (number, image) in enumerate(zip(numbers, results)):
        if masks:
            mask = masks[index]
            if options['feather']:
                radius = options['feather']
                mask = cv2.GaussianBlur(mask, (radius, radius), 0)
            alpha = mask[..., None].astype(np.float32) / 255
            image = (image * alpha + originals[index] * (1 - alpha)).astype(np.uint8)
        if not isinstance(image, np.ndarray) or image.shape != frames[index].shape or not np.isfinite(image).all():
            raise RuntimeError(f'Invalid FuouM output at frame {number}.')
        ok, encoded = cv2.imencode('.png', np.clip(image, 0, 255).astype(np.uint8))
        if not ok:
            raise RuntimeError(f'Cannot encode FuouM frame {number}.')
        name = str(number).zfill(job['padding']) + '.png'
        temporary = output / (name + '.part')
        temporary.write_bytes(encoded.tobytes())
        temporary.replace(output / name)
        preview = publisher.publish(key_numbers[0], 'Keyframe', number, image, stage='final') if len(frames) == 1 else None
        progress(90 + 9 * (index + 1) / len(frames), f'Saving {index + 1}/{len(frames)}', preview=preview)
    save_artifacts(output, exports, records, error_maps, flow_images,
                   scope='FuouM raw synthesis passes; frame-aligned errors before blending/compositing')
    vectors.finish()
    if video_export['enabled']:
        progress(99, 'Encoding rendered video')
        from reezsynth_video_export import export_rendered_video
        export_rendered_video(output, numbers, job['padding'], video_export,
                              ffmpeg_exe=video_ffmpeg)
    completion_path(output).write_text(f'Engine: {FUOUM}\nSaved frames: {len(frames)}\n', encoding='utf-8')
    progress(99, 'Finishing FuouM synthesis')
