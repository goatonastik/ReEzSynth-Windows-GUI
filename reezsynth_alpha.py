"""Explicit transparent-style boundaries; RGB jobs retain their existing path."""
from pathlib import Path

import cv2
import numpy as np


def read_style(path):
    """Select BGRA only for actual nonopaque alpha, before any resizing.

    RGB, grayscale and opaque RGBA retain the old IMREAD_COLOR normalization.
    Transparent native synthesis is byte based: reject, never truncate, 16-bit
    alpha payloads. No premultiplication or hidden-color canonicalization.
    """
    data = np.frombuffer(Path(path).read_bytes(), np.uint8)
    raw = cv2.imdecode(data, cv2.IMREAD_UNCHANGED) if data.size else None
    if raw is None:
        raise ValueError(f'Cannot decode image: {path}')
    if raw.ndim == 3 and raw.shape[2] == 4:
        opaque = np.iinfo(raw.dtype).max
        if np.any(raw[..., 3] != opaque):
            if raw.dtype != np.uint8:
                raise ValueError(f'Transparent keyframes must be 8-bit RGBA PNGs: {path}')
            return raw
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def as_bgra(image):
    if image.ndim != 3 or image.shape[2] not in (3, 4) or image.dtype != np.uint8:
        raise ValueError('Style/output images must be 8-bit BGR or BGRA.')
    if image.shape[2] == 4:
        return image
    from reezsynth_sequence import copy_number
    return copy_number(cv2.cvtColor(image, cv2.COLOR_BGR2BGRA), image)


def reject_fuoum_alpha(paths):
    for path in paths:
        if read_style(path).shape[2] == 4:
            raise ValueError('FuouM transparent RGBA keyframes are not supported by the pinned '
                             'video/reconstruction pipeline. Select Trentonom0r3/Ezsynth '
                             '(Legacy) to preserve transparency. Alpha will not be flattened.')


def keyframe_guides(style, source, edge, weights):
    """Identity-target guides: 1 edge + 3 source + 3 position + 3 warped RGB.

    Alpha is a style/output channel, not an added guide or a mask. All guide
    weights keep their existing group totals and RGB channel normalization.
    """
    h, w = source.shape[:2]
    x, y = np.meshgrid(np.linspace(0, 255, w), np.linspace(0, 255, h))
    position = np.stack((x, y, np.zeros_like(x)), axis=-1).astype(np.uint8)
    rgb = np.ascontiguousarray(style[..., :3])
    return [(edge, edge, weights['edg_wgt']), (source, source, weights['img_wgt']),
            (position, position, weights['pos_wgt']), (rgb, rgb, weights['wrp_wgt'])]


def synthesize_keyframe(style, source, edge, eb, weights):
    result, error = eb.run(style, guides=keyframe_guides(style, source, edge, weights))
    if (not isinstance(result, np.ndarray) or result.shape != (*source.shape[:2], 4)
            or not np.isfinite(result).all()):
        raise RuntimeError('Invalid RGBA keyframe synthesis output.')
    return result, error


def selected_alpha(forward, backward, mask):
    """Carry synthesized opacity from the same error-selected pass as RGB.

    Opacity is not a Lab component and is not histogram matched. Reconstruction
    may correct RGB gradients, but must not erase or manufacture opacity.
    """
    if mask.ndim == 3:
        mask = mask[..., 0]
    return np.where(mask > 0, backward[..., 3], forward[..., 3])
