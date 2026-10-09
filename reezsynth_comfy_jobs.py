"""Durable, single-attempt records for future ComfyUI inference jobs.

This module never contacts ComfyUI.  A caller must claim an attempt before it
can send the returned request bytes.  Recovery only reads records; it cannot
issue another claim for an attempted job, even if a response was lost.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from reezsynth_comfy_client import normalize_local_endpoint
from reezsynth_keyframe_candidates import _candidate_root


MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024
MAX_TOTAL_SNAPSHOT_BYTES = 512 * 1024 * 1024
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\.(?:png|jpg|jpeg)")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)),
             *(f"lpt{n}" for n in range(1, 10))}


@dataclass(frozen=True)
class JobRecord:
    directory: Path
    prompt_id: str
    client_id: str
    endpoint: str
    attempted: bool
    receipt_confirmed: bool


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _write_exclusive(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _read_bounded(path: Path, limit: int) -> bytes:
    if path.is_symlink():
        raise ValueError(f"Job record redirects outside its directory: {path.name}")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError(f"Job record exceeds its size limit: {path.name}")
    return content


def _hash_bounded(path: Path, limit: int) -> str:
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError(f"Input snapshot redirects outside its directory: {path.name}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            if size > limit:
                raise ValueError(f"Input snapshot exceeds its size limit: {path.name}")
            digest.update(chunk)
    return digest.hexdigest()


def _valid_name(name: object) -> bool:
    return (isinstance(name, str) and _NAME.fullmatch(name) is not None
            and name.split(".", 1)[0] not in _RESERVED)


def _job_dir(directory: str | Path) -> Path:
    path = Path(directory).absolute()
    if (path.name.startswith("comfy-job-") and path.is_dir()
            and path.parent.name == ".reezsynth-candidates"
            and not path.is_symlink() and not path.parent.is_symlink()
            and path.resolve() == path
            and path.parent.resolve() == path.parent):
        return path
    raise ValueError("Job folder is missing or redirects outside its project.")


def prepare_job(project: str | Path, *, endpoint: str, request: dict,
                snapshots: Mapping[str, bytes]) -> JobRecord:
    """Freeze a graph, metadata and input bytes before any network request.

    The request contains a nonempty ComfyUI `prompt` graph plus caller metadata.
    IDs and ownership marker are generated here; external code must use the
    stored POST body, never reconstruct it from mutable UI controls.
    """
    root = Path(project).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Select an existing project directory.")
    origin = normalize_local_endpoint(endpoint)
    if not isinstance(request, dict) or not isinstance(request.get("prompt"), dict) or not request["prompt"]:
        raise ValueError("A nonempty ComfyUI prompt graph is required.")
    if not isinstance(snapshots, Mapping) or not snapshots:
        raise ValueError("At least one immutable input snapshot is required.")
    if len(snapshots) > 32 or any(not _valid_name(name) for name in snapshots):
        raise ValueError("Input snapshot names must be simple image filenames.")
    if any(not isinstance(data, bytes) or not data or len(data) > MAX_SNAPSHOT_BYTES
           for data in snapshots.values()):
        raise ValueError("Input snapshots must be nonempty image bytes within the size limit.")
    if sum(len(data) for data in snapshots.values()) > MAX_TOTAL_SNAPSHOT_BYTES:
        raise ValueError("Input snapshots exceed the total size limit.")
    prompt_id = str(uuid.uuid4())
    client_id = str(uuid.uuid4())
    body = {"prompt": request["prompt"], "prompt_id": prompt_id,
            "client_id": client_id,
            "extra_data": {"reezsynth_job_id": prompt_id,
                           "reezsynth_endpoint": origin}}
    content = _json_bytes(body)
    if len(content) > MAX_REQUEST_BYTES:
        raise ValueError("ComfyUI prompt exceeds the size limit.")
    # Validate/copy metadata before creating a directory. It cannot override
    # the actual wire body or ownership marker.
    metadata = {key: value for key, value in request.items() if key != "prompt"}
    metadata_bytes = _json_bytes(metadata)
    if len(metadata_bytes) > MAX_REQUEST_BYTES:
        raise ValueError("Job metadata exceeds the size limit.")
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in snapshots.items()}
    manifest = _json_bytes({
        "schema": 1, "prompt_id": prompt_id, "client_id": client_id,
        "endpoint": origin, "request_sha256": hashlib.sha256(content).hexdigest(),
        "input_sha256": hashes, "metadata": json.loads(metadata_bytes),
    })
    if len(manifest) > MAX_REQUEST_BYTES:
        raise ValueError("Job manifest exceeds the size limit.")
    owner = _candidate_root(root)
    directory = owner / f"comfy-job-{prompt_id}"
    directory.mkdir(exist_ok=False)
    # An interrupted prepare may leave an incomplete directory for diagnosis.
    # Without a complete manifest it cannot be claimed or submitted.
    inputs = directory / "inputs"
    inputs.mkdir()
    for name, data in snapshots.items():
        _write_exclusive(inputs / name, data)
    _write_exclusive(directory / "submit.json", content)
    _write_exclusive(directory / "manifest.json", manifest)
    return JobRecord(directory, prompt_id, client_id, origin, False, False)


def load_job(directory: str | Path) -> JobRecord:
    """Read an existing record without any side effect or implicit resubmission."""
    path = _job_dir(directory)
    manifest = json.loads(_read_bounded(path / "manifest.json", MAX_REQUEST_BYTES))
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise ValueError("Unsupported job record.")
    prompt_id = manifest.get("prompt_id")
    client_id = manifest.get("client_id")
    for value in (prompt_id, client_id):
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError("Job identifiers are invalid.")
    if path.name != f"comfy-job-{prompt_id}":
        raise ValueError("Job directory and prompt identifier disagree.")
    content = _read_bounded(path / "submit.json", MAX_REQUEST_BYTES)
    if hashlib.sha256(content).hexdigest() != manifest.get("request_sha256"):
        raise ValueError("Frozen submission has changed.")
    body = json.loads(content)
    if (not isinstance(body, dict) or body.get("prompt_id") != prompt_id
            or body.get("client_id") != client_id
            or not isinstance(body.get("extra_data"), dict)
            or body["extra_data"].get("reezsynth_job_id") != prompt_id
            or body["extra_data"].get("reezsynth_endpoint") != manifest.get("endpoint")):
        raise ValueError("Frozen submission ownership is invalid.")
    hashes = manifest.get("input_sha256")
    if not isinstance(hashes, dict) or not hashes or len(hashes) > 32:
        raise ValueError("Input snapshot inventory is missing.")
    input_directory = path / "inputs"
    if (input_directory.is_symlink() or not input_directory.is_dir()
            or input_directory.resolve() != input_directory.absolute()):
        raise ValueError("Input snapshot folder is missing or redirected.")
    for name, expected in hashes.items():
        if not _valid_name(name):
            raise ValueError("Input snapshot name is invalid.")
        snapshot = input_directory / name
        if not snapshot.is_file():
            raise ValueError("Input snapshot is missing or redirected.")
        if _hash_bounded(snapshot, MAX_SNAPSHOT_BYTES) != expected:
            raise ValueError("Input snapshot has changed.")
    receipt_path = path / "receipt.json"
    attempt_path = path / "attempted"
    if receipt_path.is_symlink() or attempt_path.is_symlink():
        raise ValueError("Job state redirects outside its directory.")
    receipt_confirmed = receipt_path.exists()
    if receipt_confirmed:
        receipt = json.loads(_read_bounded(receipt_path, 64 * 1024))
        if not isinstance(receipt, dict) or receipt.get("prompt_id") != prompt_id:
            raise ValueError("Submission receipt does not match this job.")
    if receipt_confirmed and not attempt_path.exists():
        raise ValueError("Submission receipt has no matching attempt.")
    return JobRecord(path, prompt_id, client_id,
                     normalize_local_endpoint(manifest["endpoint"]),
                     attempt_path.exists(), receipt_confirmed)


def claim_submission(directory: str | Path) -> bytes:
    """Return the sole permitted POST body while permanently claiming this job."""
    job = load_job(directory)
    if job.attempted:
        raise ValueError("This job may already have been submitted; reconcile it first.")
    content = _read_bounded(job.directory / "submit.json", MAX_REQUEST_BYTES)
    manifest = json.loads(_read_bounded(job.directory / "manifest.json", MAX_REQUEST_BYTES))
    if hashlib.sha256(content).hexdigest() != manifest.get("request_sha256"):
        raise ValueError("Frozen submission has changed.")
    # Exclusive creation is the cross-process gate. Never remove this marker,
    # even if sending fails before the server acknowledges anything.
    _write_exclusive(job.directory / "attempted", b"attempted\n")
    return content


def record_receipt(directory: str | Path, response: bytes) -> JobRecord:
    """Persist only an acknowledged POST response with the expected prompt ID."""
    job = load_job(directory)
    if not job.attempted or job.receipt_confirmed:
        raise ValueError("There is no unacknowledged submission attempt.")
    if len(response) > 64 * 1024:
        raise ValueError("Submission response is unexpectedly large.")
    try:
        payload = json.loads(response)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Submission response is not valid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("prompt_id") != job.prompt_id:
        raise ValueError("Submission receipt does not match this job.")
    _write_exclusive(job.directory / "receipt.json", _json_bytes(payload))
    return load_job(job.directory)
