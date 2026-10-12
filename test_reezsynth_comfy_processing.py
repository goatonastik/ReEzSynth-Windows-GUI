"""Native-size protected preview and unreviewed-candidate integration tests."""

import hashlib
import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from reezsynth_comfy_controls import (
    ComfyKeyframeTab, _prepare_owned_for_project, _save_owned_for_project,
    _upload_owned_for_project,
)
from reezsynth_comfy_jobs import prepare_job
from reezsynth_comfy_processing import (
    PreviewRequest, prepare_preview, preview_dark_strokes, save_enforced_candidate,
)
from reezsynth_keyframe_protection import AlphaPolicy, EditIntent
from test_reezsynth_gui import GuiFixture


class ProcessingFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.keys = self.project / "keys"
        self.keys.mkdir()
        self.key = self.keys / "frame_000007.png"
        self.key.write_bytes(b"numbered original must survive")
        self.key_hash = hashlib.sha256(self.key.read_bytes()).hexdigest()
        self.files = {}
        drawing = np.zeros((8, 12, 4), dtype=np.uint8)
        drawing[..., :3] = [7, 11, 13]
        drawing[3, 3] = [0, 0, 0, 128]
        drawing[3, 4] = [255, 255, 255, 255]
        drawing[3, 5] = [120, 0, 0, 255]
        raw = np.full_like(drawing, 220)
        raw[..., 3] = 255
        edit = np.full((8, 12), 255, dtype=np.uint8)
        protect = np.zeros((8, 12), dtype=np.uint8)
        protect[3, 3:6] = 255
        for name, pixels in (
            ("source", np.full_like(drawing, 40)), ("drawing", drawing),
            ("raw", raw), ("edit_mask", edit), ("protection_mask", protect),
        ):
            path = self.root / f"{name}.png"
            Image.fromarray(pixels).save(path)
            self.files[name] = path
        self.request = PreviewRequest(
            7, *(str(self.files[name]) for name in
                 ("source", "drawing", "raw", "edit_mask", "protection_mask")),
            EditIntent.REGION_DETAIL.value, AlphaPolicy.PRESERVE.value, 0,
        )

class ProcessingTests(ProcessingFixture, unittest.TestCase):
    def test_owned_job_from_another_project_is_rejected_before_preview_or_save(self):
        other = self.root / "other-project"
        other.mkdir()
        job = prepare_job(self.project, endpoint="http://127.0.0.1:8188",
                          request={"prompt": {"1": {"class_type": "SaveImage", "inputs": {}}}},
                          snapshots={"source.png": b"frozen-fixture"})
        with patch("reezsynth_comfy_controls.prepare_job_candidate") as prepare:
            with self.assertRaisesRegex(ValueError, "different project"):
                _prepare_owned_for_project(job.directory, str(other))
            prepare.assert_not_called()
        with patch("reezsynth_comfy_controls.save_job_candidate") as save:
            with self.assertRaisesRegex(ValueError, "different project"):
                _save_owned_for_project(job.directory, str(other), object())
            save.assert_not_called()
        with patch("reezsynth_comfy_controls.upload_job_inputs") as upload:
            with self.assertRaisesRegex(ValueError, "different project"):
                _upload_owned_for_project(job.directory, str(other))
            upload.assert_not_called()
            loaded = _upload_owned_for_project(job.directory, str(self.project))
            upload.assert_called_once_with(job.directory)
            self.assertFalse(loaded.attempted)

    def test_preview_and_save_preserve_native_pixels_and_metadata(self):
        result = prepare_preview(self.request)
        self.assertEqual((result.width, result.height), (12, 8))
        self.assertEqual(result.report.protected_mismatches, 0)
        with Image.open(BytesIO(result.image_png)) as image:
            final = np.array(image)
        with Image.open(self.files["drawing"]) as image:
            drawing = np.array(image)
        np.testing.assert_array_equal(final[3, 3:6], drawing[3, 3:6])
        np.testing.assert_array_equal(final[..., 3], drawing[..., 3])
        self.assertEqual(set(result.views), {
            "Source", "Drawing", "Raw candidate", "Enforced preview",
            "Edit mask", "Protected band", "Alpha",
        })
        with Image.open(BytesIO(result.views["Enforced preview"])) as thumbnail:
            self.assertLessEqual(max(thumbnail.size), 500)
        record = save_enforced_candidate(str(self.project), result)
        self.assertEqual(record.image_path.read_bytes(), result.image_png)
        metadata = json.loads(record.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "unreviewed")
        self.assertEqual(metadata["edit_intent"], EditIntent.REGION_DETAIL.value)
        self.assertEqual(metadata["inputs"]["protection_mask"]["sha256"],
                         result.input_hashes["protection_mask"])
        self.assertEqual(metadata["protection_radius"], 0)
        self.assertEqual(hashlib.sha256(self.key.read_bytes()).hexdigest(), self.key_hash)
        self.assertEqual(list(self.keys.iterdir()), [self.key])

    def test_invalid_masks_and_changed_inputs_cannot_publish(self):
        Image.new("RGB", (12, 8), "white").save(self.files["edit_mask"])
        with self.assertRaisesRegex(ValueError, "8-bit grayscale"):
            prepare_preview(self.request)
        Image.new("L", (6, 8), 255).save(self.files["edit_mask"])
        with self.assertRaisesRegex(ValueError, "native dimensions"):
            prepare_preview(self.request)
        Image.new("L", (12, 8), 255).save(self.files["edit_mask"])
        result = prepare_preview(self.request)
        Image.new("L", (12, 8), 0).save(self.files["edit_mask"])
        with self.assertRaisesRegex(ValueError, "changed since preview"):
            save_enforced_candidate(str(self.project), result)
        self.assertFalse((self.project / ".reezsynth-candidates").exists())

    def test_raw_candidate_requires_png(self):
        Image.new("RGB", (12, 8), "white").save(self.files["raw"], format="JPEG")
        with self.assertRaisesRegex(ValueError, "Unsupported image format"):
            prepare_preview(self.request)
        self.assertFalse((self.project / ".reezsynth-candidates").exists())

    def test_stroke_proposal_is_not_applied_or_published(self):
        suggested = preview_dark_strokes(str(self.files["drawing"]))
        with Image.open(BytesIO(suggested)) as image:
            mask = np.array(image)
        self.assertEqual(mask[3, 3], 255)
        self.assertEqual(mask[3, 4], 0)
        self.assertEqual(mask[3, 5], 0)
        self.assertFalse((self.project / ".reezsynth-candidates").exists())

    def test_mask_overlap_and_alpha_edit_only_within_selected_region(self):
        Image.new("L", (12, 8), 255).save(self.files["edit_mask"])
        editable = np.zeros((8, 12), dtype=np.uint8)
        editable[0, 0] = 255
        Image.fromarray(editable).save(self.files["edit_mask"])
        request = PreviewRequest(
            7, *(str(self.files[name]) for name in
                 ("source", "drawing", "raw", "edit_mask", "protection_mask")),
            EditIntent.CUSTOM.value, AlphaPolicy.EDIT.value, 0,
        )
        result = prepare_preview(request)
        self.assertEqual(result.report.editable_pixels, 1)
        self.assertEqual(result.report.alpha_changed_pixels, 1)

    def test_protection_radius_is_applied_to_result_and_metadata(self):
        result = prepare_preview(replace(self.request, protection_radius=1))
        with Image.open(BytesIO(result.image_png)) as image:
            final = np.array(image)
        with Image.open(self.files["drawing"]) as image:
            drawing = np.array(image)
        np.testing.assert_array_equal(final[2, 2:7], drawing[2, 2:7])
        self.assertEqual(result.report.protected_pixels, 15)
        with Image.open(BytesIO(result.views["Protected band"])) as image:
            mask = np.array(image)
        self.assertEqual(mask[2, 2], 255)
        record = save_enforced_candidate(str(self.project), result)
        metadata = json.loads(record.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["protection_radius"], 1)

    def test_changed_file_during_processing_is_rejected(self):
        import reezsynth_comfy_processing as processing
        actual_compose = processing.compose_modified

        def mutate_raw(*args, **kwargs):
            value = actual_compose(*args, **kwargs)
            Image.new("RGBA", (12, 8), (1, 2, 3, 4)).save(self.files["raw"])
            return value

        with patch.object(processing, "compose_modified", side_effect=mutate_raw):
            with self.assertRaisesRegex(ValueError, "Raw changed during preview"):
                prepare_preview(self.request)
        self.assertFalse((self.project / ".reezsynth-candidates").exists())

    def test_existing_candidate_folder_with_different_case_is_accepted(self):
        (self.project / ".ReEzSynth-Candidates").mkdir()
        result = prepare_preview(self.request)
        record = save_enforced_candidate(str(self.project), result)
        self.assertTrue(record.image_path.is_file())


class TabIntegrationTests(ProcessingFixture, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_prepare_job_uses_background_worker_and_frozen_frame(self):
        parent = QWidget()
        parent.project_dir = QLineEdit(str(self.project))
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        tab.source.setText(str(self.files["source"]))
        tab.frame_number.setValue(97)
        tab.qwen_prompt.setText("Pencil drawing")
        tab.vision_ack.setChecked(True)
        prepared = SimpleNamespace(directory=self.project / ".reezsynth-candidates" / "comfy-job-example")
        with patch("reezsynth_comfy_controls.prepare_qwen_job", return_value=prepared) as worker:
            tab.prepare_new_job()
            self.assertFalse(tab.prepare_button.isEnabled())
            deadline = time.monotonic() + 5
            while tab._worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
        self.assertIsNone(tab._worker)
        request = worker.call_args.args[0]
        self.assertEqual(request.intended_frame_number, 97)
        self.assertEqual(request.source_path, str(self.files["source"]))
        self.assertEqual(request.mode, "generate")
        self.assertEqual(tab.owned_job.text(), str(prepared.directory))
        self.assertIn("No upload or submission occurred", tab.prepare_status.text())
        tab.deleteLater()
        parent.deleteLater()

    def test_upload_uses_saved_job_and_never_submits(self):
        parent = QWidget()
        parent.project_dir = QLineEdit(str(self.project))
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        directory = self.project / ".reezsynth-candidates" / "comfy-job-example"
        tab.owned_job.setText(str(directory))
        result = SimpleNamespace(directory=directory, endpoint="http://127.0.0.1:8188")
        with patch("reezsynth_comfy_controls._upload_owned_for_project", return_value=result) as upload:
            tab.upload_owned_job()
            self.assertFalse(tab.owned_upload_button.isEnabled())
            deadline = time.monotonic() + 5
            while tab._worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
        self.assertIsNone(tab._worker)
        upload.assert_called_once_with(str(directory), str(self.project.resolve()))
        self.assertTrue(tab.owned_upload_button.isEnabled())
        self.assertIn("No inference started", tab.owned_status.text())
        tab.deleteLater()
        parent.deleteLater()

    def test_upload_reports_original_job_when_selection_changes(self):
        import threading
        parent = QWidget()
        parent.project_dir = QLineEdit(str(self.project))
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        original = self.project / ".reezsynth-candidates" / "comfy-job-original"
        tab.owned_job.setText(str(original))
        release = threading.Event()
        started = threading.Event()
        def delayed(*_):
            started.set()
            release.wait(2)
            return SimpleNamespace(directory=original, endpoint="http://127.0.0.1:8188")
        with patch("reezsynth_comfy_controls._upload_owned_for_project", side_effect=delayed):
            tab.upload_owned_job()
            self.assertTrue(started.wait(2))
            tab.owned_job.setText(str(original) + "-other")
            release.set()
            deadline = time.monotonic() + 5
            while tab._worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
        self.assertIsNone(tab._worker)
        self.assertIn(str(original), tab.owned_status.text())
        self.assertIn("selection changed", tab.owned_status.text())
        tab.deleteLater()
        parent.deleteLater()

    def test_modify_tab_passes_protected_inputs_and_shows_denoise(self):
        parent = QWidget()
        parent.project_dir = QLineEdit(str(self.project))
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        self.assertFalse(tab.qwen_form.isRowVisible(tab.qwen_denoise_row))
        tab.mode.setCurrentIndex(1)
        self.assertTrue(tab.qwen_form.isRowVisible(tab.qwen_denoise_row))
        tab.source.setText(str(self.files["source"]))
        tab.drawing.setText(str(self.files["drawing"]))
        tab.edit_mask.setText(str(self.files["edit_mask"]))
        tab.protection_mask.setText(str(self.files["protection_mask"]))
        tab.radius.setValue(2)
        tab.frame_number.setValue(97)
        tab.qwen_prompt.setText("Refine strokes inside the edit mask")
        tab.vision_ack.setChecked(True)
        prepared = SimpleNamespace(directory=self.project / ".reezsynth-candidates" / "comfy-job-modify")
        with patch("reezsynth_comfy_controls.prepare_qwen_job", return_value=prepared) as worker:
            tab.prepare_new_job()
            deadline = time.monotonic() + 5
            while tab._worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
        self.assertIsNone(tab._worker)
        request = worker.call_args.args[0]
        self.assertEqual(request.mode, "modify")
        self.assertEqual(request.intended_frame_number, 97)
        self.assertEqual(request.drawing_path, str(self.files["drawing"]))
        self.assertEqual(request.edit_mask_path, str(self.files["edit_mask"]))
        self.assertEqual(request.protection_mask_path, str(self.files["protection_mask"]))
        self.assertEqual(request.background, (255, 255, 255))
        self.assertEqual(request.denoise, .5)
        self.assertEqual(request.protection_radius, 2)
        self.assertEqual(request.alpha_policy, AlphaPolicy.PRESERVE.value)
        self.assertEqual(request.intent, EditIntent.REFINE_STROKES.value)
        self.assertTrue(tab.prepare_status.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse)
        tab.mode.setCurrentIndex(0)
        self.assertFalse(tab.qwen_form.isRowVisible(tab.qwen_denoise_row))
        self.assertEqual(tab.qwen_denoise.value(), 1)
        tab.deleteLater()
        parent.deleteLater()

    def test_prepare_job_changed_inputs_still_reports_record_without_binding_it(self):
        import threading
        parent = QWidget()
        parent.project_dir = QLineEdit(str(self.project))
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        tab.source.setText(str(self.files["source"]))
        tab.frame_number.setValue(97)
        tab.qwen_prompt.setText("Pencil drawing")
        tab.vision_ack.setChecked(True)
        release = threading.Event()
        prepared = SimpleNamespace(directory=self.project / ".reezsynth-candidates" / "comfy-job-old")
        def delayed(_):
            release.wait(2)
            return prepared
        with patch("reezsynth_comfy_controls.prepare_qwen_job", side_effect=delayed):
            tab.prepare_new_job()
        tab.frame_number.setValue(98)
        release.set()
        deadline = time.monotonic() + 5
        while tab._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(tab._worker)
        self.assertEqual(tab.owned_job.text(), "")
        self.assertIn("frame 97", tab.prepare_status.text())
        self.assertIn(str(prepared.directory), tab.prepare_status.text())
        tab.deleteLater()
        parent.deleteLater()

    def test_owned_job_preview_and_save_are_background_and_unassigned(self):
        parent = QWidget()
        parent.project_dir = QLineEdit(str(self.project))
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        preview = SimpleNamespace(image_png=self.files["drawing"].read_bytes(),
                                  raw_output_png=self.files["raw"].read_bytes())
        views = {"Enforced native candidate": preview.image_png,
                 "Raw model output (includes padding)": preview.raw_output_png}
        job_path = self.project / ".reezsynth-candidates" / "comfy-job-example"
        tab.owned_job.setText(str(job_path))
        with patch("reezsynth_comfy_controls._prepare_owned_for_project",
                   return_value=(preview, views)) as prepare:
            tab.preview_owned_job()
            self.assertFalse(tab.owned_preview_button.isEnabled())
            deadline = time.monotonic() + 5
            while tab._worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
        self.assertIsNone(tab._worker)
        prepare.assert_called_once_with(str(job_path), str(self.project.resolve()))
        self.assertIs(tab.owned_result, preview)
        self.assertTrue(tab.owned_save_button.isEnabled())
        self.assertEqual(tab.view.currentText(), "Enforced native candidate")
        self.assertFalse(tab.preview.pixmap().isNull())
        saved = SimpleNamespace(image_path=self.project / "unreviewed" / "candidate.png")
        with patch("reezsynth_comfy_controls._save_owned_for_project",
                   return_value=saved) as save:
            tab.save_owned_job()
            deadline = time.monotonic() + 5
            while tab._worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
        save.assert_called_once_with(str(job_path), str(self.project.resolve()), preview)
        self.assertIn("Unreviewed result saved", tab.owned_status.text())
        self.assertFalse(tab.owned_save_button.isEnabled())
        self.assertEqual(hashlib.sha256(self.key.read_bytes()).hexdigest(), self.key_hash)
        tab.owned_job.setText(str(job_path) + "-other")
        self.assertIsNone(tab.owned_result)
        self.assertFalse(tab.owned_save_button.isEnabled())
        tab.deleteLater()
        parent.deleteLater()


    def test_owned_job_change_during_worker_discards_stale_preview(self):
        import threading
        parent = QWidget()
        parent.project_dir = QLineEdit(str(self.project))
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        tab.owned_job.setText("old-job")
        release = threading.Event()
        def delayed(*_):
            release.wait(2)
            return SimpleNamespace(image_png=b"", raw_output_png=b""), {}
        with patch("reezsynth_comfy_controls._prepare_owned_for_project", side_effect=delayed):
            tab.preview_owned_job()
        tab.owned_job.setText("new-job")
        release.set()
        deadline = time.monotonic() + 5
        while tab._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(tab.owned_result)
        self.assertFalse(tab.owned_save_button.isEnabled())
        self.assertIn("changed during preview", tab.owned_status.text())
        tab.deleteLater()
        parent.deleteLater()

    def test_owned_preview_is_invalidated_when_project_changes(self):
        parent = QWidget()
        parent.project_dir = QLineEdit(str(self.project))
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        tab.owned_result = object()
        tab.owned_save_button.setEnabled(True)
        parent.project_dir.setText(str(self.root))
        self.assertIsNone(tab.owned_result)
        self.assertFalse(tab.owned_save_button.isEnabled())
        with patch("reezsynth_comfy_controls._save_owned_for_project") as save:
            tab.save_owned_job()
            save.assert_not_called()
        tab.deleteLater()
        parent.deleteLater()

    def test_three_choices_background_preview_and_save(self):
        parent = QWidget()
        parent.project_dir = QLineEdit(str(self.project))
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        self.assertTrue(tab.edit_mask_row.isHidden())
        self.assertTrue(tab.enforce_button.isHidden())
        tab.mode.setCurrentIndex(1)
        self.assertEqual(tab.intent.count(), 3)
        self.assertFalse(tab.edit_mask_row.isHidden())
        tab.frame_number.setValue(7)
        for name, field in (("source", tab.source), ("drawing", tab.drawing),
                            ("raw", tab.generated), ("edit_mask", tab.edit_mask),
                            ("protection_mask", tab.protection_mask)):
            field.setText(str(self.files[name]))
        tab.preview_enforced()
        deadline = time.monotonic() + 5
        while tab._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(tab._worker)
        self.assertIsNotNone(tab.current_result)
        self.assertIn("protected", tab.candidate_status.text())
        self.assertTrue(tab.save_button.isEnabled())
        tab.view.setCurrentText("Raw candidate")
        tab.background.setCurrentText("Dark")
        self.assertFalse(tab.preview.pixmap().isNull())
        tab.save_enforced()
        deadline = time.monotonic() + 5
        while tab._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIn("Unreviewed enforced candidate saved", tab.candidate_status.text())
        self.assertFalse(tab.save_button.isEnabled())
        tab.frame_number.setValue(8)
        self.assertFalse(tab.save_button.isEnabled())
        tab.deleteLater()
        parent.deleteLater()

    def test_input_change_while_worker_runs_discards_stale_result(self):
        import threading
        parent = QWidget()
        parent.project_dir = QLineEdit(str(self.project))
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        tab.mode.setCurrentIndex(1)
        tab.frame_number.setValue(7)
        for name, field in (("source", tab.source), ("drawing", tab.drawing),
                            ("raw", tab.generated), ("edit_mask", tab.edit_mask),
                            ("protection_mask", tab.protection_mask)):
            field.setText(str(self.files[name]))
        release = threading.Event()
        actual_prepare = prepare_preview

        def delayed(request):
            release.wait(2)
            return actual_prepare(request)

        with patch("reezsynth_comfy_controls.prepare_preview", side_effect=delayed):
            tab.preview_enforced()
        tab.frame_number.setValue(8)
        release.set()
        deadline = time.monotonic() + 5
        while tab._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(tab.current_result)
        self.assertFalse(tab.save_button.isEnabled())
        self.assertIn("Inputs changed", tab.candidate_status.text())
        tab.deleteLater()
        parent.deleteLater()

    def test_preview_does_not_require_a_project_until_save(self):
        parent = QWidget()
        parent.project_dir = QLineEdit("")
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        tab.mode.setCurrentIndex(1)
        for name, field in (("source", tab.source), ("drawing", tab.drawing),
                            ("raw", tab.generated), ("edit_mask", tab.edit_mask),
                            ("protection_mask", tab.protection_mask)):
            field.setText(str(self.files[name]))
        tab.preview_enforced()
        deadline = time.monotonic() + 5
        while tab._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNotNone(tab.current_result)
        parent.project_dir.setText(str(self.project))
        tab.save_enforced()
        deadline = time.monotonic() + 5
        while tab._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIn("Unreviewed enforced candidate saved", tab.candidate_status.text())
        tab.deleteLater()
        parent.deleteLater()

    def test_raw_import_invalidates_earlier_enforced_save(self):
        parent = QWidget()
        parent.project_dir = QLineEdit(str(self.project))
        parent.path_value = lambda field: str(Path(field.text()).resolve())
        settings = QSettings(str(self.root / "prefs.ini"), QSettings.Format.IniFormat)
        tab = ComfyKeyframeTab(parent, settings)
        tab.mode.setCurrentIndex(1)
        tab.frame_number.setValue(7)
        for name, field in (("source", tab.source), ("drawing", tab.drawing),
                            ("raw", tab.generated), ("edit_mask", tab.edit_mask),
                            ("protection_mask", tab.protection_mask)):
            field.setText(str(self.files[name]))
        tab.preview_enforced()
        deadline = time.monotonic() + 5
        while tab._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(tab.save_button.isEnabled())
        tab.import_for_review()
        self.assertIsNone(tab.current_result)
        self.assertFalse(tab.save_button.isEnabled())
        self.assertEqual(tab.view.currentText(), "Raw candidate")
        self.assertIn("Unreviewed candidate", tab.candidate_status.text())
        tab.deleteLater()
        parent.deleteLater()


class RealWindowOwnedBindingTests(GuiFixture):
    def test_project_field_created_after_tab_still_invalidates_owned_preview(self):
        window = self.window()
        tab = window.comfy_tab
        self.assertIs(tab._bound_project_field, window.project_dir)
        tab.owned_result = object()
        tab.owned_save_button.setEnabled(True)
        window.project_dir.setText(str(self.root / "another-project"))
        self.assertIsNone(tab.owned_result)
        self.assertFalse(tab.owned_save_button.isEnabled())
