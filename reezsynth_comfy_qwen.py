"""Offline, experimental Qwen Edit 2511 workflow planning.

No network, model loading, file writes, or UI actions. This recipe is not a
quality-validated generation feature. RGB output is an opaque model intermediate,
not an approved RGBA candidate. Original RGBA/masks remain separate snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import hashlib
import json
import math
import uuid

import numpy as np
from PIL import Image

from reezsynth_keyframe_protection import (
    AlphaPolicy, EditIntent, NativeCanvas, protection_band,
)
from reezsynth_keyframe_matte import opaque_model_input


PROFILE = "qwen-edit-2511-native-reference-experimental-v1"
MAX_PIXELS = 16 * 1024 * 1024
VISION_NOTICE = (
    "The vision encoder resizes an internal reference to approximately 147,456 "
    "pixels total (384 squared), keeping its aspect ratio. The spatial reference and "
    "output keep native pixels, with right/bottom padding to a 16-pixel grid."
)
MODELS = {
    "diffusion": "qwen_image_edit_2511_fp8mixed.safetensors",
    "encoder": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
    "vae": "qwen_image_vae.safetensors",
}
_INTENT = {
    EditIntent.REFINE_STROKES: "Refine the supplied drawing's strokes while preserving its geometry and intentional color accents. ",
    EditIntent.REGION_DETAIL: "Add the requested detail or shading within the editable region while preserving the drawing's geometry. ",
    EditIntent.CUSTOM: "",
}


@dataclass(frozen=True)
class QwenSettings:
    mode: str
    prompt: str
    seed: int
    steps: int
    guidance: float
    denoise: float
    intent: EditIntent | None = None
    alpha_policy: AlphaPolicy | None = None
    background: tuple[int, int, int] | None = None
    protection_radius: int = 0
    allow_vision_preprocessing: bool = False


@dataclass(frozen=True)
class QwenPlan:
    """Immutable bytes; callers receive fresh mappings, never a mutable graph."""
    request_bytes: bytes
    snapshots: tuple[tuple[str, bytes], ...]
    uploads: tuple[tuple[str, str], ...]  # snapshot name, expected server basename

    def request(self):
        return json.loads(self.request_bytes)


def _png(array):
    output = BytesIO()
    Image.fromarray(array).save(output, format="PNG")
    return output.getvalue()


def _rgba(image, label):
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
            or image.ndim != 3 or image.shape[2] != 4 or min(image.shape[:2]) < 1):
        raise ValueError(f"{label} must be native-size RGBA uint8 pixels.")
    if image.shape[0] * image.shape[1] > MAX_PIXELS:
        raise ValueError("Image exceeds this experimental adapter's pixel limit; no resizing was performed.")


def _validate(settings):
    if not isinstance(settings, QwenSettings) or settings.mode not in {"generate", "modify"}:
        raise ValueError("Choose Generate or Modify explicitly.")
    if (not isinstance(settings.prompt, str) or not settings.prompt.strip()
            or len(settings.prompt) > 8000):
        raise ValueError("Supply an edit/style instruction of at most 8000 characters.")
    if type(settings.seed) is not int or not 0 <= settings.seed <= 0xffffffffffffffff:
        raise ValueError("Seed must be an unsigned 64-bit integer.")
    if type(settings.steps) is not int or not 1 <= settings.steps <= 100:
        raise ValueError("Experimental sampling steps must be between 1 and 100.")
    for value, low, high, name in ((settings.guidance, 1, 10, "Guidance"),
                                  (settings.denoise, 0.01, 1, "Denoise")):
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name} is outside the experimental adapter range.")
    if settings.allow_vision_preprocessing is not True:
        raise ValueError(VISION_NOTICE + " Acknowledge this before creating the workflow.")
    if type(settings.protection_radius) is not int or not 0 <= settings.protection_radius <= 64:
        raise ValueError("Protection radius must be from 0 to 64 native pixels.")
    if settings.mode == "modify":
        if not isinstance(settings.intent, EditIntent):
            raise ValueError("Choose an explicit Modify intention.")
        if settings.alpha_policy != AlphaPolicy.PRESERVE:
            raise ValueError("This RGB adapter only supports Preserve drawing alpha; it cannot generate alpha.")
        if (not isinstance(settings.background, tuple) or len(settings.background) != 3
                or any(type(v) is not int or not 0 <= v <= 255 for v in settings.background)):
            raise ValueError("Choose an explicit RGB background for the model intermediate.")
    elif (settings.intent is not None or settings.alpha_policy is not None
          or settings.background is not None or settings.protection_radius != 0
          or settings.denoise != 1):
        raise ValueError("Generate uses the opaque source, full denoise, and no drawing-preservation options.")


def plan_qwen(settings, source, *, drawing=None, edit_mask=None, protection_mask=None):
    """Freeze native inputs and a built-in-node graph, without any submission.

    No style-reference/ControlNet/alpha-generation support is claimed. In Modify,
    noise masking is only coarse latent guidance; later deterministic RGBA
    enforcement and matte handling are required before candidate publication.
    """
    _validate(settings)
    _rgba(source, "Source")
    canvas = NativeCanvas(source.shape[1], source.shape[0], 16)
    width, height = canvas.padded_size
    if width * height > MAX_PIXELS:
        raise ValueError("Padded canvas exceeds the experimental pixel limit; no resizing was performed.")
    snapshots = {"source.png": _png(source)}
    if settings.mode == "modify":
        _rgba(drawing, "Drawing")
        if drawing.shape != source.shape:
            raise ValueError("Drawing and source must have the same native dimensions.")
        for mask, label in ((edit_mask, "Edit"), (protection_mask, "Protection")):
            if (not isinstance(mask, np.ndarray) or mask.dtype != np.uint8
                    or mask.ndim != 2 or mask.shape != source.shape[:2]):
                raise ValueError(f"{label} mask must be grayscale uint8 at native dimensions.")
        protected = protection_band(protection_mask, settings.protection_radius)
        effective = np.where((protected == 0) & (drawing[...,3] > 0), edit_mask, 0).astype(np.uint8)
        if not np.any(effective):
            raise ValueError("No visible editable pixels remain; generation is unnecessary.")
        # Explicit opaque intermediate, never a replacement for original RGBA.
        rgb = opaque_model_input(drawing,background=settings.background)
        snapshots.update({"drawing.png": _png(drawing), "edit.png": _png(edit_mask),
                          "protection.png": _png(protection_mask)})
        padded_mask = np.pad(effective, ((0,height-canvas.height),(0,width-canvas.width)))
        # RGB avoids the backend video decoder's grayscale colorspace conversion.
        snapshots["noise_mask.png"] = _png(np.repeat(padded_mask[...,None],3,axis=2))
        instruction = _INTENT[settings.intent] + settings.prompt.strip()
    else:
        if any(v is not None for v in (drawing, edit_mask, protection_mask)):
            raise ValueError("Generate must not silently apply drawing restoration or masks.")
        if np.any(source[...,3] != 255):
            raise ValueError("This Generate experiment requires an opaque source frame.")
        rgb = source[..., :3].copy()
        instruction = "Create a styled keyframe from the source while preserving its framing and structure. " + settings.prompt.strip()
    opaque = np.concatenate((rgb, np.full((*rgb.shape[:2],1),255,dtype=np.uint8)),axis=2)
    snapshots["inference.png"] = _png(canvas.pad(opaque)[...,:3])
    identifier = uuid.uuid4().hex
    uploads = {name:f"reezsynth_{identifier}_{name}" for name in ("inference.png", "noise_mask.png") if name in snapshots}
    graph = {
        "1": {"class_type":"UNETLoader", "inputs":{"unet_name":MODELS["diffusion"],"weight_dtype":"default"}},
        "2": {"class_type":"CLIPLoader", "inputs":{"clip_name":MODELS["encoder"],"type":"qwen_image","device":"default"}},
        "3": {"class_type":"VAELoader", "inputs":{"vae_name":MODELS["vae"]}},
        "4": {"class_type":"LoadImage", "inputs":{"image":uploads["inference.png"]}},
        "5": {"class_type":"VAEEncode", "inputs":{"pixels":["4",0],"vae":["3",0]}},
        "6": {"class_type":"TextEncodeQwenImageEditPlus", "inputs":{"clip":["2",0],"prompt":instruction,"image1":["4",0]}},
        "7": {"class_type":"TextEncodeQwenImageEditPlus", "inputs":{"clip":["2",0],"prompt":" ","image1":["4",0]}},
        "8": {"class_type":"ReferenceLatent", "inputs":{"conditioning":["6",0],"latent":["5",0]}},
        "9": {"class_type":"ReferenceLatent", "inputs":{"conditioning":["7",0],"latent":["5",0]}},
        "10": {"class_type":"ModelSamplingAuraFlow", "inputs":{"model":["1",0],"shift":3.1}},
        "11": {"class_type":"CFGNorm", "inputs":{"model":["10",0],"strength":1.0,"pre_cfg":False}},
        "14": {"class_type":"KSampler", "inputs":{"model":["11",0],"seed":settings.seed,"steps":settings.steps,
               "cfg":settings.guidance,"sampler_name":"euler","scheduler":"simple","positive":["8",0],
               "negative":["9",0],"latent_image":["5",0],"denoise":settings.denoise}},
        "15": {"class_type":"VAEDecode", "inputs":{"samples":["14",0],"vae":["3",0]}},
        "16": {"class_type":"SaveImage", "inputs":{"images":["15",0],"filename_prefix":f"ReEzSynth_{identifier}"}},
    }
    if settings.mode == "modify":
        graph["12"] = {"class_type":"LoadImageMask","inputs":{"image":uploads["noise_mask.png"],"channel":"red"}}
        graph["13"] = {"class_type":"SetLatentNoiseMask","inputs":{"samples":["5",0],"mask":["12",0]}}
        graph["14"]["inputs"]["latent_image"] = ["13",0]
    request = {
        "prompt":graph, "profile":PROFILE, "experimental":True, "mode":settings.mode,
        "native_size":[canvas.width,canvas.height], "padded_size":[width,height],
        "padding_right_bottom":[width-canvas.width,height-canvas.height],
        "vision_notice":VISION_NOTICE, "vision_preprocessing_acknowledged":True,
        "alpha_policy":settings.alpha_policy,
        "intent":settings.intent, "intermediate_background":settings.background,
        "protection_radius":settings.protection_radius, "models":dict(MODELS),
        "uploads":uploads, "expected_output_nodes":["16"],
        "output_contract":"opaque RGB intermediate; native crop and alpha-aware enforcement required",
        "snapshot_sha256":{name:hashlib.sha256(data).hexdigest() for name,data in snapshots.items()},
    }
    encoded = (json.dumps(request,sort_keys=True,allow_nan=False,separators=(",",":"))+"\n").encode()
    return QwenPlan(encoded, tuple(snapshots.items()), tuple(uploads.items()))
