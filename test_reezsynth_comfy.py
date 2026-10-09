"""Dependency-light Keyframe Generator foundation tests; no GPU or ComfyUI install."""

import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from reezsynth_comfy_client import normalize_local_endpoint, parse_system_stats
from reezsynth_comfy_controls import ComfyKeyframeTab
from reezsynth_keyframe_candidates import import_candidate


class ConnectionTests(unittest.TestCase):
    def test_loopback_only_and_status_shape(self):
        self.assertEqual(
            normalize_local_endpoint("http://127.0.0.1:8188/"),
            "http://127.0.0.1:8188",
        )
        self.assertEqual(
            normalize_local_endpoint("http://[::1]:8190"),
            "http://[::1]:8190",
        )
        for address in (
            "http://example.com:8188", "http://192.168.1.20:8188",
            "https://127.0.0.1:8188", "http://127.0.0.1:8188/prompt",
            "http://user:pass@localhost:8188", "http://localhost:bad",
            "http://localhost:8188?secret=1",
            "http://localhost:0",
        ):
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    normalize_local_endpoint(address)
        status = parse_system_stats(json.dumps({
            "system": {"comfyui_version": "0.3.0"},
            "devices": [{"name": "GPU A"}],
        }).encode())
        self.assertEqual(status.version, "0.3.0")
        self.assertEqual(status.devices, ("GPU A",))
        with self.assertRaises(ValueError):
            parse_system_stats(b'{"unrelated": true}')


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.keys = self.project / "keys"
        self.keys.mkdir()
        self.source = self.root / "source.png"
        self.drawing = self.root / "drawing.png"
        self.generated = self.root / "generated.png"
        Image.new("RGBA", (12, 8), (10, 20, 30, 255)).save(self.source)
        Image.new("RGBA", (12, 8), (0, 0, 0, 0)).save(self.drawing)
        Image.new("RGBA", (12, 8), (255, 0, 0, 128)).save(self.generated)

    def test_native_candidate_is_unreviewed_and_never_replaces_key(self):
        key = self.keys / "frame_004.png"
        key.write_bytes(b"existing key")
        key_hash = hashlib.sha256(key.read_bytes()).hexdigest()
        result = import_candidate(
            self.project, 4, self.source, self.generated,
            mode="modify", drawing_image=self.drawing,
        )
        self.assertEqual((result.width, result.height), (12, 8))
        self.assertEqual(result.image_path.read_bytes(), self.generated.read_bytes())
        self.assertEqual(hashlib.sha256(key.read_bytes()).hexdigest(), key_hash)
        metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "unreviewed")
        self.assertEqual(metadata["frame_number"], 4)
        self.assertEqual(metadata["drawing"]["sha256"],
                         hashlib.sha256(self.drawing.read_bytes()).hexdigest())
        self.assertEqual(len(list(self.keys.iterdir())), 1)
        self.assertNotEqual(
            import_candidate(self.project, 4, self.source, self.generated,
                             mode="generate").image_path,
            result.image_path,
        )

    def test_mismatched_dimensions_or_missing_drawing_leave_no_candidate(self):
        Image.new("RGBA", (6, 8), (1, 2, 3, 4)).save(self.generated)
        with self.assertRaisesRegex(ValueError, "native source"):
            import_candidate(self.project, 4, self.source, self.generated,
                             mode="generate")
        with self.assertRaisesRegex(ValueError, "requires an existing drawing"):
            import_candidate(self.project, 4, self.source, self.generated,
                             mode="modify")
        self.assertFalse((self.project / ".reezsynth-candidates").exists())

    def test_jpeg_source_is_accepted_without_resizing_candidate(self):
        jpeg_source = self.root / "source.jpg"
        Image.new("RGB", (12, 8), (10, 20, 30)).save(jpeg_source)
        record = import_candidate(
            self.project, 9, jpeg_source, self.generated, mode="generate"
        )
        self.assertEqual((record.width, record.height), (12, 8))
        self.assertEqual(record.image_path.read_bytes(), self.generated.read_bytes())

    def test_oversize_warning_and_error_are_reported_without_writes(self):
        for limit in (80, 40):
            with self.subTest(limit=limit), patch.object(Image, "MAX_IMAGE_PIXELS", limit):
                with self.assertRaisesRegex(ValueError, "supported pixel limit"):
                    import_candidate(self.project, 4, self.source, self.generated,
                                     mode="generate")
            self.assertFalse((self.project / ".reezsynth-candidates").exists())

    def test_corrupt_png_crc_is_reported_without_writes(self):
        data = bytearray(self.generated.read_bytes())
        data[data.index(b"IDAT") + 4] ^= 1
        self.generated.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "damaged or incomplete"):
            import_candidate(self.project, 4, self.source, self.generated,
                             mode="generate")
        self.assertFalse((self.project / ".reezsynth-candidates").exists())


class TabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tab_does_not_connect_on_construction(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "prefs.ini"),
                                 QSettings.Format.IniFormat)
            class Parent:
                video = {7: Path(directory) / "source.png"}
                keys = {7: Path(directory) / "drawing.png"}
            # A QWidget parent is needed; the project context is attached to it.
            from PySide6.QtWidgets import QWidget
            parent = QWidget()
            parent.video = Parent.video
            parent.keys = Parent.keys
            tab = ComfyKeyframeTab(parent, settings)
            self.assertIsNone(tab.reply)
            tab.frame_number.setValue(7)
            tab.use_project_frame()
            self.assertEqual(tab.source.text(), str(parent.video[7]))
            self.assertEqual(tab.drawing.text(), str(parent.keys[7]))
            parent.video[8] = Path(directory) / "next.png"
            tab.frame_number.setValue(8)
            tab.use_project_frame()
            self.assertEqual(tab.source.text(), str(parent.video[8]))
            self.assertEqual(tab.drawing.text(), "")
            tab.mode.setCurrentIndex(1)
            self.assertFalse(tab.drawing_row.isHidden())
            tab.deleteLater()
            parent.deleteLater()

    def test_import_uses_selected_project_and_clears_failed_attempt(self):
        from PySide6.QtWidgets import QWidget, QLineEdit
        from reezsynth_gui import MainWindow
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "candidate.png"
            Image.new("RGBA", (12, 8), (0, 0, 0, 128)).save(image)
            parent = QWidget()
            parent.project_dir = QLineEdit(f'"{root}"')
            parent.path_value = lambda field: MainWindow.path_value(parent, field)
            settings = QSettings(str(root / "prefs.ini"), QSettings.Format.IniFormat)
            tab = ComfyKeyframeTab(parent, settings)
            tab.source.setText(str(image))
            tab.generated.setText(str(image))
            tab.import_for_review()
            self.assertIn("Unreviewed candidate", tab.candidate_status.text())
            saved = list((root / ".reezsynth-candidates").iterdir())
            self.assertEqual(len(saved), 2)
            parent.project_dir.setText("  ")
            with patch("reezsynth_comfy_controls.QMessageBox.warning") as warning:
                tab.import_for_review()
                warning.assert_called_once()
            self.assertIn("not imported", tab.candidate_status.text())
            self.assertEqual(tab.preview.text(), "Candidate preview")
            self.assertEqual(list((root / ".reezsynth-candidates").iterdir()), saved)
            tab.deleteLater()
            parent.deleteLater()

    def test_connection_check_reads_local_status_without_running_a_job(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                body = json.dumps({
                    "system": {"comfyui_version": "test-version"},
                    "devices": [{"name": "Test GPU"}],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as directory:
            from PySide6.QtWidgets import QWidget
            parent = QWidget()
            settings = QSettings(str(Path(directory) / "prefs.ini"),
                                 QSettings.Format.IniFormat)
            tab = ComfyKeyframeTab(parent, settings)
            tab.address.setText(f"http://127.0.0.1:{server.server_port}")
            tab.check_connection()
            deadline = time.monotonic() + 3
            while tab.reply is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertIsNone(tab.reply)
            self.assertEqual(requests, ["/system_stats"])
            self.assertIn("test-version", tab.connection_status.text())
            self.assertIn("Test GPU", tab.connection_status.text())
            tab.cancel_pending_check()
            tab.deleteLater()
            parent.deleteLater()
