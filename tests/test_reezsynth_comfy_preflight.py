"""Read-only ComfyUI capability checks before a one-attempt submission."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from reezsynth_comfy_preflight import check_graph_schema, preflight_graph


GRAPH = {
    "1": {"class_type": "UNETLoader", "inputs": {
        "unet_name": "qwen_image_edit_2511_fp8mixed.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {
        "model": ["1", 0], "shift": 3.1}},
}
SCHEMAS = {
    "UNETLoader": {"input": {"required": {
        "unet_name": [["qwen_image_edit_2511_fp8mixed.safetensors"]],
        "weight_dtype": [["default"]]}}, "output": ["MODEL"]},
    "ModelSamplingAuraFlow": {"input": {"required": {
        "model": ["MODEL"], "shift": ["FLOAT"]}}, "output": ["MODEL"]},
}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.server.paths.append(self.path)
        kind = self.path.removeprefix("/object_info/")
        if self.server.redirect:
            self.send_response(302)
            self.send_header("Location", "http://example.com/")
            self.end_headers()
            return
        body = json.dumps({kind: self.server.schemas.get(kind)}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.schemas = json.loads(json.dumps(SCHEMAS))
        self.server.paths = []
        self.server.redirect = False
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"

    def test_reads_only_referenced_node_schemas_and_accepts_matching_graph(self):
        self.assertEqual(preflight_graph(self.endpoint, GRAPH), 1)
        self.assertEqual(set(self.server.paths), {
            "/object_info/UNETLoader", "/object_info/ModelSamplingAuraFlow"})

    def test_missing_model_or_link_type_blocks_before_submission(self):
        self.server.schemas["UNETLoader"]["input"]["required"]["unet_name"] = [["other.safetensors"]]
        with self.assertRaisesRegex(ValueError, "no longer offers"):
            preflight_graph(self.endpoint, GRAPH)
        self.server.schemas = json.loads(json.dumps(SCHEMAS))
        self.server.schemas["UNETLoader"]["output"] = ["IMAGE"]
        with self.assertRaisesRegex(ValueError, "link type changed"):
            preflight_graph(self.endpoint, GRAPH)

    def test_missing_node_and_redirect_are_rejected(self):
        self.server.schemas.pop("ModelSamplingAuraFlow")
        with self.assertRaisesRegex(ValueError, "does not advertise"):
            preflight_graph(self.endpoint, GRAPH)
        self.server.redirect = True
        with self.assertRaisesRegex(ValueError, "redirected"):
            preflight_graph(self.endpoint, GRAPH)

    def test_nonlocal_server_rejected_without_request(self):
        with self.assertRaisesRegex(ValueError, "Only a ComfyUI server"):
            preflight_graph("http://example.com:8188", GRAPH)
        self.assertEqual(self.server.paths, [])

    def test_malformed_node_type_rejected_without_request(self):
        with self.assertRaisesRegex(ValueError, "invalid node types"):
            preflight_graph(self.endpoint, {"1": {"class_type": ["UNETLoader"]}})
        self.assertEqual(self.server.paths, [])

    def test_invalid_required_field_and_link_target_rejected(self):
        broken = json.loads(json.dumps(GRAPH))
        del broken["1"]["inputs"]["weight_dtype"]
        with self.assertRaisesRegex(ValueError, "input fields changed"):
            check_graph_schema(broken, SCHEMAS)
        broken = json.loads(json.dumps(GRAPH))
        broken["2"]["inputs"]["model"] = ["99", 0]
        with self.assertRaisesRegex(ValueError, "link type changed"):
            check_graph_schema(broken, SCHEMAS)


if __name__ == "__main__":
    unittest.main()
