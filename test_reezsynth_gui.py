"""Offscreen GUI/control regressions; run: python -B test_reezsynth_gui.py.

Uses temporary INI settings and directories, no renderer or GPU. Stale history
retention is documented current behavior, not a guarantee of path availability.
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

import reezsynth_gui as gui
import reezsynth_project_controls as controls


class GuiFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(gui.THEME)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="reezsynth_gui_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.settings_path = self.root / "settings.ini"
        self.preferences = self.settings()
        self.widgets = []
        self.qt_errors = []
        self.addCleanup(lambda: self.assertEqual(self.qt_errors, [], "Unhandled Qt callback exception"))
        self.enterContext(patch.object(sys, "excepthook", side_effect=lambda *error: self.qt_errors.append(error)))
        self.addCleanup(self.dispose_widgets)
        self.enterContext(patch.object(gui.Options, "notify"))
        self.enterContext(patch.object(gui, "ROOT", self.root))
        self.enterContext(patch.object(gui, "QSettings", side_effect=lambda *a: self.settings()))
        # Unexpected dialogs must fail rather than hang an unattended test.
        for method in ("warning", "information", "question"):
            self.enterContext(patch.object(gui.QMessageBox, method,
                side_effect=AssertionError("Unexpected dialog: " + method)))

    def settings(self):
        result = QSettings(str(self.settings_path), QSettings.Format.IniFormat)
        result.setFallbacksEnabled(False)
        return result

    def dispose_widgets(self):
        for widget in reversed(self.widgets):
            widget.close()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.preferences.sync()

    def window(self):
        window = gui.MainWindow()
        self.widgets.append(window)
        return window

    def combo(self, preferences=None):
        combo = controls.FolderHistoryCombo(
            "Video frames", gui.FolderEdit(), preferences or self.preferences)
        self.widgets.append(combo)
        return combo

    def directory(self, name):
        path = self.root / name
        path.mkdir()
        return str(path.resolve())


class ConstructionTests(GuiFixture):
    def test_construct_show_and_close_real_window(self):
        window = self.window()
        window.show()
        self.app.processEvents()
        self.assertTrue(window.isVisible())
        self.assertEqual(window.windowTitle(), gui.APP_NAME)
        self.assertEqual(window.table.rowCount(), 0)
        self.assertFalse(window.run_all.isEnabled())
        self.assertIsNone(window.process)
        self.assertTrue(window.reuse_worker.isChecked())
        self.assertEqual(window.batch_name_pattern.text(), controls.DEFAULT_BATCH_PATTERN)
        self.assertIn("out_023", window.naming_preview.text())
        for field in (window.project_dir, window.keyframe_dir, window.video_dir):
            self.assertIsInstance(field, controls.FolderHistoryCombo)
            self.assertIsInstance(field.lineEdit(), gui.FolderEdit)
        self.assertEqual(Path(window.preferences.fileName()), self.settings_path)
        self.assertTrue(window.close())
        self.assertFalse(window.isVisible())
        self.assertFalse(window.scan_timer.isActive())
        self.assertFalse(window.shutdown_timer.isActive())
        self.assertNotIn("ezsynth.main_ez", sys.modules)
        self.assertNotIn("torch", sys.modules)

    def test_saved_false_worker_preference_survives_restart(self):
        self.preferences.setValue("reuse_queue_worker", False)
        self.preferences.sync()
        window = self.window()
        self.assertFalse(window.reuse_worker.isChecked())
        window.close()
        self.assertFalse(self.window().reuse_worker.isChecked())

    def test_setup_round_trip(self):
        window = self.window()
        project = self.directory("project")
        window.project_dir.setText(project)
        window.quality.setCurrentText("Standard")
        window.resolution.setCurrentIndex(window.resolution.findData(0))
        window.batch_name_pattern.setText("shot_{date}")
        window.job_name_pattern.setText("paint_{key:04d}")
        window.close()
        restored = self.window()
        self.assertEqual(restored.project_dir.text(), project)
        self.assertEqual(restored.quality.currentText(), "Standard")
        self.assertEqual(restored.resolution.currentData(), 0)
        self.assertEqual(restored.batch_name_pattern.text(), "shot_{date}")
        self.assertEqual(restored.job_name_pattern.text(), "paint_{key:04d}")
        self.assertEqual(restored.rows, [])


class FolderHistoryTests(GuiFixture):
    def test_typing_and_selection_emit_text_changes(self):
        combo = self.combo()
        path = self.directory("typed")
        spy = QSignalSpy(combo.textChanged)
        QTest.keyClicks(combo.lineEdit(), path)
        self.assertEqual(combo.text(), path)
        self.assertGreater(spy.count(), 0)
        combo.lineEdit().editingFinished.emit()
        other = self.directory("other")
        combo.setText(other)
        combo.remember()
        before = spy.count()
        combo.setCurrentIndex(1)
        self.assertEqual(combo.text(), path)
        self.assertGreater(spy.count(), before)

    def test_remember_deduplicates_limits_and_persists_without_signals(self):
        combo = self.combo()
        paths = [self.directory(f"folder_{i}") for i in range(14)]
        for path in paths:
            combo.setText(path)
            combo.remember()
        combo.setText('"' + paths[5] + '"')
        spy = QSignalSpy(combo.textChanged)
        combo.remember()
        self.assertEqual(spy.count(), 0)
        expected = [paths[5]] + [p for p in reversed(paths[2:]) if p != paths[5]]
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], expected)
        self.assertEqual(combo.count(), 12)
        self.assertEqual(combo.text(), paths[5])
        self.preferences.sync()
        restored = self.combo(self.settings())
        self.assertEqual([restored.itemText(i) for i in range(restored.count())], expected)
        self.assertEqual(restored.text(), "")

    def test_invalid_inputs_do_not_enter_history(self):
        combo = self.combo()
        file = self.root / "file.txt"
        file.write_text("test", encoding="utf-8")
        for value in ("", "  ", str(file), str(self.root / "missing")):
            with self.subTest(value=value):
                combo.setText(value)
                combo.remember()
                self.assertEqual(combo.count(), 0)

    def test_legacy_string_and_malformed_settings(self):
        path = self.directory("legacy")
        for stored, expected in ((path, [path]), (42, []), ([path, "", 42], [path])):
            with self.subTest(stored=stored):
                self.preferences.setValue("folder_history/video_frames", stored)
                combo = self.combo()
                self.assertEqual([combo.itemText(i) for i in range(combo.count())], expected)

    def test_existing_stale_history_is_retained_but_not_readded(self):
        stale = str(self.root / "missing")
        self.preferences.setValue("folder_history/video_frames", [stale])
        combo = self.combo()
        combo.setText(stale)
        combo.remember()
        self.assertEqual(combo.count(), 1)
        combo.setText(self.directory("valid"))
        combo.remember()
        self.assertEqual(combo.itemText(1), stale)

    def test_case_variants_deduplicate_when_remembered(self):
        path = self.directory("MixedCase")
        self.preferences.setValue("folder_history/video_frames", [path.upper(), path])
        combo = self.combo()
        combo.setText(path)
        combo.remember()
        self.assertEqual(combo.count(), 1)
        self.assertEqual(combo.itemText(0), path)

    def test_directory_drag_drop_through_combo_editor(self):
        combo = self.combo()
        combo.show()
        self.app.processEvents()
        path = self.directory("dropped")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        drag = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(combo.lineEdit(), drag)
        self.assertTrue(drag.isAccepted())
        drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(combo.lineEdit(), drop)
        self.assertTrue(drop.isAccepted())
        self.assertEqual(combo.text(), path)
        combo.lineEdit().editingFinished.emit()
        self.assertEqual(combo.itemText(0), path)

    def test_invalid_or_disabled_drops_are_rejected(self):
        combo = self.combo()
        path = self.directory("drop")
        file = self.root / "image.png"
        file.write_bytes(b"placeholder")
        for urls in ([QUrl.fromLocalFile(str(file))], [QUrl("https://example.invalid")],
                     [QUrl.fromLocalFile(path)] * 2, []):
            with self.subTest(urls=urls):
                mime = QMimeData()
                mime.setUrls(urls)
                drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                combo.lineEdit().dropEvent(drop)
                self.assertFalse(drop.isAccepted())
                self.assertEqual(combo.text(), "")
        combo.setEnabled(False)
        mime.setUrls([QUrl.fromLocalFile(path)])
        drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        combo.lineEdit().dropEvent(drop)
        self.assertFalse(drop.isAccepted())


class NamingTests(GuiFixture):
    def test_default_and_documented_patterns_with_fixed_time(self):
        values = controls._values(now=datetime(2026, 9, 10, 12, 34, 56, 123456))
        for pattern, expected in ((controls.DEFAULT_BATCH_PATTERN, "batch_20260910_123456_123456"),
                (controls.DEFAULT_JOB_PATTERN, "out_023"), ("paint_{key:04d}", "paint_0023"),
                ("{index:02d}_key_{key}", "01_key_23"),
                ("{quality}_{width}_{start}_{end}", "Preview_512_0_46")):
            with self.subTest(pattern=pattern):
                self.assertEqual(controls._format_name(pattern, values, controls.JOB_FIELDS), expected)

    def test_malformed_patterns_and_batch_only_fields(self):
        for pattern in ("", "{", "{unknown}", "{}", "{key.real}", "{key[0]}",
                        "{key!r}", "{key:bad}", "{key:0{unknown}d}", "x" * 201):
            with self.subTest(pattern=pattern), self.assertRaises(ValueError):
                controls._format_name(pattern, controls._values(), controls.JOB_FIELDS)
        with self.assertRaises(ValueError):
            controls.validate_project_naming({"batch_pattern": "{key}"})
        with self.assertRaises(ValueError):
            controls.validate_project_naming({"batch_pattern": "parent/batch"})

    def test_windows_invalid_names(self):
        invalid = ["", ".", "..", "../escape", "a/../b", "/absolute", "C:\\out",
            "\\\\server\\share", "a//b", "a/", "a\\", "trailing.", "trailing ",
            "CON", "nul.txt", "COM1", "lpt9.png", "parent/AUX", "a\n", "x" * 181]
        invalid += ["a" + char + "b" for char in '<>:"|?*']
        for name in invalid:
            with self.subTest(name=name), self.assertRaises(ValueError):
                controls.validate_output_folders([name])

    def test_distinct_siblings_and_nested_names_are_valid(self):
        controls.validate_output_folders(["shot/a", "shot/b", "shot_2", "CONtrast", "paint_0023"])

    def test_duplicate_and_overlapping_names(self):
        for names in (["a", "A"], ["shot/a", "SHOT\\A"], ["shot", "shot/a"],
                      ["shot/a", "SHOT"]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                controls.validate_output_folders(names)

    def test_missing_project_naming_defaults_and_invalid_data(self):
        expected = {"batch_pattern": controls.DEFAULT_BATCH_PATTERN,
                    "job_pattern": controls.DEFAULT_JOB_PATTERN}
        for value in (None, {}):
            self.assertEqual(controls.validate_project_naming(value), expected)
        for value in ([], "bad", {"job_pattern": 23}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                controls.validate_project_naming(value)

    def test_generated_names_reflect_directions_and_do_not_mutate_rows(self):
        window = self.window()
        window.job_name_pattern.setText("{index:02d}_{key}_{start}_{end}_{width}")
        window.resolution.setCurrentIndex(window.resolution.findData(0))
        definitions = [dict(key=5, start=0, end=10, reverse=False, forward=True, folder="manual"),
                       dict(key=8, start=2, end=12, reverse=True, forward=False, folder="other")]
        result = controls.default_job_definitions(window, definitions)
        self.assertEqual([row["folder"] for row in result], ["01_5_5_10_original", "02_8_2_8_original"])
        self.assertEqual(definitions[0]["folder"], "manual")
        window.job_name_pattern.setText("same")
        with self.assertRaises(ValueError):
            controls.default_job_definitions(window, definitions)

    def test_batch_collisions_preserve_existing_content_and_skip_files(self):
        window = self.window()
        window.batch_name_pattern.setText("shot")
        first = controls.create_batch_directory(window, self.root)
        sentinel = first / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        second = controls.create_batch_directory(window, self.root)
        (first.parent / "shot_003").write_text("occupied", encoding="utf-8")
        fourth = controls.create_batch_directory(window, self.root)
        self.assertEqual(first, self.root / "renders" / "shot")
        self.assertEqual(second.name, "shot_002")
        self.assertEqual(fourth.name, "shot_004")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
        self.assertEqual((first.parent / "shot_003").read_text(encoding="utf-8"), "occupied")

    def test_invalid_batch_does_not_create_render_root(self):
        window = self.window()
        window.batch_name_pattern.setText("../escape")
        with self.assertRaises(ValueError):
            controls.create_batch_directory(window, self.root)
        self.assertFalse((self.root / "renders").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
