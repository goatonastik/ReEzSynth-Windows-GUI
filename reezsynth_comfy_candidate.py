"""Prepare an unreviewed native candidate from an owned completed job.

Only frozen job inputs participate. This worker performs read-only network I/O
and CPU composition; it never assigns a keyframe or writes project files.
"""
from dataclasses import dataclass
from io import BytesIO
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from reezsynth_comfy_jobs import (
    MAX_REQUEST_BYTES, MAX_SNAPSHOT_BYTES, _json_bytes, _read_bounded, load_job,
)
from reezsynth_comfy_output import fetch_owned_output
from reezsynth_comfy_qwen import PROFILE
from reezsynth_keyframe_matte import MatteReport, compose_matted_output
from reezsynth_keyframe_protection import AlphaPolicy, EditIntent, protection_band


@dataclass(frozen=True)
class JobCandidatePreview:
    """Immutable review bytes, not approval to replace a numbered keyframe."""
    prompt_id: str
    mode: str
    image_png: bytes
    provenance_json: bytes
    matte_report: MatteReport | None


def _png(pixels):
    stream = BytesIO()
    Image.fromarray(pixels).save(stream, format="PNG")
    return stream.getvalue()


def _image(content, mode, size, name):
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != "PNG" or image.mode != mode or image.size != size:
                raise ValueError(f"Frozen {name} has the wrong format or dimensions.")
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()
            return np.array(image)
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Frozen {name} is not a readable native image.") from exc


def prepare_job_candidate(directory: str | Path, *, timeout=15.0) -> JobCandidatePreview:
    """Download, verify, and enforce one result; no mutable UI paths are used.

    Job records are a local trust boundary, not signatures against a malicious
    project author. Ordinary changes during this operation are rejected.
    """
    job = load_job(directory)
    manifest_path = job.directory / "manifest.json"
    manifest_bytes = _read_bounded(manifest_path, MAX_REQUEST_BYTES)
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError("Frozen candidate manifest is invalid.")
    metadata = manifest.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("Frozen candidate metadata is invalid.")
    mode = metadata.get("mode")
    if metadata.get("profile") != PROFILE or mode not in {"modify", "generate"}:
        raise ValueError("Unsupported frozen candidate profile or mode.")
    names = {"source.png", "inference.png"}
    if mode == "modify":
        names |= {"drawing.png", "edit.png", "protection.png", "noise_mask.png"}
    hashes = manifest.get("input_sha256")
    if (not isinstance(hashes, dict) or set(hashes) != names
            or metadata.get("snapshot_sha256") != hashes):
        raise ValueError("Frozen candidate snapshot inventory disagrees with its plan.")
    snapshots = {}
    for name in sorted(names):
        content = _read_bounded(job.directory / "inputs" / name, MAX_SNAPSHOT_BYTES)
        if hashlib.sha256(content).hexdigest() != hashes[name]:
            raise ValueError("Frozen candidate input changed while reading.")
        snapshots[name] = content
    # Retrieval validates the planned native/padded canvas and completed ownership.
    # Do not accept a caller-supplied mutable OwnedOutput as ownership evidence.
    output = fetch_owned_output(job.directory, timeout=timeout)
    if output.prompt_id != job.prompt_id:
        raise ValueError("Output belongs to another job.")
    height, width = output.native_rgb.shape[:2]
    size = (width, height)
    # Modify also validates source provenance/dimensions, though it conditions on drawing.
    source = _image(snapshots["source.png"], "RGBA", size, "source")
    padded = metadata.get("padded_size")
    if (not isinstance(padded, list) or len(padded) != 2
            or any(type(v) is not int for v in padded)
            or padded != [((width + 15) // 16) * 16, ((height + 15) // 16) * 16]):
        raise ValueError("Frozen candidate padding is invalid.")
    baseline = _image(snapshots["inference.png"], "RGB",
                      tuple(padded), "inference")[:height, :width]
    report = None
    if mode == "modify":
        if metadata.get("alpha_policy") != AlphaPolicy.PRESERVE:
            raise ValueError("Only Preserve drawing alpha is supported for this adapter.")
        EditIntent(metadata.get("intent"))
        background = metadata.get("intermediate_background")
        if not isinstance(background, list):
            raise ValueError("Frozen intermediate background is missing.")
        drawing = _image(snapshots["drawing.png"], "RGBA", size, "drawing")
        edit = _image(snapshots["edit.png"], "L", size, "edit mask")
        protected = _image(snapshots["protection.png"], "L", size, "protection mask")
        band = protection_band(protected, metadata.get("protection_radius"))
        noise = _image(snapshots["noise_mask.png"], "RGB", tuple(padded), "noise mask")
        effective = np.where((band == 0) & (drawing[..., 3] > 0), edit, 0)
        expected = np.pad(effective, ((0, padded[1] - height), (0, padded[0] - width)))
        if any(not np.array_equal(noise[..., channel], expected) for channel in range(3)):
            raise ValueError("Frozen edit/protection region disagrees with the inference mask.")
        pixels, report = compose_matted_output(
            drawing, output.native_rgb, baseline, edit, band,
            background=tuple(background),
        )
    else:
        if not np.all(source[..., 3] == 255) or not np.array_equal(baseline, source[..., :3]):
            raise ValueError("Generate requires the frozen opaque source as model input.")
        pixels = np.concatenate((output.native_rgb,
                                 np.full((height, width, 1), 255, dtype=np.uint8)), axis=2)
    image_png = _png(pixels)
    # Recheck both the exact metadata bytes and input hashes after network/CPU work.
    load_job(job.directory)
    if _read_bounded(manifest_path, MAX_REQUEST_BYTES) != manifest_bytes:
        raise ValueError("Frozen candidate plan changed during preparation.")
    provenance = {
        "status": "unreviewed", "prompt_id": job.prompt_id, "mode": mode,
        "profile": metadata["profile"], "padded_size": padded,
        "job_directory": str(job.directory),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "input_sha256": hashes, "output_filename": output.filename,
        "downloaded_output_sha256": output.source_sha256,
        "candidate_sha256": hashlib.sha256(image_png).hexdigest(),
        "width": width, "height": height,
        "alpha_policy": metadata.get("alpha_policy"),
        "intent": metadata.get("intent"),
        "intermediate_background": metadata.get("intermediate_background"),
        "protection_radius": metadata.get("protection_radius"),
    }
    return JobCandidatePreview(job.prompt_id, mode, image_png,
                               _json_bytes(provenance),
                               report)
