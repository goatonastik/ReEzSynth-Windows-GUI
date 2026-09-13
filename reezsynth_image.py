"""Image-synthesis schema and adapter; no engine or Qt imports at module load."""
import math
from pathlib import Path

IMAGE_DEFAULTS = dict(style='', source='', target='', source_weight=6.0,
                      key_weight=1.0, guides=[], folder='image_synthesis', modulation='')
SYNTHESIS_FIELDS = ('uniformity', 'patchsize', 'pyramidlevels', 'searchvoteiters',
                    'patchmatchiters', 'extrapass3x3')


def validate_image_settings(data=None):
    data = {} if data is None else data
    if not isinstance(data, dict) or set(data) - set(IMAGE_DEFAULTS):
        raise ValueError('Invalid image synthesis settings.')
    result = dict(IMAGE_DEFAULTS, **data)
    for name in ('style', 'source', 'target', 'folder', 'modulation'):
        if not isinstance(result[name], str):
            raise ValueError(f'Image {name} must be text.')
        result[name] = result[name].strip()
    def weight(value, minimum=0):
        if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= 10000:
            raise ValueError(f'Image guide weights must be finite and between {minimum} and 10000.')
        return value
    weight(result['source_weight'])
    weight(result['key_weight'], .001)
    if not isinstance(result['guides'], list) or len(result['guides']) > 23:
        raise ValueError('Image synthesis supports at most 24 guide pairs including the primary pair.')
    guides = []
    for item in result['guides']:
        if (not isinstance(item, dict) or not {'source', 'target', 'weight'} <= set(item)
                or set(item) - {'source', 'target', 'weight', 'modulation'}):
            raise ValueError('Each guide needs source, target and weight.')
        if not isinstance(item['source'], str) or not isinstance(item['target'], str):
            raise ValueError('Guide paths must be text.')
        guides.append(dict(source=item['source'].strip(), target=item['target'].strip(), weight=weight(item['weight'])))
        if 'modulation' in item:
            if not isinstance(item['modulation'], str):
                raise ValueError('Guide modulation path must be text.')
            guides[-1]['modulation'] = item['modulation'].strip()
    result['guides'] = guides
    return result


def image_job_settings(data):
    result = validate_image_settings(data)
    for name in ('style', 'source', 'target'):
        if not result[name] or not Path(result[name]).expanduser().is_file():
            raise ValueError(f'Select an existing {name} image.')
        result[name] = str(Path(result[name]).expanduser().resolve())
    for guide in result['guides']:
        for name in ('source', 'target'):
            if not guide[name] or not Path(guide[name]).expanduser().is_file():
                raise ValueError(f'Select an existing additional guide {name} image.')
            guide[name] = str(Path(guide[name]).expanduser().resolve())
    for guide in [result, *result['guides']]:
        if guide.get('modulation'):
            path = Path(guide['modulation']).expanduser()
            if not path.is_file():
                raise ValueError('Select an existing modulation image or leave it blank.')
            guide['modulation'] = str(path.resolve())
    return result


def render_image_job(job, progress):
    import cv2
    import numpy as np
    from reezsynth_config import validate_render, validate_processing_settings, validate_synthesis_dimensions

    settings = image_job_settings(job['image_synthesis'])
    if job.get('quality') not in ('Standard', 'Preview', 'Highest'):
        raise ValueError('Invalid image quality or processing size.')
    processing = validate_processing_settings(job)
    from reezsynth_config import quality_profile
    options = dict(quality_profile(job['quality']))
    options.update(job.get('render_options', {}))
    options = validate_render(options)
    from reezsynth_modulation import require_backend
    require_backend(options, any(g.get('modulation') for g in [settings, *settings['guides']]))
    def read(path, style=False):
        image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None or image.dtype != np.uint8 or image.ndim not in (2, 3):
            raise ValueError(f'Image must decode as an 8-bit image: {path}')
        if style and image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif style and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return image
    def channels(image):
        return 1 if image.ndim == 2 else image.shape[2]
    style = read(settings['style'], style=True)
    pairs = [(read(settings['source']), read(settings['target']), settings['source_weight'])]
    pairs.extend((read(g['source']), read(g['target']), g['weight']) for g in settings['guides'])
    target_shape = pairs[0][1].shape[:2]
    for source, target, _ in pairs:
        if source.shape[:2] != style.shape[:2]:
            raise ValueError('All source guides must match the styled image dimensions.')
        if target.shape[:2] != target_shape:
            raise ValueError('All target guides must have matching dimensions.')
        if channels(source) != channels(target):
            raise ValueError('Each source/target guide pair must have matching channel counts.')
    if sum(channels(pair[0]) for pair in pairs) > 24:
        raise ValueError('The native engine supports at most 24 guide channels in total.')
    original_style_shape = style.shape[:2]
    def resize(image):
        requested = processing['processing_size']
        if requested is not None:
            return cv2.resize(image, tuple(requested), interpolation=cv2.INTER_AREA)
        limit = processing['max_width']
        if limit and image.shape[1] > limit:
            height = max(1, round(image.shape[0] * limit / image.shape[1]))
            return cv2.resize(image, (limit, height), interpolation=cv2.INTER_AREA)
        return image
    style = resize(style)
    pairs = [(resize(a), resize(b), weight / settings['key_weight']) for a, b, weight in pairs]
    from reezsynth_modulation import read_map, pack_maps, legacy_modulation, channel_layout, map_info, write_manifest
    paths = [settings['modulation'], *(g.get('modulation', '') for g in settings['guides'])]
    maps = [read_map(path, target_shape, pairs[0][1].shape[1::-1]) if path else None for path in paths]
    modulated = any(value is not None for value in maps)
    validate_synthesis_dimensions(options['patchsize'], style.shape[1::-1], pairs[0][1].shape[1::-1])
    progress(10, 'Initializing image synthesis')
    backend = options['ebsynth_backend']
    progress(15, 'Synthesizing image')
    from reezsynth_engines import FUOUM
    if options['engine'] == FUOUM:
        from reezsynth_fuoum import synthesize_image
        result, error = synthesize_image(style, pairs, options, output=job['output'],
                                         modulation=pack_maps(pairs, maps))
    else:
        from ezsynth.aux_classes import RunConfig
        from ezsynth.main_ez import ImageSynthBase
        cfg = RunConfig(**{name: options[name] for name in SYNTHESIS_FIELDS}, img_wgt=pairs[0][2])
        runner = ImageSynthBase(style_img=style, src_img=pairs[0][0], tgt_img=pairs[0][1], cfg=cfg)
        runner.eb.backend = runner.eb.backends[backend]
        # Always pass a fresh list: upstream appends the primary pair to this list.
        from reezsynth_iterations import legacy_schedule, ScheduleRecorder
        # Legacy appends the primary guide after the additional guides.
        packed = pack_maps([*pairs[1:], pairs[0]], [*maps[1:], maps[0]])
        with legacy_schedule(runner.eb, options, ScheduleRecorder(job['output'])), \
             legacy_modulation(runner.eb, packed):
            result, error = runner.run(guides=list(pairs[1:]))
    expected_shape = (*pairs[0][1].shape[:2], 3)
    if not isinstance(result, np.ndarray) or result.shape != expected_shape or not np.isfinite(result).all():
        raise RuntimeError('Image synthesis returned an invalid output image.')
    if not isinstance(error, np.ndarray) or error.shape != expected_shape[:2] or error.dtype.kind not in 'uif' or not np.isfinite(error).all():
        raise RuntimeError('Image synthesis returned an invalid numerical error map.')
    from reezsynth_preview_transport import PreviewPublisher
    preview = PreviewPublisher(job['output']).publish('Image', 'Image', None, result, stage='final')
    if preview is not None:
        progress(90, 'Saving image and error map', preview=preview)
    else:
        progress(90, 'Saving image and error map')
    output = Path(job['output'])
    ok, encoded = cv2.imencode('.png', np.clip(result, 0, 255).astype(np.uint8))
    if not ok:
        raise RuntimeError('Could not encode synthesized image.')
    temporary = output / 'image.png.part'
    temporary.write_bytes(encoded.tobytes())
    temporary.replace(output / 'image.png')
    temporary = output / 'error.npy.part'
    with temporary.open('wb') as stream:
        np.save(stream, error, allow_pickle=False)
    temporary.replace(output / 'error.npy')
    from reezsynth_config import atomic_json
    if modulated:
        order = list(range(len(pairs))) if options['engine'] == FUOUM else [*range(1, len(pairs)), 0]
        labels = ['Primary guide', *(f'Additional guide {i + 1}' for i in range(len(pairs) - 1))]
        write_manifest(job['output'], mode='per_image_guide',
            maps=[dict(guide=labels[i], **map_info(paths[i], maps[i])) for i in range(len(paths)) if paths[i]],
            layouts=[channel_layout([pairs[i] for i in order], [labels[i] for i in order],
                [j for j, i in enumerate(order) if maps[i] is not None])])
    atomic_json(output / 'image_manifest.json', dict(version=1, image='image.png', error='error.npy',
        error_dtype=str(error.dtype), output_shape=list(result.shape),
        original_style_shape=list(original_style_shape), original_target_shape=list(target_shape),
        guide_channels=[channels(pair[0]) for pair in pairs], backend=backend, engine=options['engine']))
    (output / 'COMPLETE.txt').write_text('Image synthesis complete: image.png, error.npy, image_manifest.json\n', encoding='utf-8')
    progress(99, 'Finishing image synthesis')
