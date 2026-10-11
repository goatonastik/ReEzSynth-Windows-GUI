"""CPU-only reconstruction of RGB model edits under a fixed drawing alpha.

This is an explicit encoded-RGB matte model, not alpha inference or segmentation.
It cannot add coverage or guarantee the appearance of unprotected generated art.
"""
from dataclasses import dataclass

import numpy as np

from reezsynth_keyframe_protection import (
    AlphaPolicy, ProtectionReport, _mask, _rgba, compose_modified,
)


def _background(value):
    if (not isinstance(value, tuple) or len(value) != 3
            or any(type(v) is not int or not 0 <= v <= 255 for v in value)):
        raise ValueError("Choose an explicit RGB background with three byte values.")
    return np.array(value,dtype=np.uint32)


def _rgb(image, shape, label):
    if (not isinstance(image,np.ndarray) or image.dtype != np.uint8
            or image.shape != (*shape,3)):
        raise ValueError(f"{label} must be RGB uint8 at the original drawing dimensions.")
    return image


def _matte_rows(rows, background):
    alpha = rows[...,3:4].astype(np.uint32)
    colors = rows[...,:3].astype(np.uint32)
    return ((colors*alpha + background*(255-alpha) + 127)//255).astype(np.uint8)


def opaque_model_input(drawing, *, background):
    """Composite an explicit model intermediate; never mutate original RGBA."""
    drawing = _rgba(drawing,"Drawing")
    backdrop = _background(background)
    result = np.empty((*drawing.shape[:2],3),dtype=np.uint8)
    for top in range(0,drawing.shape[0],128):
        result[top:top+128] = _matte_rows(drawing[top:top+128],backdrop)
    return result


@dataclass(frozen=True)
class MatteReport:
    protection: ProtectionReport
    clipped_reconstruction_pixels: int
    translucent_edit_pixels: int


def compose_matted_output(drawing, generated_rgb, input_rgb, edit_mask,
                         protection_mask, *, background):
    """Reconstruct foreground color changes, then enforce exact RGBA protection.

    input_rgb is the exact quantized model-input matte, cropped to native size.
    It must match the drawing and explicit background. For visible editable
    pixels, raw foreground = original RGB + (generated RGB - input RGB)/alpha.
    Identity output therefore preserves even low-alpha foreground RGB exactly.
    Unrepresentable raw colors are clipped, counted once per eligible pixel,
    and then blended by edit coverage via compose_modified. Clipping is assessed
    before that final soft blend; the count is not a count of saturated outputs.
    Original alpha never changes. Hidden RGB and protected samples remain exact.
    This cannot recover model edits that require different coverage/transparency.
    """
    drawing = _rgba(drawing,"Drawing")
    shape = drawing.shape[:2]
    generated_rgb = _rgb(generated_rgb,shape,"Generated intermediate")
    input_rgb = _rgb(input_rgb,shape,"Frozen model input")
    edit_mask = _mask(edit_mask,shape,"Edit")
    protection_mask = _mask(protection_mask,shape,"Protection")
    backdrop = _background(background)
    candidate = drawing.copy()
    # Candidate colors are already reconstructed foreground; do not attenuate
    # their edit strength a second time using the drawing's alpha.
    candidate[...,3] = 255
    clipped = translucent = 0
    for top in range(0,shape[0],128):
        rows = drawing[top:top+128]
        baseline = input_rgb[top:top+128]
        if not np.array_equal(baseline,_matte_rows(rows,backdrop)):
            raise ValueError("Frozen model input does not match the drawing and background.")
        active = ((rows[...,3] > 0) & (edit_mask[top:top+128] > 0)
                  & (protection_mask[top:top+128] == 0))
        original = rows[active].astype(np.float64)
        delta = (generated_rgb[top:top+128][active].astype(np.float64)
                 - baseline[active].astype(np.float64))
        colors = original[:,:3] + delta * (255.0/original[:,3:4])
        clipped += int(np.any((colors < 0) | (colors > 255),axis=1).sum())
        translucent += int((original[:,3] < 255).sum())
        candidate_rows = candidate[top:top+128]
        candidate_rows[...,:3][active] = np.clip(np.floor(colors+0.5),0,255).astype(np.uint8)
    result, protection = compose_modified(
        drawing,candidate,edit_mask,protection_mask,alpha_policy=AlphaPolicy.PRESERVE,
    )
    return result,MatteReport(protection,clipped,translucent)
