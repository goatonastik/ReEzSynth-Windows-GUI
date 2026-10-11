"""Prepare an unreviewed native candidate from an owned completed job.

Only frozen job inputs participate. Preview preparation performs read-only
network I/O and CPU composition. Saving writes an unreviewed candidate in the
project, never a numbered synthesis keyframe.
"""
from dataclasses import asdict, dataclass
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import uuid

import numpy as np
from PIL import Image

from reezsynth_comfy_jobs import (
    MAX_REQUEST_BYTES, MAX_SNAPSHOT_BYTES, _json_bytes, _read_bounded, load_job,
)
from reezsynth_comfy_output import fetch_owned_output
from reezsynth_comfy_qwen import PROFILE
from reezsynth_keyframe_candidates import CandidateRecord, _candidate_root
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
    raw_output_png: bytes


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
    intended_frame = metadata.get("intended_frame_number")
    if (intended_frame is not None
            and (type(intended_frame) is not int or not 0 <= intended_frame <= 2147483647)):
        raise ValueError("Frozen intended frame number is invalid.")
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
        "intended_frame_number": intended_frame,
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
                               report, output.raw_png)


def _write_exclusive(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def save_job_candidate(directory: str | Path,
                       preview: JobCandidatePreview) -> CandidateRecord:
    """Save verified preview bytes as one unreviewed, unassigned candidate.

    `record.json` is the completion marker. An interrupted directory without it
    is not a valid candidate. The existing job and numbered keys are untouched.
    """
    if not isinstance(preview, JobCandidatePreview):
        raise ValueError("A prepared job preview is required.")
    job = load_job(directory)
    if preview.prompt_id != job.prompt_id:
        raise ValueError("Preview belongs to another job.")
    root = job.directory.parent.parent
    manifest_path = job.directory / "manifest.json"
    manifest_bytes = _read_bounded(manifest_path, MAX_REQUEST_BYTES)
    manifest = json.loads(manifest_bytes)
    metadata = manifest.get("metadata") if isinstance(manifest, dict) else None
    if not isinstance(metadata, dict):
        raise ValueError("Frozen job metadata is invalid.")
    intended_frame = metadata.get("intended_frame_number")
    if (intended_frame is not None
            and (type(intended_frame) is not int or not 0 <= intended_frame <= 2147483647)):
        raise ValueError("Frozen intended frame number is invalid.")
    try:
        provenance = json.loads(preview.provenance_json)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Preview provenance is invalid.") from exc
    if (not isinstance(provenance, dict)
            or provenance.get("status") != "unreviewed"
            or provenance.get("prompt_id") != job.prompt_id
            or provenance.get("job_directory") != str(job.directory)
            or provenance.get("mode") != preview.mode
            or provenance.get("mode") != metadata.get("mode")
            or provenance.get("intended_frame_number") != metadata.get("intended_frame_number")
            or provenance.get("manifest_sha256") != hashlib.sha256(manifest_bytes).hexdigest()
            or provenance.get("input_sha256") != manifest.get("input_sha256")
            or provenance.get("candidate_sha256") != hashlib.sha256(preview.image_png).hexdigest()
            or provenance.get("downloaded_output_sha256") != hashlib.sha256(preview.raw_output_png).hexdigest()):
        raise ValueError("Preview does not match its frozen job or image bytes.")
    native = (provenance.get("width"), provenance.get("height"))
    padded = provenance.get("padded_size")
    if (any(type(value) is not int or value < 1 for value in native)
            or not isinstance(padded, list) or len(padded) != 2
            or any(type(value) is not int or value < 1 for value in padded)
            or native != tuple(metadata.get("native_size", ()))
            or padded != metadata.get("padded_size")):
        raise ValueError("Preview dimensions do not match the frozen job.")
    _image(preview.image_png, "RGBA", native, "candidate")
    _image(preview.raw_output_png, "RGB", tuple(padded), "raw output")
    owner = _candidate_root(root)
    identifier = uuid.uuid4().hex
    saved = owner / f"comfy-preview-{identifier}"
    saved.mkdir(exist_ok=False)
    image_path = saved / "candidate.png"
    metadata_path = saved / "record.json"
    files = (image_path, saved / "raw-output.png", saved / "provenance.json")
    record = {
        "schema": 3, "status": "unreviewed", "identifier": identifier,
        "prompt_id": job.prompt_id, "mode": preview.mode,
        "frame_number": None, "width": native[0], "height": native[1],
        "intended_frame_number": intended_frame,
        "candidate_sha256": provenance["candidate_sha256"],
        "raw_output_sha256": provenance["downloaded_output_sha256"],
        "provenance_sha256": hashlib.sha256(preview.provenance_json).hexdigest(),
        "qc": asdict(preview.matte_report) if preview.matte_report is not None else None,
    }
    try:
        for path, content in zip(files, (preview.image_png,
                                         preview.raw_output_png, preview.provenance_json)):
            _write_exclusive(path, content)
        # Detect ordinary changes to the job while the candidate was saved.
        load_job(job.directory)
        if _read_bounded(manifest_path, MAX_REQUEST_BYTES) != manifest_bytes:
            raise ValueError("Frozen job changed while saving its candidate.")
        _write_exclusive(metadata_path, _json_bytes(record))
    except Exception:
        metadata_path.unlink(missing_ok=True)
        for path in files:
            path.unlink(missing_ok=True)
        try:
            saved.rmdir()
        except OSError:
            pass
        raise
    return CandidateRecord(identifier, image_path, metadata_path, *native)
