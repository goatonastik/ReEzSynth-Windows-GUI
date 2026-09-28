"""One-frame edge preview worker. No Qt; runs in the selected engine environment."""
import json
from pathlib import Path
import sys


def generate_preview(request, directory):
    import cv2
    import numpy as np
    from reezsynth_config import validate_render, validate_processing_settings
    from reezsynth_engines import FUOUM, prepare_runtime, activate_fuoum
    from reezsynth_edges import compute_edge_frames

    options = validate_render(request['options'])
    processing = validate_processing_settings(request)
    runtime = prepare_runtime(options, request.get('application', {}))
    if runtime['engine'] == FUOUM:
        activate_fuoum(runtime)

    def read(path, grayscale=False):
        image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8),
                            cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f'Cannot decode preview image: {path}')
        return image

    source = read(request['source'])
    h, w = source.shape[:2]
    scale = min(1., processing['max_width'] / w) if processing['max_width'] else 1.
    size = tuple(processing['processing_size'] or (max(1, round(w * scale)), max(1, round(h * scale))))
    if source.shape[1::-1] != size:
        source = cv2.resize(source, size, interpolation=cv2.INTER_AREA)
    detector_input = source
    if options['do_mask'] and options['pre_mask']:
        mask = (cv2.cvtColor(read(request['mask']), cv2.COLOR_BGR2GRAY)
                if runtime['engine'] == FUOUM else read(request['mask'], True))
        if mask.shape != (h, w):
            raise ValueError('Preview mask dimensions differ from the source frame.')
        mask = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
        if runtime['engine'] == FUOUM:
            detector_input = (source * (mask[..., None].astype(np.float32) / 255)).astype(np.uint8)
        else:
            detector_input = cv2.bitwise_and(source, source, mask=mask)
    if options['custom_edge_guides']:
        raise ValueError('Automatic edge preview is bypassed when custom edge guides are selected.')
    tuned = compute_edge_frames([detector_input], options['edge_method'], options, runtime['engine'])[0]
    default = compute_edge_frames([detector_input], options['edge_method'], engine=runtime['engine'])[0]
    if tuned.ndim == 2:
        tuned = cv2.cvtColor(tuned, cv2.COLOR_GRAY2BGR)
    if default.ndim == 2:
        default = cv2.cvtColor(default, cv2.COLOR_GRAY2BGR)
    overlay = cv2.addWeighted(source, .5, tuned, .5, 0)
    directory = Path(directory)
    for name, image in (('source', source), ('edges', tuned), ('defaults', default), ('overlay', overlay)):
        ok, data = cv2.imencode('.png', image)
        if not ok:
            raise ValueError(f'Could not encode {name} preview.')
        (directory / f'{name}.png').write_bytes(data.tobytes())
    # Publish readiness only after all images have been written.
    (directory / 'result.json').write_text(json.dumps(dict(size=size, original_size=[w, h])), encoding='utf-8')


if __name__ == '__main__':
    request_path = Path(sys.argv[1]).resolve()
    generate_preview(json.loads(request_path.read_text(encoding='utf-8')), request_path.parent)
