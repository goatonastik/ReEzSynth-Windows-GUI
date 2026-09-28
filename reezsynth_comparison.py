"""Qt-free planning and static comparison-sheet rendering."""
import copy
import json
from pathlib import Path

from reezsynth_engines import FUOUM, file_sha256

COMPARISON_KINDS = {
    'flow': 'RAFT versus NeuFlow',
    'directions': 'One versus two estimated flow directions',
    'reconstruction': 'Reconstruction: LSQR / LSMR / disabled',
    'backend': 'Synthesis: CUDA versus experimental torch',
}
MAX_COMPARISON_FRAMES = 64


def comparison_plans(video, keys, start, end, kind, options, blend):
    from reezsynth_config import validate_render
    from reezsynth_video_plan import plan_grouped_video, validate_blend_options
    if kind not in COMPARISON_KINDS:
        raise ValueError('Unknown comparison kind.')
    options = validate_render(options)
    blend = validate_blend_options(blend)
    if options['engine'] != FUOUM:
        raise ValueError('These comparison templates require FuouM.')
    if type(start) is not int or type(end) is not int or not 2 <= end - start + 1 <= MAX_COMPARISON_FRAMES:
        raise ValueError('Select a consecutive range of 2 to 64 frames.')
    selected = [number for number in sorted(keys) if start <= number <= end]
    plan = plan_grouped_video(video, keys, dict(start=start, end=end, keyframes=selected), blend)
    selected_keys = [number for number, _ in plan['styles']]
    if len(selected_keys) == end - start + 1:
        raise ValueError('Every selected frame is a keyframe. Include a non-keyframe to compare synthesis.')
    if kind == 'reconstruction' and (len(selected_keys) < 2 or blend['only_mode'] != 'none'):
        raise ValueError('Reconstruction comparisons need at least two keyframes and normal blending in Blend / Flow.')
    variants = {
        'flow': [('RAFT', {'fuoum_flow_engine': 'RAFT'}, {}),
                 ('NeuFlow', {'fuoum_flow_engine': 'NeuFlow'}, {})],
        'directions': [('One estimated direction', {'fuoum_bidirectional_flow': False}, {}),
                       ('Both flow directions', {'fuoum_bidirectional_flow': True}, {})],
        'reconstruction': [('LSQR', {}, {'fuoum_poisson_solver': 'lsqr'}),
                           ('LSMR', {}, {'fuoum_poisson_solver': 'lsmr'}),
                           ('No reconstruction', {}, {'fuoum_poisson_solver': 'disabled'})],
        'backend': [('CUDA', {'fuoum_backend': 'cuda'}, {}),
                    ('Experimental torch', {'fuoum_backend': 'torch'}, {})],
    }[kind]
    result = []
    for index, (label, render_changes, blend_changes) in enumerate(variants, 1):
        selected_blend = validate_blend_options(dict(blend, **blend_changes))
        selected_plan = copy.deepcopy(plan)
        selected_plan['blend_options'] = selected_blend
        result.append(dict(label=label, folder=f'variant_{index:02d}', plan=selected_plan,
                           render_options=validate_render(dict(options, **render_changes))))
    return result


def sample_frames(numbers):
    numbers = list(numbers)
    if not numbers:
        raise ValueError('No comparison frames.')
    count = min(8, len(numbers))
    return [numbers[round(index * (len(numbers) - 1) / (count - 1))]
            for index in range(count)] if count > 1 else numbers


def remap_sheet_dependencies(job, replacements):
    """Recovery redirects partial variants to fresh outputs without editing originals."""
    result = copy.deepcopy(job)
    for variant in result['comparison_variants']:
        original = str(Path(variant['job']).resolve())
        if original in replacements:
            variant['job'] = str(replacements[original])
            variant['job_sha256'] = file_sha256(variant['job'])
    return result


def render_comparison_sheet(job, progress):
    import cv2
    import numpy as np
    from reezsynth_config import atomic_json
    from reezsynth_jobs import scan_images
    from reezsynth_sequence import completion_path

    output = Path(job['output']).resolve()
    variants = job.get('comparison_variants')
    if not isinstance(variants, list) or not 2 <= len(variants) <= 3:
        raise ValueError('A comparison sheet requires two or three variants.')
    entries = job.get('frames', [])
    numbers = [entry[0] for entry in entries]
    if (not numbers or any(type(number) is not int for number in numbers) or
            numbers != list(range(numbers[0], numbers[-1] + 1)) or len(numbers) > MAX_COMPARISON_FRAMES):
        raise ValueError('Invalid comparison source range.')
    sources = dict(entries)
    selected = sample_frames(numbers)
    columns = [{'label': 'Source', 'images': sources}]
    metadata = []
    for variant in variants:
        path = Path(variant['job']).resolve()
        if not path.is_relative_to(output.parent) or not path.is_file():
            raise ValueError('Comparison variant job is missing or outside this batch.')
        if file_sha256(path) != variant.get('job_sha256'):
            raise ValueError('Comparison variant job changed or is outside this batch.')
        rendered_job = json.loads(path.read_text(encoding='utf-8'))
        destination = Path(rendered_job['output']).resolve()
        if not destination.is_relative_to(output.parent) or destination == output:
            raise ValueError('Comparison variant output is outside this batch.')
        if not (destination / 'COMPLETE.txt').is_file():
            raise ValueError(f'Variant {variant["label"]} is incomplete. Finish or recover its render first.')
        if [entry[0] for entry in rendered_job.get('frames', [])] != numbers:
            raise ValueError('Comparison variants do not have the same frame range.')
        images, _ = scan_images(destination, source=True)
        if set(images) != set(numbers):
            raise ValueError(f'Variant {variant["label"]} has missing or unexpected output frames.')
        columns.append(dict(label=variant['label'], images=images))
        engine_manifest = json.loads((destination / 'engine_manifest.json').read_text(encoding='utf-8'))
        metadata.append(dict(label=variant['label'], job=str(path), job_sha256=variant['job_sha256'],
            output=str(destination), requested=rendered_job,
            effective_settings=engine_manifest['effective_settings']))

    width, height, caption, header = 256, 192, 28, 42
    canvas = np.full((header + len(selected) * (height + caption), len(columns) * width, 3), 35, np.uint8)
    for column, info in enumerate(columns):
        cv2.putText(canvas, info['label'], (column * width + 8, 25), cv2.FONT_HERSHEY_SIMPLEX, .5, (240, 240, 240), 1, cv2.LINE_AA)
    samples = []
    for row, number in enumerate(selected):
        y = header + row * (height + caption)
        sample = {'frame': number, 'images': []}
        for column, info in enumerate(columns):
            path = Path(info['images'][number])
            image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
            if image is None:
                raise ValueError(f'Cannot decode comparison image: {path}')
            if image.ndim == 2:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            if image.dtype != np.uint8 or image.shape[2] not in (3, 4):
                raise ValueError('Comparison images must be 8-bit RGB/RGBA.')
            if image.shape[2] == 4:
                yy, xx = np.indices(image.shape[:2])
                background = np.where((xx // 16 + yy // 16) % 2, 180, 230)[..., None]
                alpha = image[..., 3:4].astype(np.float32) / 255
                image = (image[..., :3] * alpha + background * (1 - alpha)).astype(np.uint8)
            scale = min(width / image.shape[1], height / image.shape[0])
            thumbnail = cv2.resize(image, (max(1, round(image.shape[1] * scale)), max(1, round(image.shape[0] * scale))), interpolation=cv2.INTER_AREA)
            x = column * width + (width - thumbnail.shape[1]) // 2
            top = y + (height - thumbnail.shape[0]) // 2
            canvas[top:top + thumbnail.shape[0], x:x + thumbnail.shape[1]] = thumbnail
            cv2.putText(canvas, f'Frame {number}', (column * width + 8, y + height + 19), cv2.FONT_HERSHEY_SIMPLEX, .45, (230, 230, 230), 1, cv2.LINE_AA)
            sample['images'].append(dict(label=info['label'], path=str(path), sha256=file_sha256(path), size=list(image.shape[1::-1])))
        samples.append(sample)
        progress(95 * (row + 1) / len(selected), 'Building static comparison sheet')
    ok, encoded = cv2.imencode('.png', canvas)
    if not ok:
        raise ValueError('Cannot encode comparison sheet.')
    temporary = output / 'contact_sheet.png.part'
    try:
        temporary.write_bytes(encoded.tobytes())
        temporary.replace(output / 'contact_sheet.png')
    finally:
        temporary.unlink(missing_ok=True)
    atomic_json(output / 'comparison_manifest.json', dict(version=1, kind=job['comparison_kind'],
        range=[numbers[0], numbers[-1]], sampled_frames=selected, samples=samples, variants=metadata,
        display='Static aspect-preserving thumbnails; RGBA is shown on a checkerboard.',
        timing='Not a speed benchmark. Cache reuse and model initialization can differ.',
        sheet='contact_sheet.png', sheet_sha256=file_sha256(output / 'contact_sheet.png')))
    completion_path(output).write_text('Static comparison sheet and manifest complete.\n', encoding='utf-8')
