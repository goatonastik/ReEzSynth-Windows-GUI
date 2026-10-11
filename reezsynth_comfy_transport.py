"""Bounded loopback transport for one frozen ComfyUI job.

Run from a worker, never the Qt thread. Uploads may be retried only before the
single prompt attempt; uncertain prompt POSTs are never retried automatically.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from reezsynth_comfy_binding import _UPLOAD
from reezsynth_comfy_jobs import (MAX_REQUEST_BYTES, MAX_SNAPSHOT_BYTES, _json_bytes,
                                 _read_bounded, _write_exclusive, claim_submission,
                                 load_job, record_receipt)


MAX_RECEIPT_BYTES = 64 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise ValueError("ComfyUI redirected the job request.")


def _timeout(value):
    if type(value) not in (int, float) or not 0 < value <= 30:
        raise ValueError("ComfyUI timeout must be between 0 and 30 seconds.")


def _opener():
    return build_opener(ProxyHandler({}), _NoRedirect())


def _read_response(opener, request, *, timeout, limit):
    with opener.open(request, timeout=timeout) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError("ComfyUI response exceeds its size limit.")
    return content


def _inventory(job):
    manifest = json.loads(_read_bounded(job.directory / "manifest.json", MAX_REQUEST_BYTES))
    metadata = manifest.get("metadata")
    uploads = metadata.get("uploads") if isinstance(metadata, dict) else None
    hashes = manifest.get("input_sha256")
    if (not isinstance(uploads, dict) or not isinstance(hashes, dict)
            or set(uploads) not in ({"inference.png"}, {"inference.png", "noise_mask.png"})
            or any(not isinstance(name, str) or not _UPLOAD.fullmatch(name)
                   or key not in hashes for key, name in uploads.items())):
        raise ValueError("Frozen upload inventory is invalid.")
    body = json.loads(_read_bounded(job.directory / "submit.json", MAX_REQUEST_BYTES))
    graph = body.get("prompt", {})
    if (not isinstance(graph, dict) or not isinstance(graph.get("4"), dict)
            or not isinstance(graph["4"].get("inputs"), dict)
            or graph["4"]["inputs"].get("image") != uploads["inference.png"]
            or ("noise_mask.png" in uploads and
                (not isinstance(graph.get("12"), dict)
                 or not isinstance(graph["12"].get("inputs"), dict)
                 or graph["12"]["inputs"].get("image") != uploads["noise_mask.png"]))):
        raise ValueError("Frozen graph and upload inventory disagree.")
    return uploads, hashes


def _snapshot(job, key, hashes):
    payload = _read_bounded(job.directory / "inputs" / key, MAX_SNAPSHOT_BYTES)
    if hashlib.sha256(payload).hexdigest() != hashes[key]:
        raise ValueError("Frozen upload bytes have changed.")
    return payload


def _server_bytes(job, name, opener, timeout):
    query = urlencode({"filename": name, "type": "input"})
    request = Request(f"{job.endpoint}/view?{query}", method="GET")
    return _read_response(opener, request, timeout=timeout, limit=MAX_SNAPSHOT_BYTES)


def _multipart(name, payload):
    boundary = "reezsynth" + uuid.uuid4().hex
    header = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
              f"filename=\"{name}\"\r\nContent-Type: image/png\r\n\r\n").encode("ascii")
    trailer = (f"\r\n--{boundary}\r\nContent-Disposition: form-data; "
               "name=\"type\"\r\n\r\ninput\r\n"
               f"--{boundary}--\r\n").encode("ascii")
    return f"multipart/form-data; boundary={boundary}", header + payload + trailer


def upload_job_inputs(directory: str | Path, *, timeout: float = 15.0) -> None:
    """Upload only frozen inputs, verifying each receipt and server-side bytes."""
    _timeout(timeout)
    job = load_job(directory)
    if job.attempted:
        raise ValueError("An attempted job cannot upload inputs again.")
    uploads, hashes = _inventory(job)
    opener = _opener()
    for key, name in uploads.items():
        payload = _snapshot(job, key, hashes)
        receipt_path = job.directory / f"upload-{key[:-4]}.json"
        if receipt_path.is_symlink():
            raise ValueError("Upload receipt redirects outside the job.")
        if receipt_path.exists():
            receipt = json.loads(_read_bounded(receipt_path, MAX_RECEIPT_BYTES))
            if receipt != {"name": name, "subfolder": "", "type": "input"}:
                raise ValueError("Stored upload receipt does not match this job.")
        else:
            content_type, content = _multipart(name, payload)
            request = Request(f"{job.endpoint}/upload/image", data=content, method="POST",
                              headers={"Content-Type": content_type, "Accept": "application/json"})
            response = _read_response(opener, request, timeout=timeout,
                                      limit=MAX_RECEIPT_BYTES)
            try:
                receipt = json.loads(response)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("ComfyUI returned an invalid upload receipt.") from exc
            if (not isinstance(receipt, dict) or receipt.get("name") != name
                    or receipt.get("subfolder") != "" or receipt.get("type") != "input"):
                raise ValueError("ComfyUI renamed or redirected an uploaded input.")
            # Do not persist success until GET confirms the bytes at that name.
            if hashlib.sha256(_server_bytes(job, name, opener, timeout)).hexdigest() != hashes[key]:
                raise ValueError("ComfyUI input bytes differ from the frozen snapshot.")
            _write_exclusive(receipt_path, _json_bytes({
                "name": name, "subfolder": "", "type": "input"}))


def submit_uploaded_job(directory: str | Path, *, timeout: float = 15.0):
    """Verify every server input and issue exactly one durable prompt attempt."""
    _timeout(timeout)
    job = load_job(directory)
    if job.attempted:
        raise ValueError("This job may already have been submitted; reconcile it first.")
    uploads, hashes = _inventory(job)
    opener = _opener()
    for key, name in uploads.items():
        receipt_path = job.directory / f"upload-{key[:-4]}.json"
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise ValueError("Upload every input before submitting this job.")
        receipt = json.loads(_read_bounded(receipt_path, MAX_RECEIPT_BYTES))
        if receipt != {"name": name, "subfolder": "", "type": "input"}:
            raise ValueError("Stored upload receipt does not match this job.")
        _snapshot(job, key, hashes)
        if hashlib.sha256(_server_bytes(job, name, opener, timeout)).hexdigest() != hashes[key]:
            raise ValueError("ComfyUI input bytes differ from the frozen snapshot.")
    content = claim_submission(job.directory)
    request = Request(f"{job.endpoint}/prompt", data=content, method="POST",
                      headers={"Content-Type": "application/json", "Accept": "application/json"})
    response = _read_response(opener, request, timeout=timeout, limit=MAX_RECEIPT_BYTES)
    return record_receipt(job.directory, response)
