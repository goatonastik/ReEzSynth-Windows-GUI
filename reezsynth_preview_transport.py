"""CPU-only live-preview transport, independent of Qt and the rendering engine."""
import json
import time
from pathlib import Path

PREVIEW_DIR = '.reezsynth-preview'
LEASE_SECONDS = 6
MAX_EDGE = 960


def preview_channels(job):
    """Key/direction pairs in queue order, including grouped propagation tails."""
    if job.get('type') == 'image_synthesis':
        return [('Image', 'Image')]
    numbers = [n for n, _ in job['frames']]
    keys = sorted(n for n, _ in job.get('styles', [[job['key'], job['style']]]))
    if len(numbers) == 1:
        return [(keys[0], 'Keyframe')]
    mode = job.get('blend_options', {}).get('only_mode', 'none')
    channels = set()
    if numbers[0] < keys[0]:
        channels.add((keys[0], 'Backward'))
    for index, (first, last) in enumerate(zip(keys, keys[1:])):
        if mode != 'reverse':
            channels.add((first, 'Forward'))
        # Upstream shifts the start of later reverse-only segments by one.
        shifted = mode == 'reverse' and (index > 0 or numbers[0] < keys[0])
        if mode != 'forward' and last - first > int(shifted):
            channels.add((last, 'Backward'))
    if keys[-1] < numbers[-1]:
        channels.add((keys[-1], 'Forward'))
    return [(key, direction) for key in keys for direction in ('Backward', 'Forward')
            if (key, direction) in channels]


def preview_filename(key, direction):
    if not (type(key) is int and key >= 0 or key == 'Image'):
        raise ValueError('Invalid preview key.')
    if direction not in ('Backward', 'Forward', 'Keyframe', 'Image'):
        raise ValueError('Invalid preview direction.')
    return f'{key}_{direction.lower()}.png'


class PreviewPublisher:
    """One small latest-frame file per subscribed direction, only while visible.

    The GUI refreshes a short lease while open. A hidden/closed/crashed GUI cannot
    leave workers continuously encoding previews. A preview failure never fails
    the render. The full-resolution synthesis array is returned untouched.
    """
    def __init__(self, output):
        self.root = Path(output) / PREVIEW_DIR
        self.request = self.root / 'request.json'
        self.seconds = 0.0
        self.warned = False

    def publish(self, key, direction, frame, pixels, stage='synthesis'):
        started = time.perf_counter()
        try:
            if not self.request.is_file():
                return None
            request = json.loads(self.request.read_text(encoding='utf-8'))
            if not 0 <= time.time() - request['updated'] <= LEASE_SECONDS:
                return None
            if [key, direction] not in request['channels']:
                return None
            import cv2
            import numpy as np
            if not isinstance(pixels, np.ndarray) or pixels.ndim != 3 or pixels.shape[2] not in (3, 4):
                raise ValueError('Invalid preview image returned by synthesis.')
            height, width = pixels.shape[:2]
            scale = min(1.0, MAX_EDGE / max(height, width))
            thumbnail = pixels
            if scale < 1:
                thumbnail = cv2.resize(pixels, (max(1, round(width * scale)), max(1, round(height * scale))),
                                       interpolation=cv2.INTER_AREA)
            if thumbnail.dtype != np.uint8:
                thumbnail = np.clip(thumbnail, 0, 255).astype(np.uint8)
            ok, encoded = cv2.imencode('.png', thumbnail, [cv2.IMWRITE_PNG_COMPRESSION, 1])
            if not ok:
                raise ValueError('Cannot encode preview image.')
            destination = self.root / preview_filename(key, direction)
            temporary = destination.with_suffix('.png.part')
            temporary.write_bytes(encoded.tobytes())
            temporary.replace(destination)
            return dict(key=key, direction=direction, frame=frame, path=str(destination), stage=stage)
        except FileNotFoundError:
            return None  # The window may have closed while the request was read.
        except Exception as exc:
            if not self.warned:
                print(f'[Preview] Capture unavailable: {exc}', flush=True)
                self.warned = True
            return None
        finally:
            self.seconds += time.perf_counter() - started
