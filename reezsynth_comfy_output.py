"""Read one owned ComfyUI RGB result and crop only explicit native padding."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

import numpy as np
from PIL import Image

from reezsynth_comfy_jobs import MAX_REQUEST_BYTES, _read_bounded, load_job
from reezsynth_comfy_status import MAX_STATUS_BYTES, parse_job_status
from reezsynth_comfy_transport import _opener, _read_response, _timeout


_OUTPUT_NAME = re.compile(r"ReEzSynth_[0-9a-f]{32}_[0-9]{5}_[.]png")


@dataclass(frozen=True)
class OwnedOutput:
    prompt_id: str
    filename: str
    source_sha256: str
    native_rgb: np.ndarray


def fetch_owned_output(directory: str | Path, *, timeout: float = 15.0) -> OwnedOutput:
    """Fetch a completed owned result without publishing a candidate."""
    _timeout(timeout)
    job = load_job(directory)
    # A lost POST response leaves no receipt even when ComfyUI accepted the
    # single attempt. Terminal status with the frozen ownership marker is the
    # read-only recovery proof; this path must never submit the prompt again.
    if not job.attempted:
        raise ValueError("The job has no submission attempt.")
    opener = _opener()
    status_request = Request(f"{job.endpoint}/api/jobs/{job.prompt_id}", method="GET",
                             headers={"Accept": "application/json"})
    try:
        status_bytes = _read_response(opener, status_request, timeout=timeout,
                                      limit=MAX_STATUS_BYTES)
    except HTTPError as exc:
        if exc.code == 404:
            raise ValueError("ComfyUI has no record of this attempt; it remains uncertain.") from exc
        raise
    observation = parse_job_status(job, status_bytes)
    if observation.status != "completed" or not observation.ownership_verified:
        raise ValueError("Wait for a completed job with verified ownership.")
    def reject_constant(value):
        raise ValueError("ComfyUI job data contains an invalid number.")
    try:
        status = json.loads(status_bytes, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ComfyUI returned invalid job data.") from exc
    manifest = json.loads(_read_bounded(job.directory / "manifest.json", MAX_REQUEST_BYTES))
    metadata = manifest.get("metadata")
    content = _read_bounded(job.directory / "submit.json", MAX_REQUEST_BYTES)
    if hashlib.sha256(content).hexdigest() != manifest.get("request_sha256"):
        raise ValueError("Frozen submission changed while fetching output.")
    body = json.loads(content)
    graph = body.get("prompt")
    node = graph.get("16") if isinstance(graph, dict) else None
    node_inputs = node.get("inputs") if isinstance(node, dict) else None
    prefix = node_inputs.get("filename_prefix") if isinstance(node_inputs, dict) else None
    if (not isinstance(metadata, dict) or not isinstance(prefix, str)
            or not re.fullmatch(r"ReEzSynth_[0-9a-f]{32}", prefix)
            or node.get("class_type") != "SaveImage"
            or metadata.get("expected_output_nodes") != ["16"]):
        raise ValueError("Frozen output contract is invalid.")
    native = metadata.get("native_size")
    padded = metadata.get("padded_size")
    if (not isinstance(native, list) or not isinstance(padded, list)
            or len(native) != 2 or len(padded) != 2
            or any(type(v) is not int or v < 1 for v in native + padded)
            or any(p < n or p - n > 15 for n, p in zip(native, padded))
            or padded[0] % 16 or padded[1] % 16
            or padded[0] * padded[1] > 16 * 1024 * 1024):
        raise ValueError("Frozen native canvas dimensions are invalid.")
    outputs = status.get("outputs")
    if not isinstance(outputs, dict) or set(outputs) != {"16"}:
        raise ValueError("The owned output contains unexpected nodes.")
    node_output = outputs.get("16")
    images = node_output.get("images") if isinstance(node_output, dict) else None
    if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
        raise ValueError("The owned output node must contain exactly one image.")
    descriptor = images[0]
    filename = descriptor.get("filename")
    if (not isinstance(filename, str) or not _OUTPUT_NAME.fullmatch(filename)
            or not filename.startswith(prefix + "_")
            or descriptor.get("subfolder") != "" or descriptor.get("type") != "output"):
        raise ValueError("ComfyUI returned an unexpected output file.")
    query = urlencode({"filename": filename, "subfolder": "", "type": "output"})
    image_request = Request(f"{job.endpoint}/view?{query}", method="GET")
    image_bytes = _read_response(opener, image_request, timeout=timeout,
                                 limit=padded[0] * padded[1] * 3 + 1024 * 1024)
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            if image.format != "PNG" or image.mode != "RGB" or image.size != tuple(padded):
                raise ValueError("Owned output must be RGB PNG at the padded native size.")
            image.verify()
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
            pixels = np.asarray(image)
    except Image.DecompressionBombError as exc:
        raise ValueError("Owned output exceeds the supported pixel limit.") from exc
    except (OSError, SyntaxError) as exc:
        raise ValueError("Owned output PNG is damaged or incomplete.") from exc
    return OwnedOutput(job.prompt_id, filename, hashlib.sha256(image_bytes).hexdigest(),
                       pixels[:native[1], :native[0]].copy())
