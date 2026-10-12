"""CPU-only preparation of a frozen Qwen job from explicit tab inputs."""

from __future__ import annotations

from dataclasses import dataclass

from reezsynth_comfy_binding import bind_qwen_plan
from reezsynth_comfy_processing import _read_image
from reezsynth_comfy_qwen import QwenSettings, plan_qwen
from reezsynth_keyframe_candidates import _sha256
from reezsynth_keyframe_protection import AlphaPolicy, EditIntent


@dataclass(frozen=True)
class PrepareJobRequest:
    project: str
    endpoint: str
    intended_frame_number: int
    mode: str
    source_path: str
    drawing_path: str
    edit_mask_path: str
    protection_mask_path: str
    prompt: str
    seed: int
    steps: int
    guidance: float
    denoise: float
    intent: str | None
    alpha_policy: str | None
    background: tuple[int, int, int] | None
    protection_radius: int
    allow_vision_preprocessing: bool


def prepare_qwen_job(request: PrepareJobRequest):
    """Freeze local pixels and intended frame; never contact ComfyUI."""
    if not isinstance(request, PrepareJobRequest):
        raise ValueError("Choose explicit Qwen job settings before preparing.")
    if type(request.intended_frame_number) is not int or not 0 <= request.intended_frame_number <= 2147483647:
        raise ValueError("Choose a valid intended frame number.")
    if request.mode not in {"generate", "modify"}:
        raise ValueError("Choose Generate or Modify explicitly.")
    if not request.source_path.strip():
        raise ValueError("Choose an original source frame before preparing.")
    loaded = {"source": _read_image(request.source_path)}
    options = {}
    if request.mode == "modify":
        if any(not path.strip() for path in (
                request.drawing_path, request.edit_mask_path, request.protection_mask_path)):
            raise ValueError("Modify requires a drawing and both grayscale mask PNGs.")
        loaded["drawing"] = _read_image(request.drawing_path, png_only=True)
        loaded["edit_mask"] = _read_image(request.edit_mask_path, mask=True)
        loaded["protection_mask"] = _read_image(request.protection_mask_path, mask=True)
        try:
            intent = EditIntent(request.intent)
            policy = AlphaPolicy(request.alpha_policy)
        except (TypeError, ValueError) as exc:
            raise ValueError("Choose a supported edit intention and transparency policy.") from exc
        options = {"intent": intent, "alpha_policy": policy,
                   "background": request.background,
                   "protection_radius": request.protection_radius}
    settings = QwenSettings(
        mode=request.mode, prompt=request.prompt, seed=request.seed,
        steps=request.steps, guidance=request.guidance, denoise=request.denoise,
        allow_vision_preprocessing=request.allow_vision_preprocessing, **options,
    )
    source = loaded["source"][0]
    pixels = ({key: value[0] for key, value in loaded.items() if key != "source"}
              if request.mode == "modify" else {})
    plan = plan_qwen(settings, source, **pixels)
    for key, (_, digest, path) in loaded.items():
        if _sha256(path) != digest:
            raise ValueError(f"{key.replace('_', ' ').capitalize()} changed during job preparation; retry.")
    return bind_qwen_plan(request.project, endpoint=request.endpoint, plan=plan,
                          intended_frame_number=request.intended_frame_number)
