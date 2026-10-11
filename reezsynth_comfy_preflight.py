"""Read-only capability check for a frozen experimental ComfyUI graph.

This checks advertised node interfaces and selected model filenames. It cannot
prove model contents, free VRAM, inference quality, or acceptance by /prompt.
"""

from __future__ import annotations

import json
from urllib.parse import quote
from urllib.request import Request

from reezsynth_comfy_client import normalize_local_endpoint
from reezsynth_comfy_transport import _opener, _read_response, _timeout


MAX_NODE_INFO_BYTES = 1024 * 1024


def check_graph_schema(graph: dict, node_info: dict) -> int:
    """Reject missing nodes, incompatible links, inputs, and model selections."""
    if not isinstance(graph, dict) or not graph:
        raise ValueError("The frozen ComfyUI graph is empty or invalid.")
    if not isinstance(node_info, dict):
        raise ValueError("ComfyUI node information is invalid.")
    links = 0
    for node_id, node in graph.items():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str):
            raise ValueError(f"ComfyUI graph node {node_id} is invalid.")
        kind = node["class_type"]
        info = node_info.get(kind)
        if not isinstance(info, dict) or not isinstance(info.get("input"), dict):
            raise ValueError(f"ComfyUI does not advertise required node {kind}.")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise ValueError(f"ComfyUI graph node {node_id} has invalid inputs.")
        schema = info["input"]
        required = schema.get("required", {})
        optional = schema.get("optional", {})
        if not isinstance(required, dict) or not isinstance(optional, dict):
            raise ValueError(f"ComfyUI advertised invalid inputs for {kind}.")
        fields = required | optional
        if not set(required) <= set(inputs) or not set(inputs) <= set(fields):
            raise ValueError(f"ComfyUI input fields changed for {kind}.")
        for field, value in inputs.items():
            spec = fields[field]
            if not isinstance(spec, list) or not spec:
                raise ValueError(f"ComfyUI advertised invalid {kind}.{field}.")
            expected = spec[0]
            if isinstance(value, list):
                if len(value) != 2 or not isinstance(value[0], str) or type(value[1]) is not int:
                    raise ValueError(f"ComfyUI graph link {kind}.{field} is invalid.")
                upstream = graph.get(value[0])
                upstream_info = node_info.get(upstream.get("class_type")) if isinstance(upstream, dict) else None
                outputs = upstream_info.get("output") if isinstance(upstream_info, dict) else None
                if (not isinstance(outputs, list) or value[1] < 0 or value[1] >= len(outputs)
                        or outputs[value[1]] != expected):
                    raise ValueError(f"ComfyUI link type changed for {kind}.{field}.")
                links += 1
            elif isinstance(expected, list):
                # Upload filenames are not in LoadImage's menu before upload.
                if kind in {"LoadImage", "LoadImageMask"} and field == "image":
                    continue
                if value not in expected:
                    raise ValueError(f"ComfyUI no longer offers {kind}.{field}={value}.")
            elif expected == "COMBO":
                options = spec[1].get("options") if len(spec) > 1 and isinstance(spec[1], dict) else None
                if not isinstance(options, list) or value not in options:
                    raise ValueError(f"ComfyUI no longer offers {kind}.{field}={value}.")
            elif expected in {"INT", "FLOAT"}:
                if type(value) not in (int, float) or (expected == "INT" and type(value) is not int):
                    raise ValueError(f"ComfyUI expects a different value for {kind}.{field}.")
            elif expected == "BOOLEAN" and type(value) is not bool:
                raise ValueError(f"ComfyUI expects a different value for {kind}.{field}.")
            elif expected == "STRING" and not isinstance(value, str):
                raise ValueError(f"ComfyUI expects a different value for {kind}.{field}.")
    return links


def preflight_graph(endpoint: str, graph: dict, *, timeout: float = 15.0) -> int:
    """GET only the referenced node schemas from a loopback ComfyUI server."""
    origin = normalize_local_endpoint(endpoint)
    _timeout(timeout)
    if not isinstance(graph, dict) or not graph:
        raise ValueError("The frozen ComfyUI graph is empty or invalid.")
    if any(not isinstance(node, dict) or not isinstance(node.get("class_type"), str)
           for node in graph.values()):
        raise ValueError("The frozen ComfyUI graph has invalid node types.")
    kinds = {node["class_type"] for node in graph.values()}
    if len(kinds) > 32:
        raise ValueError("The frozen ComfyUI graph has invalid node types.")
    opener = _opener()
    infos = {}
    for kind in sorted(kinds):
        if not isinstance(kind, str) or not kind or len(kind) > 120:
            raise ValueError("The frozen ComfyUI graph has an invalid node type.")
        request = Request(f"{origin}/object_info/{quote(kind, safe='')}", method="GET")
        payload = _read_response(opener, request, timeout=timeout, limit=MAX_NODE_INFO_BYTES)
        try:
            data = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"ComfyUI returned invalid node information for {kind}.") from exc
        infos[kind] = data.get(kind) if isinstance(data, dict) else None
    return check_graph_schema(graph, infos)
