"""CPU-only review and explicit approval of saved ComfyUI candidates.

Approval records intent for a frozen image and frame. It never publishes a
numbered keyframe or changes the source job or candidate record.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image

from reezsynth_comfy_jobs import MAX_REQUEST_BYTES, MAX_SNAPSHOT_BYTES, _read_bounded, load_job
from reezsynth_keyframe_candidates import CANDIDATE_DIR


@dataclass(frozen=True)
class CandidateReview:
    project: Path
    directory: Path
    image_png: bytes
    frame_number: int
    prompt_id: str
    record_sha256: str
    provenance_sha256: str
    image_sha256: str
    raw_sha256: str
    manifest_sha256: str
    approved: bool = False
    rejected: bool = False


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _plain_file(path: Path, limit: int = MAX_REQUEST_BYTES) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Candidate file is missing or redirected: {path.name}")
    return _read_bounded(path, limit)


def _object(payload: bytes, label: str) -> dict:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"Candidate {label} is invalid.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Candidate {label} is invalid.")
    return value


def load_candidate_review(project: str | Path, directory: str | Path,
                          frame_number: int | None = None) -> CandidateReview:
    """Validate a schema-3 candidate and freeze the exact image shown for review."""
    root = Path(project).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Choose an existing project before reviewing a candidate.")
    owner = root / CANDIDATE_DIR
    candidate = Path(directory).expanduser().absolute()
    if (not owner.is_dir() or owner.is_symlink() or owner.resolve(strict=True) != owner.absolute()
            or candidate.parent != owner or candidate.is_symlink()
            or not candidate.is_dir() or candidate.resolve(strict=True) != candidate
            or not candidate.name.startswith("comfy-preview-")):
        raise ValueError("Candidate folder does not belong to the selected project.")
    record_bytes = _plain_file(candidate / "record.json")
    provenance_bytes = _plain_file(candidate / "provenance.json")
    image_bytes = _plain_file(candidate / "candidate.png", MAX_SNAPSHOT_BYTES)
    raw_bytes = _plain_file(candidate / "raw-output.png", MAX_SNAPSHOT_BYTES)
    record = _object(record_bytes, "record")
    provenance = _object(provenance_bytes, "provenance")
    if (record.get("schema") != 3 or record.get("status") != "unreviewed"
            or record.get("identifier") != candidate.name.removeprefix("comfy-preview-")
            or record.get("frame_number") is not None
            or record.get("candidate_sha256") != _sha(image_bytes)
            or record.get("raw_output_sha256") != _sha(raw_bytes)
            or record.get("provenance_sha256") != _sha(provenance_bytes)):
        raise ValueError("Candidate record or saved bytes changed.")
    if not isinstance(provenance.get("job_directory"), str):
        raise ValueError("Candidate source job path is invalid.")
    job_dir = Path(provenance["job_directory"])
    job = load_job(job_dir)
    if job.directory.parent != owner or job.directory.parent.parent != root:
        raise ValueError("Candidate source job belongs to another project.")
    manifest_bytes = _plain_file(job.directory / "manifest.json")
    manifest = _object(manifest_bytes, "job manifest")
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Candidate source job metadata is invalid.")
    intended = record.get("intended_frame_number")
    chosen = intended if frame_number is None else frame_number
    if (type(chosen) is not int or not 0 <= chosen <= 2147483647
            or (intended is not None and chosen != intended)
            or metadata.get("intended_frame_number") != intended):
        raise ValueError("Candidate frame does not match its frozen job; choose the intended frame.")
    if (record.get("prompt_id") != job.prompt_id
            or provenance.get("prompt_id") != job.prompt_id
            or record.get("mode") != provenance.get("mode")
            or record.get("mode") != metadata.get("mode")
            or provenance.get("status") != "unreviewed"
            or provenance.get("job_directory") != str(job.directory)
            or provenance.get("intended_frame_number") != intended
            or provenance.get("manifest_sha256") != _sha(manifest_bytes)
            or provenance.get("input_sha256") != manifest.get("input_sha256")
            or provenance.get("candidate_sha256") != _sha(image_bytes)
            or provenance.get("downloaded_output_sha256") != _sha(raw_bytes)):
        raise ValueError("Candidate provenance does not match its saved job.")
    native = metadata.get("native_size")
    padded = metadata.get("padded_size")
    if (not isinstance(native, list) or len(native) != 2
            or any(type(n) is not int or n < 1 for n in native)
            or not isinstance(padded, list) or len(padded) != 2
            or any(type(n) is not int or n < 1 for n in padded)
            or [record.get("width"), record.get("height")] != native
            or [provenance.get("width"), provenance.get("height")] != native
            or provenance.get("padded_size") != padded):
        raise ValueError("Candidate dimensions do not match its frozen job.")
    with Image.open(BytesIO(image_bytes)) as image:
        if image.format != "PNG" or image.mode != "RGBA" or image.size != tuple(native):
            raise ValueError("Candidate must be a native-size RGBA PNG.")
        image.load()
    with Image.open(BytesIO(raw_bytes)) as raw:
        if raw.format != "PNG" or raw.mode != "RGB" or raw.size != tuple(padded):
            raise ValueError("Raw output differs from its frozen size or format.")
        raw.load()
    approval = candidate / "approval.json"
    rejection = candidate / "rejection.json"
    decision_lock = candidate / ".review-decision"
    approved = False
    rejected = False
    if approval.is_symlink() or rejection.is_symlink():
        raise ValueError("Review decision marker is redirected.")
    if approval.exists() and rejection.exists():
        raise ValueError("Conflicting approval and rejection markers; inspect them before continuing.")
    if decision_lock.is_symlink() or (decision_lock.exists() and not decision_lock.is_dir()):
        raise ValueError("Review decision lock is redirected or invalid.")
    if decision_lock.exists() and not (approval.exists() or rejection.exists()):
        raise ValueError("Review decision was interrupted; inspect it before continuing.")
    if approval.exists():
        saved = _object(_plain_file(approval), "approval marker")
        if (saved.get("schema") != 1 or saved.get("status") != "approved_unassigned"
                or saved.get("project") != str(root) or saved.get("frame_number") != chosen
                or saved.get("prompt_id") != job.prompt_id
                or saved.get("candidate_sha256") != _sha(image_bytes)
                or saved.get("record_sha256") != _sha(record_bytes)
                or saved.get("provenance_sha256") != _sha(provenance_bytes)
                or saved.get("raw_output_sha256") != _sha(raw_bytes)
                or saved.get("manifest_sha256") != _sha(manifest_bytes)):
            raise ValueError("Approval marker is incomplete or conflicts with this candidate; inspect it before continuing.")
        approved = True
    if rejection.exists():
        saved = _object(_plain_file(rejection), "rejection marker")
        if (saved.get("schema") != 1 or saved.get("status") != "rejected"
                or saved.get("project") != str(root) or saved.get("frame_number") != chosen
                or saved.get("prompt_id") != job.prompt_id
                or saved.get("candidate_sha256") != _sha(image_bytes)
                or saved.get("record_sha256") != _sha(record_bytes)
                or saved.get("provenance_sha256") != _sha(provenance_bytes)
                or saved.get("raw_output_sha256") != _sha(raw_bytes)
                or saved.get("manifest_sha256") != _sha(manifest_bytes)):
            raise ValueError("Rejection marker is incomplete or conflicts with this candidate; inspect it before continuing.")
        rejected = True
    return CandidateReview(root, candidate, image_bytes, chosen, job.prompt_id,
                           _sha(record_bytes), _sha(provenance_bytes), _sha(image_bytes),
                           _sha(raw_bytes), _sha(manifest_bytes), approved, rejected)


def approve_candidate(review: CandidateReview) -> Path:
    """Persist one exact reviewed approval; an interrupted marker fails closed."""
    if not isinstance(review, CandidateReview):
        raise ValueError("Review the saved candidate before approving it.")
    if review.approved or review.rejected:
        raise ValueError("This candidate already has a review decision.")
    current = load_candidate_review(review.project, review.directory, review.frame_number)
    if current.approved or current.rejected:
        raise ValueError("This candidate received a review decision in another window.")
    if current != review:
        raise ValueError("Candidate or source job changed since review; review it again.")
    approval = review.directory / "approval.json"
    if approval.is_symlink():
        raise ValueError("Approval marker is redirected.")
    _claim_decision(review.directory)
    record = {
        "schema": 1, "status": "approved_unassigned",
        "approved_utc": datetime.now(timezone.utc).isoformat(),
        "project": str(review.project), "frame_number": review.frame_number,
        "prompt_id": review.prompt_id,
        "candidate_sha256": review.image_sha256,
        "record_sha256": review.record_sha256,
        "provenance_sha256": review.provenance_sha256,
        "raw_output_sha256": review.raw_sha256,
        "manifest_sha256": review.manifest_sha256,
    }
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    # O_EXCL is the cross-process approval gate. Never remove a partial marker:
    # after a crash it must be investigated, never mistaken for approval.
    try:
        with approval.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ValueError("Approval marker appeared during approval; review the saved candidate again.") from exc
    return approval


def reject_candidate(review: CandidateReview) -> Path:
    """Record a non-destructive rejection of the exact reviewed candidate."""
    if not isinstance(review, CandidateReview):
        raise ValueError("Review the saved candidate before rejecting it.")
    if review.approved or review.rejected:
        raise ValueError("This candidate already has a review decision.")
    current = load_candidate_review(review.project, review.directory, review.frame_number)
    if current.approved or current.rejected:
        raise ValueError("This candidate received a review decision in another window.")
    if current != review:
        raise ValueError("Candidate or source job changed since review; review it again.")
    rejection = review.directory / "rejection.json"
    if rejection.is_symlink():
        raise ValueError("Rejection marker is redirected.")
    _claim_decision(review.directory)
    record = {
        "schema": 1, "status": "rejected",
        "rejected_utc": datetime.now(timezone.utc).isoformat(),
        "project": str(review.project), "frame_number": review.frame_number,
        "prompt_id": review.prompt_id,
        "candidate_sha256": review.image_sha256,
        "record_sha256": review.record_sha256,
        "provenance_sha256": review.provenance_sha256,
        "raw_output_sha256": review.raw_sha256,
        "manifest_sha256": review.manifest_sha256,
    }
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    try:
        with rejection.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ValueError("Rejection marker appeared during rejection; review the saved candidate again.") from exc
    return rejection


def _claim_decision(directory: Path) -> None:
    """Reserve the one review decision across windows; retain on interruption."""
    try:
        (directory / ".review-decision").mkdir()
    except FileExistsError as exc:
        raise ValueError("A review decision appeared in another window; review the candidate again.") from exc
