"""Loopback-only ComfyUI connection helpers.

Inference, workflow selection and process ownership are deliberately separate
from this first connection/readiness slice.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ComfyStatus:
    version: str
    devices: tuple[str, ...]


def normalize_local_endpoint(value: str) -> str:
    """Accept only an HTTP loopback origin, with no credentials or URL path."""
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() != "http":
        raise ValueError("Use a local http:// ComfyUI address.")
    if parsed.username or parsed.password:
        raise ValueError("Credentials are not accepted in the ComfyUI address.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Enter the ComfyUI address without a path or query.")
    host = parsed.hostname
    if not host:
        raise ValueError("Enter a local ComfyUI address.")
    if host.casefold() != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError("Only a ComfyUI server on this PC is supported.")
        except ValueError as exc:
            if str(exc).startswith("Only a ComfyUI"):
                raise
            raise ValueError("Only a ComfyUI server on this PC is supported.") from exc
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The ComfyUI port is invalid.") from exc
    if port is None or port == 0:
        raise ValueError("Include the ComfyUI port, such as :8188.")
    normalized_host = f"[{host}]" if ":" in host else host.lower()
    return f"http://{normalized_host}:{port}"


def parse_system_stats(payload: bytes) -> ComfyStatus:
    """Read the small, read-only /system_stats response without guessing models."""
    if len(payload) > 1024 * 1024:
        raise ValueError("ComfyUI status response is unexpectedly large.")
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ComfyUI returned invalid status data.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("system"), dict):
        raise ValueError("This address did not return a ComfyUI status response.")
    system = data["system"]
    version = system.get("comfyui_version")
    if not isinstance(version, str) or not version:
        version = "unknown"
    version = version[:120]
    devices = data.get("devices", [])
    if not isinstance(devices, list):
        devices = []
    names = tuple(item["name"][:120] for item in devices[:8]
                  if isinstance(item, dict) and isinstance(item.get("name"), str))
    return ComfyStatus(version, names)
