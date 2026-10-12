"""Durable single-job submission coordinator; call from a background worker.

The SQLite reservation is committed before submission. A write transaction then
serializes sending and recovery, including across processes. Recovery can only
release an unattempted job while holding that same transaction, so a sender must
recheck its reservation before sending. The shared GPU gate is in-process only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from reezsynth_comfy_jobs import MAX_REQUEST_BYTES, _read_bounded, load_job
from reezsynth_comfy_status import (
    JobObservation, TERMINAL, fetch_job_status, reconcile_observation,
)
from reezsynth_comfy_transport import submit_uploaded_job


@dataclass(frozen=True)
class SessionUpdate:
    status: str
    directory: str = ""
    error: str = ""


class ComfySession:
    """One durable reservation plus one token in the application's GPU gate.

    All instances for an application profile must use the same database path.
    Construction does no I/O; restore must run before enabling GPU actions.
    No method uploads, retries a prompt, cancels work, or controls a server.
    """

    def __init__(self, state_path, gpu_gate):
        self.path = Path(state_path).absolute()
        self.gate = gpu_gate
        self._token = None
        self._had_reservation = False
        self._mutex = threading.RLock()

    def _hold(self):
        if self._token is None:
            self._token = self.gate.acquire("ComfyUI generation or recovery")

    def _release(self):
        if self._token is not None:
            self.gate.release(self._token)
            self._token = None

    @contextmanager
    def _transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("ComfyUI recovery database must not be a symbolic link.")
        connection = sqlite3.connect(self.path, timeout=0)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE IF NOT EXISTS session (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
            yield connection
            connection.commit()
        finally:
            connection.close()  # Rolls back an interrupted transaction.

    @staticmethod
    def _read(connection):
        row = connection.execute("SELECT payload FROM session WHERE id=1").fetchone()
        if row is None:
            return None
        if not isinstance(row[0], str) or len(row[0]) > 64 * 1024:
            raise ValueError("ComfyUI recovery record is invalid.")
        record = json.loads(row[0])
        if (not isinstance(record, dict) or record.get("schema") != 1
                or record.get("resolution") not in {"active", "not_submitted", *TERMINAL}
                or any(not isinstance(record.get(key), str) or not record[key]
                       for key in ("reservation", "directory", "prompt_id", "client_id", "endpoint", "request_sha256"))):
            raise ValueError("ComfyUI recovery record is invalid.")
        if str(uuid.UUID(record["reservation"])) != record["reservation"]:
            raise ValueError("ComfyUI recovery reservation is invalid.")
        previous = record.get("observation")
        if previous is not None:
            observation = JobObservation(**previous)
            if observation.prompt_id != record["prompt_id"]:
                raise ValueError("ComfyUI recovery observation has a different owner.")
            reconcile_observation(None, observation)
        if record["resolution"] in TERMINAL:
            if previous is None or previous["status"] != record["resolution"]:
                raise ValueError("ComfyUI recovery completion has no verified observation.")
        return record

    @staticmethod
    def _write(connection, record):
        connection.execute("INSERT OR REPLACE INTO session(id, payload) VALUES (1, ?)",
                           (json.dumps(record, allow_nan=False),))

    @staticmethod
    def _matching_job(record):
        job = load_job(record["directory"])
        digest = hashlib.sha256(_read_bounded(job.directory / "submit.json", MAX_REQUEST_BYTES)).hexdigest()
        if ((job.prompt_id, job.client_id, job.endpoint, digest) !=
                (record["prompt_id"], record["client_id"], record["endpoint"], record["request_sha256"])):
            raise ValueError("The reserved ComfyUI job changed; recovery remains blocked.")
        return job

    def _update(self, record, error=""):
        if record is None:
            if self._had_reservation:
                return SessionUpdate("blocked", error="The reserved ComfyUI recovery record disappeared.")
            self._release()
            return SessionUpdate("idle", error=error)
        resolution = record["resolution"]
        if resolution != "active":
            self._had_reservation = False
            self._release()
            return SessionUpdate(resolution, record["directory"], error)
        self._had_reservation = True
        previous = record.get("observation")
        return SessionUpdate(previous["status"] if previous else "unknown", record["directory"], error)

    def restore(self):
        """Restore admission without network access or assuming a job has ended."""
        with self._mutex:
            if not self.path.exists() and not self.path.is_symlink():
                if self._token is not None:
                    return SessionUpdate("blocked", error="ComfyUI recovery database disappeared while a job was reserved.")
                return self._update(None)
            try:
                self._hold()
                with self._transaction() as connection:
                    record = self._read(connection)
                return self._update(record)
            except Exception as exc:
                return SessionUpdate("blocked", error=str(exc) or type(exc).__name__)

    def submit(self, directory, project):
        """Explicitly submit a prepared/uploaded job once, after durable admission."""
        with self._mutex:
            reserved = False
            record = None
            try:
                self._hold()
                with self._transaction() as connection:
                    record = self._read(connection)
                    if record is None and self._had_reservation:
                        raise ValueError("The reserved ComfyUI recovery record disappeared.")
                    if record is not None and record["resolution"] == "active":
                        return self._update(record, "Resolve the reserved job before starting another.")
                    if not str(project).strip():
                        raise ValueError("Choose an existing project before submitting its ComfyUI job.")
                    job = load_job(directory)
                    if job.directory.parent.parent.resolve(strict=True) != Path(project).resolve(strict=True):
                        raise ValueError("This ComfyUI job belongs to a different project.")
                    if job.attempted:
                        raise ValueError("This job has already been attempted; do not submit it again.")
                    record = {
                        "schema": 1, "reservation": str(uuid.uuid4()),
                        "directory": str(job.directory), "prompt_id": job.prompt_id,
                        "client_id": job.client_id, "endpoint": job.endpoint,
                        "request_sha256": hashlib.sha256(_read_bounded(job.directory / "submit.json", MAX_REQUEST_BYTES)).hexdigest(),
                        "resolution": "active", "observation": None,
                    }
                    self._write(connection, record)
                reserved = True  # Durably committed before any prompt request.
                self._had_reservation = True
                return self._send_reserved(record)
            except Exception as exc:
                # Database failures may hide an older reservation. Only a
                # successful recovery read can establish that admission is free.
                update = self.restore()
                if reserved or update.status not in {"idle", "not_submitted", *TERMINAL}:
                    return SessionUpdate("blocked", (record or {}).get("directory", ""),
                                         str(exc) or type(exc).__name__)
                return SessionUpdate("not_submitted", error=str(exc) or type(exc).__name__)

    def _send_reserved(self, record):
        error = ""
        with self._transaction() as connection:
            current = self._read(connection)
            if current != record:
                # Recovery may have safely cleared an unattempted reservation
                # between the durable commit and acquisition of this send lock.
                return self._update(current, "Reservation changed before submission; no prompt was sent.")
            try:
                job = self._matching_job(record)
                submit_uploaded_job(job.directory)
            except Exception as exc:
                error = str(exc) or type(exc).__name__
                try:
                    if not self._matching_job(record).attempted:
                        record["resolution"] = "not_submitted"
                except Exception:
                    pass  # Unreadable records cannot establish that no POST happened.
            self._write(connection, record)
        return self._update(record, error)

    def refresh(self):
        """Read the reserved job only; missing history never permits a retry."""
        with self._mutex:
            try:
                self._hold()
                if self._had_reservation and not self.path.exists():
                    return SessionUpdate("blocked", error="ComfyUI recovery database disappeared while a job was reserved.")
                with self._transaction() as connection:
                    record = self._read(connection)
                    if record is not None and record["resolution"] == "active":
                        job = self._matching_job(record)
                        if not job.attempted:
                            # This transaction excludes all session senders.
                            record["resolution"] = "not_submitted"
                        else:
                            previous = record.get("observation")
                            observation = reconcile_observation(
                                JobObservation(**previous) if previous else None,
                                fetch_job_status(job),
                            )
                            record["observation"] = asdict(observation)
                            if observation.status in TERMINAL:
                                record["resolution"] = observation.status
                        self._write(connection, record)
                return self._update(record)
            except Exception as exc:
                return SessionUpdate("blocked", error=str(exc) or type(exc).__name__)
