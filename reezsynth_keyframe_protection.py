"""Deterministic native-canvas protection for Modify Existing Keyframe.

No inference, file writes, Qt dependencies, or synthesis-engine changes. Arrays
are straight-alpha RGBA uint8; masks are single-channel uint8 at native size.
Protection is binary (any nonzero sample protects); edit coverage may be soft.
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np


class EditIntent(str, Enum):
    REFINE_STROKES = "refine_strokes"
    REGION_DETAIL = "region_detail"
    CUSTOM = "custom"


class AlphaPolicy(str, Enum):
    PRESERVE = "preserve_drawing_alpha"
    EDIT = "edit_alpha_in_selected_region"


def _rgba(value, label):
    if (not isinstance(value, np.ndarray) or value.dtype != np.uint8
            or value.ndim != 3 or value.shape[2] != 4
            or min(value.shape[:2]) < 1):
        raise ValueError(f"{label} must be a nonempty native-size RGBA uint8 image.")
    return value


def _mask(value, shape, label):
    if (not isinstance(value, np.ndarray) or value.dtype != np.uint8
            or value.ndim != 2 or value.shape != shape):
        raise ValueError(f"{label} must be a grayscale uint8 mask at native dimensions.")
    return value


def propose_dark_strokes(drawing, *, maximum_channel=48):
    """Propose visible dark pixels, not a semantic contour/face detector.

    Fully transparent hidden RGB never becomes linework. Color accents are not
    automatically protected: the caller must show this proposal for correction.
    """
    drawing = _rgba(drawing, "Drawing")
    if type(maximum_channel) is not int or not 0 <= maximum_channel <= 255:
        raise ValueError("Dark-stroke threshold must be an integer from 0 to 255.")
    visible = drawing[..., 3] > 0
    dark = drawing[..., :3].max(axis=2) <= maximum_channel
    return (visible & dark).astype(np.uint8) * 255


def protection_band(mask, radius):
    """Expand an explicit mask by a square radius in ORIGINAL pixels.

    This is Chebyshev distance, not a circular/Euclidean band. Radius is chosen
    by the caller; no universal contour-width default is imposed.
    """
    if not isinstance(mask, np.ndarray) or mask.ndim != 2 or not mask.size:
        raise ValueError("Protection requires a nonempty grayscale mask.")
    _mask(mask, mask.shape, "Protection")
    if type(radius) is not int or not 0 <= radius <= 64:
        raise ValueError("Protection radius must be an integer from 0 to 64 pixels.")
    binary = (mask > 0).astype(np.uint8) * 255
    # Separable dilation by doubling offsets. Each pass expands the already
    # contiguous interval, requiring O(pixels * log(radius)) rather than a
    # generic square rank filter's per-pixel kernel scan.
    for axis in (0, 1):
        remaining, step = radius, 1
        while remaining:
            offset = min(step, remaining)
            if offset < binary.shape[axis]:
                lower = [slice(None), slice(None)]
                upper = [slice(None), slice(None)]
                lower[axis], upper[axis] = slice(None, -offset), slice(offset, None)
                lower, upper = tuple(lower), tuple(upper)
                expanded = binary.copy()
                np.maximum(expanded[lower], binary[upper], out=expanded[lower])
                np.maximum(expanded[upper], binary[lower], out=expanded[upper])
                binary = expanded
            remaining -= offset
            step *= 2
    return binary


@dataclass(frozen=True)
class ProtectionReport:
    width: int
    height: int
    editable_pixels: int
    protected_pixels: int
    changed_pixels: int
    alpha_changed_pixels: int
    protected_mismatches: int


def compose_modified(drawing, candidate, edit_mask, protection_mask, *, alpha_policy):
    """Return an independent RGBA result and static preservation report.

    All pixels outside edit coverage or within protection remain byte-exact,
    including invisible RGB. PRESERVE keeps original alpha and hidden RGB;
    candidate alpha attenuates its color contribution. EDIT interpolates in
    premultiplied-alpha space using encoded RGB values (not linear-light RGB).
    Under EDIT, fully editable samples take candidate RGBA exactly, including hidden RGB.
    This guarantees supplied-mask preservation, not unprotected geometry quality.
    """
    drawing = _rgba(drawing, "Drawing")
    candidate = _rgba(candidate, "Candidate")
    if candidate.shape != drawing.shape:
        raise ValueError("Candidate must match native drawing dimensions; resizing is not allowed.")
    shape = drawing.shape[:2]
    edit_mask = _mask(edit_mask, shape, "Edit")
    protection_mask = _mask(protection_mask, shape, "Protection")
    try:
        policy = AlphaPolicy(alpha_policy)
    except (ValueError, TypeError) as exc:
        raise ValueError("Choose a supported alpha policy explicitly.") from exc
    protected = (protection_mask > 0) | (edit_mask == 0)
    active = ~protected
    result = drawing.copy()
    # Float intermediates cover selected pixels (the whole canvas if selected).
    before = drawing[active].astype(np.float64)
    after = candidate[active].astype(np.float64)
    weight = edit_mask[active, None].astype(np.float64) / 255.0
    if policy == AlphaPolicy.PRESERVE:
        amount = weight * after[:, 3:4] / 255.0
        colors = before[:, :3] * (1 - amount) + after[:, :3] * amount
        colors[before[:, 3] == 0] = before[before[:, 3] == 0, :3]
        composed = before.copy()
        composed[:, :3] = colors
    else:
        alpha = before[:, 3:4] * (1 - weight) + after[:, 3:4] * weight
        premult = (before[:, :3] * before[:, 3:4] * (1 - weight)
                   + after[:, :3] * after[:, 3:4] * weight)
        colors = np.divide(premult, alpha, out=before[:, :3].copy(), where=alpha > 0)
        composed = np.concatenate((colors, alpha), axis=1)
        full = weight[:, 0] == 1
        composed[full] = after[full]
    result[active] = np.clip(np.floor(composed + 0.5), 0, 255).astype(np.uint8)
    changed = np.any(result != drawing, axis=2)
    report = ProtectionReport(
        width=shape[1], height=shape[0],
        editable_pixels=int(active.sum()), protected_pixels=int(protected.sum()),
        changed_pixels=int(changed.sum()),
        alpha_changed_pixels=int((result[..., 3] != drawing[..., 3]).sum()),
        protected_mismatches=int((changed & protected).sum()),
    )
    return result, report


@dataclass(frozen=True)
class NativeCanvas:
    """Right/bottom padding plan for a verified adapter's VAE stride."""

    width: int
    height: int
    stride: int

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in (self.width, self.height, self.stride)):
            raise ValueError("Native canvas dimensions and stride must be positive integers.")
        if self.stride > 128:
            raise ValueError("Unsupported VAE stride.")

    @property
    def padded_size(self):
        return (((self.width + self.stride - 1) // self.stride) * self.stride,
                ((self.height + self.stride - 1) // self.stride) * self.stride)

    def pad(self, image):
        image = _rgba(image, "Input")
        if image.shape[:2] != (self.height, self.width):
            raise ValueError("Input does not match the native canvas.")
        width, height = self.padded_size
        # Replicate the edge into padding; original pixels stay at the same indices.
        return np.pad(image, ((0, height - self.height), (0, width - self.width), (0, 0)),
                      mode="edge")

    def crop(self, image):
        image = _rgba(image, "Output")
        width, height = self.padded_size
        if image.shape[:2] != (height, width):
            raise ValueError("Output does not match the expected padded canvas.")
        return image[:self.height, :self.width].copy()
