"""Associated-color representation for upcoming transparent FuouM renders.

Only nonopaque FuouM styles will use this path. Preserve the original keyframe
separately: an 8-bit synthesis representation cannot losslessly round-trip
    arbitrary straight RGB at very low alpha. The original unmasked keyframes
    remain authoritative for exact native-resolution output.
"""
import cv2
import numpy as np

VERSION = 'fuoum-associated-alpha-v1'


def validate_bgra(image):
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 4:
        raise ValueError('Transparent FuouM styles must be 8-bit BGRA arrays.')
    if not image.shape[0] or not image.shape[1]:
        raise ValueError('Transparent FuouM styles must have nonempty dimensions.')
    return image


def associated_style(image, size=None):
    """Remove invisible RGB from filtering/costs; resize associated color + alpha."""
    validate_bgra(image)
    value = image.astype(np.float32)
    value[..., :3] *= value[..., 3:4] / 255
    if size is not None:
        if not isinstance(size, (list, tuple)) or len(size) != 2 or any(type(n) is not int or n < 1 for n in size):
            raise ValueError('Alpha processing size must contain positive integer width and height.')
        value = cv2.resize(value, tuple(size), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(np.clip(np.rint(value), 0, 255).astype(np.uint8))


def straight_output(image):
    """Return straight BGRA PNG data; zero alpha has canonical invisible RGB 0."""
    validate_bgra(image)
    alpha = image[..., 3:4].astype(np.float32)
    color = np.minimum(image[..., :3].astype(np.float32), alpha)
    result = np.zeros_like(color)
    np.divide(color * 255, alpha, out=result, where=alpha > 0)
    return np.concatenate((np.clip(np.rint(result), 0, 255).astype(np.uint8), image[..., 3:4]), axis=2)


def clip_artwork(image, mask):
    """Limit associated color and opacity together; never add opaque source RGB."""
    validate_bgra(image)
    if not isinstance(mask, np.ndarray) or mask.dtype != np.uint8 or mask.shape != image.shape[:2]:
        raise ValueError('Artwork mask must be matching 8-bit grayscale.')
    return np.clip(np.rint(image.astype(np.float32) * (mask[..., None].astype(np.float32) / 255)), 0, 255).astype(np.uint8)


def composite_source(image, source, mask):
    validate_bgra(image)
    if not isinstance(source, np.ndarray) or source.dtype != np.uint8 or source.shape != (*image.shape[:2], 3):
        raise ValueError('Source compositing requires matching 8-bit BGR frames.')
    foreground = clip_artwork(image, mask)
    alpha = foreground[..., 3:4].astype(np.float32)
    color = np.minimum(foreground[..., :3].astype(np.float32), alpha)
    rgb = np.clip(np.rint(color + source.astype(np.float32) * (1 - alpha / 255)), 0, 255).astype(np.uint8)
    return np.concatenate((rgb, np.full_like(foreground[..., 3:4], 255)), axis=2)
