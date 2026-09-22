"""Deterministic diagnostic inputs generated at run time; no bundled media required."""
from pathlib import Path

import cv2
import numpy as np


def frame(size, index, total=11):
    """Return a textured BGR frame with predictable motion and occlusion."""
    width, height = map(int, size)
    if width < 8 or height < 8 or total < 2:
        raise ValueError('Synthetic diagnostic frames require at least 8x8 pixels and two positions.')
    yy, xx = np.indices((height, width), dtype=np.int32)
    image = np.stack((
        (3 * xx + 2 * yy + 11 * index) % 256,
        (xx + 5 * yy + 17 * index) % 256,
        (7 * xx + yy + 23 * index) % 256,
    ), axis=-1).astype(np.uint8)
    position = index / (total - 1)
    center = (round(width * (.18 + .64 * position)), round(height * (.30 + .35 * position)))
    radius = max(3, min(width, height) // 9)
    cv2.circle(image, center, radius, (235, 70, 35), -1, lineType=cv2.LINE_AA)
    left = round(width * (.68 - .32 * position))
    top = round(height * (.12 + .28 * position))
    cv2.rectangle(image, (left, top),
                  (min(width - 1, left + max(4, width // 7)),
                   min(height - 1, top + max(4, height // 5))),
                  (30, 220, 170), -1)
    cv2.line(image, (0, (index * 13) % height),
             (width - 1, (height // 2 + index * 7) % height), (245, 245, 245), 2)
    return image


def style(image, variant=0, flat=False):
    """Create an obviously stylized derivative without external artwork."""
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('Synthetic diagnostic styles require a three-channel BGR image.')
    if flat:
        result = np.empty_like(image)
        result[:] = (40, 100, 170)
        return result
    poster = ((image.astype(np.uint16) // 48) * 48 + 24).clip(0, 255).astype(np.uint8)
    channels = list(cv2.split(poster))
    channels = channels[variant % 3:] + channels[:variant % 3]
    result = cv2.merge(channels)
    edges = cv2.Canny(image, 70, 150)
    result[edges != 0] = (20, 20, 20)
    return result


def mask(size, index, total=11):
    width, height = map(int, size)
    result = np.zeros((height, width), np.uint8)
    position = index / max(1, total - 1)
    center = (round(width * (.25 + .5 * position)), round(height * (.5 + .12 * np.sin(index))))
    axes = (max(3, width // 5), max(3, height // 3))
    cv2.ellipse(result, center, axes, 0, 0, 360, 255, -1, lineType=cv2.LINE_AA)
    return result


def write(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise RuntimeError(f'Could not write synthetic diagnostic input: {path}')
    return str(path)


def image_case(directory, name, guide_count=0, source_size=(256, 256), target_size=(384, 128)):
    """Create one retargeting case and return paths in the image-job schema."""
    directory = Path(directory)
    source = frame(source_size, 2, 7)
    target = frame(target_size, 4, 7)
    settings = {
        'style': write(directory / f'{name}_style.png', style(source, guide_count + 1)),
        'source': write(directory / f'{name}_source.png', source),
        'target': write(directory / f'{name}_target.png', target),
        'guides': [],
    }
    for index in range(guide_count):
        source_guide = frame(source_size, index + 1, guide_count + 2)
        target_guide = frame(target_size, index + 2, guide_count + 3)
        if index % 2:
            source_guide = cv2.cvtColor(source_guide, cv2.COLOR_BGR2GRAY)
            target_guide = cv2.cvtColor(target_guide, cv2.COLOR_BGR2GRAY)
        settings['guides'].append({
            'source': write(directory / f'{name}_guide_{index}_source.png', source_guide),
            'target': write(directory / f'{name}_guide_{index}_target.png', target_guide),
            'weight': 1.0,
        })
    return settings
