"""One in-process GPU work lease shared by ReEzSynth worker entry points."""

from __future__ import annotations

import threading
import uuid


class GpuBusy(ValueError):
    """A different operation currently owns ReEzSynth's GPU work slot."""


class GpuAdmission:
    def __init__(self):
        self._mutex = threading.Lock()
        self._token = None
        self._owner = None

    @property
    def owner(self) -> str | None:
        with self._mutex:
            return self._owner

    def acquire(self, owner: str) -> uuid.UUID:
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("GPU work owner is required.")
        with self._mutex:
            if self._token is not None:
                raise GpuBusy(f"Wait for {self._owner} to finish before starting another GPU task.")
            self._token = uuid.uuid4()
            self._owner = owner
            return self._token

    def release(self, token: uuid.UUID) -> bool:
        """Only the exact owner token can release the active lease."""
        with self._mutex:
            if self._token is None or token != self._token:
                return False
            self._token = None
            self._owner = None
            return True
