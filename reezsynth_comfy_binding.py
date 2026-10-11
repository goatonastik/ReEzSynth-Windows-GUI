"""Bind one offline Qwen plan to one durable job before any network action."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from reezsynth_comfy_client import normalize_local_endpoint
from reezsynth_comfy_jobs import (JobRecord, MAX_SNAPSHOT_BYTES,
                                 MAX_TOTAL_SNAPSHOT_BYTES, _valid_name, prepare_job)
from reezsynth_comfy_qwen import QwenPlan
from reezsynth_keyframe_candidates import _candidate_root


_UPLOAD = re.compile(r"reezsynth_[0-9a-f]{32}_(?:inference|noise_mask)\.png")


def bind_qwen_plan(project: str | Path, *, endpoint: str, plan: QwenPlan) -> JobRecord:
    """Freeze a validated plan once per project; a failed freeze consumes its ID.

    This claim also blocks another process from binding the same plan while the
    first is writing a job. A new plan has fresh upload names and may be used
    for an intentional new attempt; an uncertain POST is never retried.
    """
    if not isinstance(plan, QwenPlan):
        raise ValueError("A frozen Qwen plan is required.")
    if not str(project).strip():
        raise ValueError("Select an existing project directory.")
    if not isinstance(plan.snapshots, tuple) or not isinstance(plan.uploads, tuple):
        raise ValueError("Qwen plan inventory is invalid.")
    try:
        request = json.loads(plan.request_bytes)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Qwen plan request is invalid.") from exc
    if not isinstance(request, dict) or not isinstance(request.get("prompt"), dict):
        raise ValueError("Qwen plan graph is missing.")
    try:
        snapshots = dict(plan.snapshots)
        uploads = dict(plan.uploads)
    except (TypeError, ValueError) as exc:
        raise ValueError("Qwen plan inventory is invalid.") from exc
    if (request.get("mode") not in {"generate", "modify"}
            or len(snapshots) != len(plan.snapshots) or len(uploads) != len(plan.uploads)
            or set(uploads) != ({"inference.png"} if request.get("mode") == "generate"
                                else {"inference.png", "noise_mask.png"})
            or not set(uploads).issubset(snapshots)
            or request.get("uploads") != uploads):
        raise ValueError("Qwen plan inputs and upload inventory disagree.")
    if any(not isinstance(name, str) or not _UPLOAD.fullmatch(name)
           for name in uploads.values()) or len(set(uploads.values())) != len(uploads):
        raise ValueError("Qwen plan upload names are invalid or repeated.")
    if any(name.split("_", 2)[1] != uploads["inference.png"].split("_", 2)[1]
           for name in uploads.values()):
        raise ValueError("Qwen plan upload names must share one unique identity.")
    if (len(snapshots) > 32 or any(not _valid_name(name) for name in snapshots)
            or any(not isinstance(data, bytes) or not data or len(data) > MAX_SNAPSHOT_BYTES
                   for data in snapshots.values())
            or sum(len(data) for data in snapshots.values()) > MAX_TOTAL_SNAPSHOT_BYTES):
        raise ValueError("Qwen plan snapshots are invalid or too large.")
    graph = request["prompt"]
    if any(not isinstance(node, dict) or not isinstance(node.get("inputs"), dict)
           for node in graph.values()):
        raise ValueError("Qwen plan graph nodes are invalid.")
    if (not isinstance(graph.get("4"), dict)
            or graph["4"].get("class_type") != "LoadImage"
            or graph["4"]["inputs"].get("image") != uploads["inference.png"]
            or (request.get("mode") == "modify" and
                (not isinstance(graph.get("12"), dict)
                 or graph["12"].get("class_type") != "LoadImageMask"
                 or graph["12"]["inputs"].get("image") != uploads["noise_mask.png"]))
            or (request.get("mode") == "generate" and "12" in graph)
            or any(node.get("class_type") in {"LoadImage", "LoadImageMask"}
                   and node["inputs"].get("image") not in uploads.values()
                   for node in graph.values())):
        raise ValueError("Qwen graph does not reference its frozen upload names.")
    if request.get("snapshot_sha256") != {
        name: hashlib.sha256(data).hexdigest() for name, data in snapshots.items()
    }:
        raise ValueError("Qwen plan snapshots have changed.")
    try:
        root = Path(project).expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("Select an existing project directory.") from exc
    if not root.is_dir():
        raise ValueError("Select an existing project directory.")
    normalize_local_endpoint(endpoint)
    owner = _candidate_root(root)
    # All uploads in a plan share the same random prefix. Claim that upload
    # identity, not the request hash: edited settings cannot reuse the names.
    token = uploads["inference.png"].split("_", 2)[1]
    claim = owner / f"qwen-upload-{token}.claimed"
    try:
        with claim.open("xb") as stream:
            stream.write(b"claimed\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ValueError("This Qwen plan was already bound; make a fresh plan for another run.") from exc
    return prepare_job(root, endpoint=endpoint, request=request, snapshots=snapshots)
