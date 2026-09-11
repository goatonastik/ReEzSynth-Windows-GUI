"""Preset, settings, automation, project and parallel-queue regressions."""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QProcess
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QCheckBox

from test_reezsynth_gui import GuiFixture, gui, controls
from test_reezsynth_lifecycle import LifecycleFixture
from reezsynth_config import (APPLICATION, PREVIEW, STANDARD, WEIGHTS, PresetStore,
    discover_pairs, validate_render, validate_weights)
from reezsynth_jobs import validate_masks


REAL_NOTIFY = gui.Options.notify


class PresetTests(GuiFixture):
    def test_store_groups_overwrite_remove_and_export_round_trip(self):
        path = self.root / "presets.json"
        store = PresetStore(path)
        store.save("weights", "Paint", WEIGHTS)
        with self.assertRaises(ValueError):
            store.save("weights", "paint", WEIGHTS)
        store.save("weights", "paint", dict(WEIGHTS, img_wgt=9.0), overwrite=True)
        store.save("directories", "paint", dict(video_dir="D:/video"))
        loaded = PresetStore(path)
        self.assertEqual(loaded.groups["weights"]["paint"]["img_wgt"], 9)
        self.assertEqual(loaded.groups["directories"]["paint"]["video_dir"], "D:/video")
        export = self.root / "export.json"
        loaded.write(loaded.groups, export)
        self.assertEqual(PresetStore(export).groups, loaded.groups)
        loaded.remove("weights", "paint")
        self.assertEqual(PresetStore(path).groups["weights"], {})
        self.assertIn("paint", loaded.groups["directories"])

    def test_invalid_preset_does_not_replace_good_file(self):
        store = PresetStore(self.root / "presets.json")
        store.save("weights", "good", WEIGHTS)
        before = store.path.read_bytes()
        for weights in ({"edg_wgt": float("nan")}, {"img_wgt": -1}, {"unknown": 2}):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                store.save("weights", "bad", weights)
        self.assertEqual(store.path.read_bytes(), before)

    def test_preset_buttons_prefill_and_confirm_overwrite(self):
        w = self.window()
        options = w.options
        with patch("reezsynth_options.QInputDialog.getText", return_value=("Paint", True)):
            options.save_preset("weights")
        options.widgets["weights"]["img_wgt"].setValue(9)
        with patch("reezsynth_options.QInputDialog.getText", return_value=("Paint", True)) as prompt, patch.object(
                gui.QMessageBox, "question", return_value=gui.QMessageBox.StandardButton.No):
            options.save_preset("weights")
            self.assertEqual(prompt.call_args.kwargs["text"], "Paint")
        self.assertEqual(options.store.groups["weights"]["Paint"]["img_wgt"], 6)
        with patch("reezsynth_options.QInputDialog.getText", return_value=("Paint", True)), patch.object(
                gui.QMessageBox, "question", return_value=gui.QMessageBox.StandardButton.Yes):
            options.save_preset("weights")
        self.assertEqual(options.store.groups["weights"]["Paint"]["img_wgt"], 9)

    def test_startup_policy_defaults_last_and_named_preset(self):
        w = self.window()
        o = w.options
        o.widgets["weights"]["img_wgt"].setValue(8)
        o.widgets["render"]["uniformity"].setValue(4200)
        o.store.save("weights", "Named", dict(WEIGHTS, img_wgt=12))
        o.refresh_presets()
        o.policy_boxes["weights"].setCurrentIndex(o.policy_boxes["weights"].findData("preset:Named"))
        o.policy_boxes["render"].setCurrentIndex(o.policy_boxes["render"].findData("defaults"))
        w.close()
        restored = self.window()
        self.assertEqual(restored.options.weights()["img_wgt"], 12)
        self.assertEqual(restored.options.render()["uniformity"], 3500)
        self.assertFalse(restored.options.application()["parallel"])
        self.assertFalse(restored.options.auto_armed)

    def test_changes_persist_separately_from_presets(self):
        w = self.window()
        w.options.widgets["weights"]["img_wgt"].setValue(7)
        w.options.persist()
        data = json.loads(w.options.last_path.read_text())
        self.assertEqual(data["groups"]["weights"]["img_wgt"], 7)
        self.assertFalse(w.options.store.path.exists())
        self.assertEqual(self.window().options.weights()["img_wgt"], 7)

    def test_corrupt_preset_library_is_preserved(self):
        path = self.root / "configuration" / "presets.json"
        path.parent.mkdir()
        path.write_text("not json")
        w = self.window()
        w.options.persist()
        self.assertIsNone(w.options.store)
        self.assertEqual(path.read_text(), "not json")
        self.assertIn("Presets could not be loaded", w.log.toPlainText())

    def test_quality_resets_synthesis_but_preserves_weights(self):
        w = self.window()
        self.assertEqual(w.quality.currentText(), 'Standard')
        self.assertEqual(w.options.weights()['img_wgt'], 6)
        w.quality.setCurrentText('Preview')
        w.options.widgets["weights"]["img_wgt"].setValue(11)
        w.quality.setCurrentText("Standard")
        for key, value in STANDARD.items():
            self.assertEqual(w.options.render()[key], value)
        self.assertEqual(w.options.weights()["img_wgt"], 11)

    def test_invalid_engine_parameters_are_rejected(self):
        for data in ({"patchsize": 4}, {"feather": 2}, {"uniformity": float("inf")},
                     {"do_mask": 1}, {"edge_method": "unknown"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_render(data)

    def test_discovery_matches_sibling_suffixes_and_custom_prefixes(self):
        for name in ("keys_shot", "video_shot", "keys_other", "video_different", "nested"):
            self.directory(name)
        (self.root / "nested" / "paint_a").mkdir()
        (self.root / "nested" / "source_a").mkdir()
        self.assertEqual(discover_pairs(self.root), [(self.root / "keys_shot", self.root / "video_shot")])
        self.assertEqual(discover_pairs(self.root, "paint", "source"),
                         [(self.root / "nested" / "paint_a", self.root / "nested" / "source_a")])

    def test_ambiguous_discovery_requires_selection(self):
        w = self.window()
        for name in ("keys_a", "video_a", "keys_b", "video_b"):
            self.directory(name)
        w.options.widgets["application"]["discover"].setChecked(True)
        w.project_dir.setText(str(self.root))
        with patch("reezsynth_options.QInputDialog.getItem", return_value=("", False)) as prompt:
            w.options.discover()
        prompt.assert_called_once()
        self.assertEqual(w.video_dir.text(), "")

    def test_suffix_toggles_and_new_template_fields(self):
        w = self.window()
        w.keyframe_dir.setText(str(self.root / "keys_shot"))
        w.video_dir.setText(str(self.root / "video_shot"))
        w.keys = {23: self.root / "paint023.png"}
        definition = dict(key=23, start=0, end=46, reverse=True, forward=True)
        values = controls._values(w, definition)
        self.assertEqual(controls._format_name("{key_name}_{keyframe_dir_name}_{video_dir_name}", values, controls.JOB_FIELDS),
                         "paint023_keys_shot_video_shot")
        toggle = next(b for b in w.findChildren(QCheckBox) if b.text() == "Keyframe name")
        toggle.setChecked(True)
        self.assertIn("_{key_name}", w.job_name_pattern.text())
        toggle.setChecked(False)
        self.assertNotIn("_{key_name}", w.job_name_pattern.text())


class IntegrationTests(LifecycleFixture):
    def test_project_round_trip_and_older_project_keeps_manual_names(self):
        w = self.w
        w.rows[0]["folder"].setText("manual")
        w.options.widgets["weights"]["img_wgt"].setValue(8)
        w.options.widgets["render"]["uniformity"].setValue(4100)
        w.options.widgets['render']['memory_efficient_raft'].setChecked(True)
        w.project_file = self.root / "project.json"
        w.save_project()
        data = json.loads(w.project_file.read_text())
        self.assertEqual(data["guide_weights"]["img_wgt"], 8)
        w.options.widgets["weights"]["img_wgt"].setValue(2)
        with patch.object(gui.QFileDialog, "getOpenFileName", return_value=(str(w.project_file), "")):
            w.open_project()
        self.assertEqual(w.options.weights()["img_wgt"], 8)
        self.assertEqual(w.options.render()["uniformity"], 4100)
        self.assertTrue(w.options.render()['memory_efficient_raft'])
        for key in ("guide_weights", "render_options", "mask_dir", "output_naming"):
            data.pop(key, None)
        data["quality"] = "Standard"
        w.project_file.write_text(json.dumps(data))
        with patch.object(gui.QFileDialog, "getOpenFileName", return_value=(str(w.project_file), "")):
            w.open_project()
        self.assertEqual(w.rows[0]["folder"].text(), "manual")
        self.assertEqual(w.options.weights(), WEIGHTS)
        self.assertEqual(w.options.render()["patchsize"], STANDARD["patchsize"])
        self.assertFalse(w.options.auto_armed)

    def make_masks(self, size=8):
        masks = self.root / "masks"
        masks.mkdir(exist_ok=True)
        image = QImage(size, size, QImage.Format.Format_Grayscale8)
        image.fill(255)
        for i in range(3):
            image.save(str(masks / f"mask{i:03d}.png"))
        return masks

    def test_mask_number_and_dimension_validation(self):
        masks = self.make_masks()
        self.assertEqual(set(validate_masks(masks, self.w.video)), {0, 1, 2})
        self.make_masks(4)
        with self.assertRaises(ValueError):
            validate_masks(masks, self.w.video)
        (masks / "mask001.png").unlink()
        with self.assertRaises(ValueError):
            validate_masks(masks, self.w.video)

    def test_manual_start_disarms_pending_automatic_start(self):
        o = self.w.options
        o.widgets["application"]["auto_start"].setChecked(True)
        self.assertTrue(o.auto_timer.isActive())
        with patch.object(self.w, "start_next"):
            self.run_queue()
        self.assertFalse(o.auto_armed)
        self.assertFalse(o.auto_timer.isActive())
        self.w.stop_queue()

    def test_job_contains_render_controls_weights_and_masks(self):
        self.w.mask_dir.setText(str(self.make_masks()))
        self.w.options.widgets["render"]["do_mask"].setChecked(True)
        self.w.options.widgets["weights"]["img_wgt"].setValue(8)
        with patch.object(self.w, "start_next"):
            self.run_queue()
        job = json.loads(self.w.pending[0]["job_path"].read_text())
        self.assertTrue(job["render_options"]["do_mask"])
        self.assertEqual(job["guide_weights"]["img_wgt"], 8)
        self.assertEqual([n for n, _ in job["masks"]], [n for n, _ in job["frames"]])
        self.w.stop_queue()

    def test_auto_start_waits_for_masks_and_does_not_repeat(self):
        o = self.w.options
        o.widgets["application"]["auto_start"].setChecked(True)
        o.widgets["application"]["wait_for_mask"].setChecked(True)
        o.auto_armed = True
        with patch.object(self.w, "run_rows") as run:
            o.maybe_start()
            run.assert_not_called()
            self.w.mask_dir.setText(str(self.make_masks()))
            o.maybe_start()
            run.assert_called_once()
            o.auto_armed = True
            o.maybe_start()
            run.assert_called_once()

    def test_auto_start_does_not_run_during_preset_application_or_busy_queue(self):
        o = self.w.options
        o.widgets["application"]["auto_start"].setChecked(True)
        o.auto_armed = True
        with patch.object(self.w, "run_rows") as run:
            o.loading = True
            o.maybe_start()
            o.loading = False
            self.w.busy = True
            o.maybe_start()
            self.w.busy = False
            run.assert_not_called()

    def test_apply_names_confirmation_preserves_or_replaces_manual_names(self):
        self.w.rows[0]["folder"].setText("manual")
        self.w.job_name_pattern.setText("paint_{key:04d}")
        with patch.object(gui.QMessageBox, "question", return_value=gui.QMessageBox.StandardButton.No):
            controls.apply_names_to_queue(self.w)
        self.assertEqual(self.w.rows[0]["folder"].text(), "manual")
        with patch.object(gui.QMessageBox, "question", return_value=gui.QMessageBox.StandardButton.Yes):
            controls.apply_names_to_queue(self.w)
        self.assertEqual(self.w.rows[0]["folder"].text(), "paint_0000")

    def enable_parallel(self, limit=2):
        self.w.options.widgets["application"]["parallel"].setChecked(True)
        self.w.options.widgets["application"]["parallel_limit"].setValue(limit)

    def test_parallel_workers_overlap_cancel_and_restart(self):
        self.enable_parallel()
        self.mode("slow")
        self.run_queue()
        pool = self.w.parallel_queue
        self.until(lambda: self.w.log.toPlainText().count("MOCK_STARTED") == 2)
        self.assertEqual(len(pool.active), 2)
        self.w.stop_queue()
        self.assertTrue(self.w.busy)
        self.assertFalse(self.w.run_all.isEnabled())
        self.until(lambda: not self.w.busy)
        self.assertIsNone(self.w.parallel_queue)
        self.mode("normal")
        self.run_queue()
        self.until(lambda: not self.w.busy)
        self.assertEqual(self.w.overall.value(), 100)
        self.assertTrue(all(r["state"].text() == "Complete" for r in self.w.rows))

    def test_parallel_limit_one_keeps_second_job_pending(self):
        self.enable_parallel(1)
        self.mode("slow")
        self.run_queue()
        self.until(lambda: "MOCK_STARTED" in self.w.log.toPlainText())
        pool = self.w.parallel_queue
        self.assertEqual(len(pool.active), 1)
        self.assertEqual(len(pool.pending), 1)
        self.w.stop_queue()
        self.until(lambda: not self.w.busy)
        self.assertEqual(self.w.rows[1]["state"].text(), "Not run")

    def test_parallel_failure_stops_queue_and_reaps_workers(self):
        self.enable_parallel()
        self.mode("fail")
        self.run_queue()
        self.until(lambda: not self.w.busy)
        self.assertIsNone(self.w.parallel_queue)
        self.assertIn("failed", self.w.status.text())

    def test_parallel_failed_start(self):
        self.enable_parallel()
        with patch.object(gui.sys, "executable", str(self.root / "missing.exe")):
            self.run_queue()
            self.until(lambda: not self.w.busy)
        self.assertIsNone(self.w.parallel_queue)
        self.assertTrue(self.w.run_all.isEnabled())

    def test_close_parallel_queue_reaps_all_workers(self):
        self.enable_parallel()
        self.mode("slow")
        self.w.show()
        self.run_queue()
        self.until(lambda: self.w.log.toPlainText().count("MOCK_STARTED") == 2)
        with patch.object(gui.QMessageBox, "question", return_value=gui.QMessageBox.StandardButton.Yes):
            self.assertFalse(self.w.close())
        self.until(lambda: not self.w.isVisible())
        self.assertFalse(self.w.busy)
        self.assertIsNone(self.w.parallel_queue)


class GuardTests(GuiFixture):
    def test_missing_startup_preset_does_not_block_other_groups(self):
        w = self.window()
        o = w.options
        o.store.save("weights", "Removed", WEIGHTS)
        o.refresh_presets()
        box = o.policy_boxes["weights"]
        box.setCurrentIndex(box.findData("preset:Removed"))
        o.widgets["render"]["uniformity"].setValue(4200)
        w.close()
        o.store.remove("weights", "Removed")
        restored = self.window()
        self.assertEqual(restored.options.weights(), WEIGHTS)
        self.assertEqual(restored.options.render()["uniformity"], 4200)
        self.assertIn("Startup preset unavailable", restored.log.toPlainText())
        self.assertEqual(restored.options.policy_boxes["weights"].currentData(), "preset:Removed")

    def test_modal_dialog_defers_automatic_start(self):
        w = self.window()
        o = w.options
        o.auto_armed = True
        o.widgets["application"]["auto_start"].setChecked(True)
        with patch("reezsynth_options.QApplication.activeModalWidget", return_value=object()), patch.object(w, "run_rows") as run:
            o.maybe_start()
            run.assert_not_called()
            self.assertTrue(o.auto_timer.isActive())

    def test_notification_defaults_custom_file_and_disable(self):
        w = self.window()
        o = w.options
        sound = MagicMock()
        constructor = MagicMock(return_value=sound)
        fake = types.SimpleNamespace(QSoundEffect=constructor)
        with patch.dict(sys.modules, {"PySide6.QtMultimedia": fake}):
            REAL_NOTIFY(o, each=True)
            constructor.assert_not_called()
            REAL_NOTIFY(o)
            constructor.assert_called_once()
            self.assertTrue(sound.setSource.call_args.args[0].toLocalFile().endswith("complete.wav"))
            sound.play.assert_called_once()
            custom = self.root / "custom.wav"
            custom.write_bytes(b"test placeholder")
            o.widgets["application"]["sound_file"].setText(str(custom))
            REAL_NOTIFY(o)
            self.assertEqual(Path(sound.setSource.call_args.args[0].toLocalFile()), custom)
            o.widgets["application"]["sound_enabled"].setChecked(False)
            REAL_NOTIFY(o)
            self.assertEqual(sound.play.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
