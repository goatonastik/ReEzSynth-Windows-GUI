"""Adapter for the pinned FuouM engine, executed only in its own worker runtime."""
from pathlib import Path
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
        edge_weight=weights.get('edg_wgt', 1.0) / ratio,
        image_weight=weights.get('img_wgt', 6.0) / ratio,
        pos_weight=weights.get('pos_wgt', 2.0) / ratio,
        warp_weight=weights.get('wrp_wgt', .5) / ratio)
    # FuouM clamps positive depth itself but does not implement the legacy -1 sentinel.
    pipeline = PipelineConfig(pyramid_levels=32 if options['pyramidlevels'] == -1 else options['pyramidlevels'],
                              use_temporal_nnf_propagation=options['temporal_nnf'],
                              use_sparse_feature_guide=options['sparse_features'])
    # The convenience API's use_lsqr argument is ignored by this pinned schema.
    blending = BlendingConfig(poisson_solver='lsqr' if blend.get('use_lsqr', True) else 'lsmr',
                             poisson_maxiter=blend.get('poisson_maxiter'))
    return native, pipeline, blending


def native_guides(pairs):
    import numpy as np
    def hwc(image):
        return np.ascontiguousarray(image[:, :, None] if image.ndim == 2 else image)
    return [(hwc(source), hwc(target), weight) for source, target, weight in pairs]


def synthesize_image(style, pairs, options):
    from ezsynth.engines.synthesis_engine import EbsynthEngine
    native, pipeline, _ = build_configs(options)
    engine = EbsynthEngine(native, pipeline)
    return engine.run(style, guides=native_guides(pairs))


def render_fuoum_job(job, progress):
    from reezsynth_config import (validate_render, quality_profile, validate_processing_settings,
                                  validate_weights, validate_synthesis_dimensions)
    options = validate_render(dict(quality_profile(job['quality']), **job.get('render_options', {})))
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
    frames = [read(path) for _, path in entries]
    styles = [read(path) for _, path in style_entries]
    original_shape = frames[0].shape
    if any(frame.shape != original_shape for frame in frames + styles):
        raise ValueError('Source and styled frames must have matching dimensions.')
    width, height = original_shape[1], original_shape[0]
    scale = min(1.0, processing['max_width'] / width) if processing['max_width'] else 1.0
    size = tuple(processing['processing_size'] or (max(1, round(width * scale)), max(1, round(height * scale))))
    frames = [cv2.resize(frame, size, interpolation=cv2.INTER_AREA) for frame in frames]
    styles = [cv2.resize(frame, size, interpolation=cv2.INTER_AREA) for frame in styles]
    if len(frames) > 1:
        if min(size) < 128:
            raise ValueError('RAFT video dimensions must both be at least 128 pixels.')
        validate_synthesis_dimensions(options['patchsize'], size)
    output = Path(job['output']).resolve()
    from reezsynth_preview_transport import PreviewPublisher
    publisher = PreviewPublisher(output)
    if len(frames) == 1:
        results = styles
    else:
        from ezsynth.config import MainConfig, ProjectConfig, PrecomputationConfig, DebugConfig
        from ezsynth.data import ProjectData
        from ezsynth.pipeline import SynthesisPipeline
        weights = validate_weights(job.get('guide_weights'))
        native, pipeline_config, blending = build_configs(options, weights, job.get('blend_options'))
        positions = [numbers.index(number) for number in key_numbers]
        expected = len(frames) - 1 + positions[-1] - positions[0]
        completed = 0
        lookup = {id(frame): number for frame, number in zip(frames, numbers)}
        origins = {id(style): number for style, number in zip(styles, key_numbers)}
        progress(10, 'Initializing FuouM synthesis')
        with tempfile.TemporaryDirectory(prefix='.fuoum-cache-', dir=output) as cache:
            config = MainConfig(
                project=ProjectConfig(content_dir=str(output), style_path=[path for _, path in style_entries],
                                      style_indices=positions, output_dir=str(output), cache_dir=cache),
                precomputation=PrecomputationConfig(flow_engine='RAFT', flow_model=options['flow_model'],
                                                     edge_method=options['edge_method']),
                pipeline=pipeline_config, blending=blending, ebsynth_params=native, debug=DebugConfig())
            data = ProjectData(config.project)
            # Data has already been validated/resized; bypass its directory scanning and implicit resize.
            data._content_frames, data._style_frames = frames, styles
            pipeline = SynthesisPipeline(config, data)
            original = pipeline.synthesis_engine.run
            def tracked(style, guides, **kwargs):
                nonlocal completed
                started = time.perf_counter()
                result = original(style, guides=native_guides(guides), **kwargs)
                completed += 1
                target = lookup.get(id(guides[1][1]))
                origin = origins.get(id(style))
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
            if completed != expected:
                raise RuntimeError(f'FuouM produced {completed} synthesis calls; expected {expected}.')
    if len(results) != len(frames):
        raise RuntimeError(f'FuouM returned {len(results)} frames; expected {len(frames)}.')
    for index, (number, image) in enumerate(zip(numbers, results)):
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
    (output / 'COMPLETE.txt').write_text(f'Engine: {FUOUM}\nSaved frames: {len(frames)}\n', encoding='utf-8')
    progress(99, 'Finishing FuouM synthesis')
