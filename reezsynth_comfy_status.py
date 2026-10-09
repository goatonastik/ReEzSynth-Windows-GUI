"""Read-only, bounded observation of one externally owned ComfyUI job.

Call fetch_job_status from a worker, never from the Qt UI thread. It never
submits, cancels, clears, or otherwise mutates a backend. A missing response
does not prove that an uncertain submission failed.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from reezsynth_comfy_jobs import JobRecord, MAX_REQUEST_BYTES


MAX_STATUS_BYTES = MAX_REQUEST_BYTES + 16 * 1024 * 1024
STATUSES = frozenset({"pending", "in_progress", "completed", "failed", "cancelled"})
TERMINAL = frozenset({"completed", "failed", "cancelled"})


@dataclass(frozen=True)
class JobObservation:
    prompt_id: str
    status: str  # unknown, pending, in_progress, completed, failed, cancelled
    ownership_verified: bool
    outputs_present: bool


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise ValueError("ComfyUI redirected the job-status request.")


def _reject_constant(value: str) -> None:
    raise ValueError("ComfyUI status contained an invalid number.")


def parse_job_status(job: JobRecord, payload: bytes) -> JobObservation:
    """Interpret only this job's bounded API response, never a whole queue."""
    if not job.attempted:
        raise ValueError("This job has not been submitted.")
    if len(payload) > MAX_STATUS_BYTES:
        raise ValueError("ComfyUI job-status response is too large.")
    try:
        data = json.loads(payload, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("ComfyUI returned invalid job-status data.") from exc
    if not isinstance(data, dict) or data.get("id") != job.prompt_id:
        raise ValueError("ComfyUI returned status for a different job.")
    status = data.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError("ComfyUI returned an unknown job status.")
    if status not in TERMINAL:
        # The normalized queue response omits extra_data. An exact UUID match
        # is informative, but terminal identity must later be verified.
        return JobObservation(job.prompt_id, status, False, False)
    workflow = data.get("workflow")
    extra = workflow.get("extra_data") if isinstance(workflow, dict) else None
    if (not isinstance(extra, dict)
            or extra.get("reezsynth_job_id") != job.prompt_id
            or extra.get("client_id") != job.client_id
            or extra.get("reezsynth_endpoint") != job.endpoint):
        raise ValueError("Terminal job ownership could not be verified.")
    outputs = data.get("outputs")
    if outputs is not None and not isinstance(outputs, dict):
        raise ValueError("ComfyUI job outputs have an invalid shape.")
    return JobObservation(job.prompt_id, status, True, bool(outputs))


def reconcile_observation(previous: JobObservation | None,
                          current: JobObservation) -> JobObservation:
    """Never regress a known running or terminal state on stale/missing reads."""
    if current.status not in STATUSES | {"unknown"}:
        raise ValueError("Unknown observed job status.")
    if previous is None:
        if current.status in TERMINAL and not current.ownership_verified:
            raise ValueError("Terminal job ownership could not be verified.")
        return current
    if previous.prompt_id != current.prompt_id:
        raise ValueError("Observations belong to different jobs.")
    if previous.status in TERMINAL:
        if current.status in TERMINAL and current.status != previous.status:
            raise ValueError("Contradictory terminal status for the same job.")
        if current.status == previous.status:
            if not current.ownership_verified:
                raise ValueError("Terminal job ownership could not be verified.")
            return JobObservation(previous.prompt_id, previous.status, True,
                                  previous.outputs_present or current.outputs_present)
        return previous
    if current.status == "unknown":
        return previous
    if current.status in TERMINAL and not current.ownership_verified:
        raise ValueError("Terminal job ownership could not be verified.")
    if previous.status == "in_progress" and current.status == "pending":
        return previous
    return current


def fetch_job_status(job: JobRecord, *, timeout: float = 5.0) -> JobObservation:
    """GET only /api/jobs/<id> on the validated loopback origin.

    A 404 is unknown: history eviction, restart, a transient queue transition
    and an unsupported route cannot be distinguished by that response alone.
    Other network errors propagate so callers preserve the last known state.
    """
    if not job.attempted:
        raise ValueError("This job has not been submitted.")
    if not (0 < timeout <= 30):
        raise ValueError("The ComfyUI request timeout is invalid.")
    # JobRecord is returned by the validated journal. Recheck an externally
    # constructed instance too, so the transport cannot be redirected outward.
    from reezsynth_comfy_client import normalize_local_endpoint
    origin = normalize_local_endpoint(job.endpoint)
    try:
        if str(uuid.UUID(job.prompt_id)) != job.prompt_id:
            raise ValueError("ComfyUI job identifier is invalid.")
    except (AttributeError, ValueError) as exc:
        raise ValueError("ComfyUI job identifier is invalid.") from exc
    request = Request(f"{origin}/api/jobs/{job.prompt_id}", method="GET",
                      headers={"Accept": "application/json"})
    opener = build_opener(ProxyHandler({}), _RejectRedirects())
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = response.read(MAX_STATUS_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 404:
            exc.close()
            return JobObservation(job.prompt_id, "unknown", False, False)
        exc.close()
        raise
    return parse_job_status(job, payload)
