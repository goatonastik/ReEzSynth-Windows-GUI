"""CPU-only preparation and review of externally generated keyframe candidates."""

from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from reezsynth_keyframe_candidates import CandidateRecord, _candidate_root, _sha256
from reezsynth_keyframe_protection import (
    AlphaPolicy, EditIntent, ProtectionReport, compose_modified,
    propose_dark_strokes, protection_band,
)


@dataclass(frozen=True)
class PreviewRequest:
    frame_number: int
    source_path: str
    drawing_path: str
    raw_path: str
    edit_mask_path: str
    protection_mask_path: str
    edit_intent: str
    alpha_policy: str
    protection_radius: int


@dataclass(frozen=True)
class PreviewResult:
    request: PreviewRequest
    width: int
    height: int
    image_png: bytes
    views: dict[str, bytes]
    input_hashes: dict[str, str]
    report: ProtectionReport


def _read_image(path: str, *, mask: bool = False, png_only: bool = False):
    target = Path(path).expanduser().resolve(strict=True)
    content = target.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                allowed = {"PNG"} if mask or png_only else {"PNG", "JPEG"}
                if image.format not in allowed:
                    raise ValueError(f"Unsupported image format: {target.name}")
                if mask and image.mode != "L":
                    raise ValueError(f"Mask must be an 8-bit grayscale PNG: {target.name}")
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
                pixels = np.array(image if mask else image.convert("RGBA"), dtype=np.uint8)
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError(f"Image exceeds the supported pixel limit: {target.name}") from exc
    except SyntaxError as exc:
        raise ValueError(f"Image is damaged or incomplete: {target.name}") from exc
    return pixels, digest, target


def _png(pixels):
    with io.BytesIO() as stream:
        Image.fromarray(pixels).save(stream, format="PNG")
        return stream.getvalue()


def _thumbnail_png(pixels):
    image = Image.fromarray(pixels)
    image.thumbnail((500, 500), Image.Resampling.LANCZOS)
    with io.BytesIO() as stream:
        image.save(stream, format="PNG")
        return stream.getvalue()


def prepare_preview(request: PreviewRequest) -> PreviewResult:
    """Validate, compose, and return display/storage bytes; no files are written."""
    if type(request.frame_number) is not int or request.frame_number < 0:
        raise ValueError("Choose a valid frame number.")
    try:
        EditIntent(request.edit_intent)
        AlphaPolicy(request.alpha_policy)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose a supported edit intention and alpha policy.") from exc
    names = {
        "source": request.source_path, "drawing": request.drawing_path,
        "raw": request.raw_path, "edit_mask": request.edit_mask_path,
        "protection_mask": request.protection_mask_path,
    }
    if any(not value.strip() for value in names.values()):
        raise ValueError("Select a source, drawing, raw PNG, and both mask PNGs.")
    loaded = {name: _read_image(path, mask=name.endswith("mask"), png_only=name == "raw")
              for name, path in names.items()}
    source, drawing, raw = (loaded[name][0] for name in ("source", "drawing", "raw"))
    edit, protection = (loaded[name][0] for name in ("edit_mask", "protection_mask"))
    dimensions = source.shape[:2]
    if any(pixels.shape[:2] != dimensions for pixels, _, _ in loaded.values()):
        raise ValueError("All inputs and masks must match the source's native dimensions.")
    expanded = protection_band(protection, request.protection_radius)
    final, report = compose_modified(
        drawing, raw, edit, expanded, alpha_policy=request.alpha_policy,
    )
    # Detect files that changed between loading and completing the preview.
    for name, (_, digest, target) in loaded.items():
        if _sha256(target) != digest:
            raise ValueError(f"{name.replace('_', ' ').capitalize()} changed during preview; retry.")
    views = {
        "Source": _thumbnail_png(source), "Drawing": _thumbnail_png(drawing),
        "Raw candidate": _thumbnail_png(raw),
        "Enforced preview": _thumbnail_png(final),
        "Edit mask": _thumbnail_png(edit), "Protected band": _thumbnail_png(expanded),
        "Alpha": _thumbnail_png(final[..., 3]),
    }
    return PreviewResult(request, dimensions[1], dimensions[0], _png(final), views,
                         {name: value[1] for name, value in loaded.items()}, report)


def preview_dark_strokes(drawing_path: str) -> bytes:
    """Show a suggested mask only; never apply it without user-supplied masks."""
    drawing, _, _ = _read_image(drawing_path)
    return _thumbnail_png(propose_dark_strokes(drawing))


def save_enforced_candidate(project_directory: str, result: PreviewResult) -> CandidateRecord:
    """Publish one unreviewed preview in a new owned directory, with provenance."""
    if not project_directory.strip():
        raise ValueError("Select a project directory before saving a candidate.")
    root = Path(project_directory).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Project directory does not exist.")
    for name, expected in result.input_hashes.items():
        path = Path(getattr(result.request, f"{name}_path")).expanduser().resolve(strict=True)
        if _sha256(path) != expected:
            raise ValueError(f"{name.replace('_', ' ').capitalize()} changed since preview; rebuild it.")
    image_bytes = result.image_png
    with Image.open(io.BytesIO(image_bytes)) as image:
        if image.format != "PNG" or image.mode != "RGBA" or image.size != (result.width, result.height):
            raise ValueError("The enforced preview is not a native-size RGBA PNG.")
        image.verify()
    candidate_root = _candidate_root(root)
    identifier = uuid.uuid4().hex
    owned = candidate_root / f"frame_{result.request.frame_number:06d}_{identifier}"
    owned.mkdir()
    image_path = owned / "candidate.png"
    metadata_path = owned / "record.json"
    metadata = {
        "schema": 2, "status": "unreviewed", "identifier": identifier,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "modify", "frame_number": result.request.frame_number,
        "width": result.width, "height": result.height,
        "edit_intent": result.request.edit_intent,
        "alpha_policy": result.request.alpha_policy,
        "protection_radius": result.request.protection_radius,
        "inputs": {name: {"path": str(Path(getattr(result.request, f"{name}_path")).expanduser().resolve()),
                          "sha256": digest}
                   for name, digest in result.input_hashes.items()},
        "candidate_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "qc": vars(result.report),
    }
    try:
        with image_path.open("xb") as stream:
            stream.write(image_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        with metadata_path.open("x", encoding="utf-8") as stream:
            json.dump(metadata, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        image_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        try:
            owned.rmdir()
        except OSError:
            pass
        raise
    return CandidateRecord(identifier, image_path, metadata_path, result.width, result.height)
