"""Header, session logs and processing compatibility; no real settings or GPU."""
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox

from test_reezsynth_gui import GuiFixture, gui
from test_reezsynth_lifecycle import LifecycleFixture
from reezsynth_config import (OPTIONAL_FLOW_HASHES, validate_group, validate_render,
                              validate_flow_model_available)


class HeaderAndSettingsTests(GuiFixture):
    def test_logo_tabs_share_header_and_every_tab_remains_reachable(self):
        w = self.window()
        w.show()
        self.app.processEvents()
        bar = w.tabs.tabBar()
        logo = w.logo.mapTo(w, QPoint(0, 0))
        tabs = bar.mapTo(w, QPoint(0, 0))
        self.assertLess(logo.x(), tabs.x())
        self.assertLess(abs(logo.y() - tabs.y()), 10)
        self.assertLess(tabs.y(), 25)
        for index in range(w.tabs.count()):
            QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(index).center())
            self.assertEqual(w.tabs.currentIndex(), index)
            self.assertTrue(w.save_log_button.isVisible())
        # Exercise the separate two-column popup painter, not just the closed combo.
        w.tabs.setCurrentIndex(0)
        w.resolution.showPopup()
        self.app.processEvents()
        self.assertFalse(w.resolution.view().grab().isNull())
        w.resolution.hidePopup()

    def test_preset_dimensions_stay_locked_and_custom_stays_editable_after_busy(self):
        w = self.window()
        for size, editable in ((None, False), ([1280, 720], False), ([1536, 864], True)):
            w.set_processing_size(size)
            w.set_busy(True)
            self.assertFalse(w.processing_width.isEnabled())
            w.set_busy(False)
            self.assertEqual(w.processing_width.isEnabled(), editable)
            self.assertEqual(w.processing_height.isEnabled(), editable)
            self.assertEqual(w.processing_size(), tuple(size) if size == [1280, 720] else size)

    def test_render_presets_do_not_change_processing_size(self):
        w = self.window()
        w.set_processing_size([1280, 720])
        w.options.apply('render', dict(max_width=960))
        self.assertEqual(w.processing_size(), (1280, 720))
        self.assertEqual(w.processing_max_width(), 0)
        w.options.store.save('render', 'Legacy', w.options.snapshot('render'))
        w.close()
        restored = self.window()
        self.assertEqual(restored.processing_size(), (1280, 720))
        restored.options.apply('render', restored.options.store.groups['render']['Legacy'])
        self.assertEqual(restored.processing_size(), (1280, 720))
        self.assertEqual(validate_group('render', dict(max_width=512))['max_width'], 512)

    def test_old_qsettings_and_corrupt_dimensions_do_not_break_startup(self):
        self.preferences.setValue('last_setup/max_width', 512)
        w = self.window()
        self.assertEqual(w.processing_max_width(), 512)
        # Test QSettings fallback directly, before the separate last-used restore.
        self.preferences.setValue('last_setup/processing_size', '[false, 720]')
        gui.restore_ui_state(w)
        self.assertEqual(w.resolution.currentData(), 'original')

    def test_original_size_uses_image_target_and_unknown_input_shows_dash(self):
        w = self.window()
        target = self.root / 'target.png'
        image = QImage(800, 600, QImage.Format.Format_RGB32)
        image.fill(0)
        self.assertTrue(image.save(str(target)))
        w.image_synthesis.target.setText(str(target))
        w.tabs.setCurrentWidget(w.image_synthesis)
        self.assertEqual((w.processing_width.value(), w.processing_height.value()), (800, 600))
        w.image_synthesis.target.setText('')
        self.assertEqual(w.processing_width.text(), '—')

    def test_automatic_pyramid_steps_and_preset_round_trip(self):
        w = self.window()
        control = w.options.widgets['render']['pyramidlevels']
        control.setValue(1)
        control.stepDown()
        self.assertEqual(control.value(), -1)
        self.assertEqual(control.text(), 'Automatic')
        data = w.options.snapshot('render')
        control.stepUp()
        self.assertEqual(control.value(), 1)
        w.options.apply('render', data)
        self.assertEqual(w.options.render()['pyramidlevels'], -1)
        with self.assertRaises(ValueError):
            validate_render(dict(pyramidlevels=0))

    def test_live_preview_tracks_only_selected_directions_and_reflows(self):
        w = self.window()
        back, forward = QCheckBox(), QCheckBox()
        back.setChecked(True)
        row = dict(key=12, reverse=back, forward=forward,
                   start=gui.QueueSpinBox(), end=gui.QueueSpinBox())
        row['start'].setValue(4); row['end'].setValue(12)
        w.preview_window.begin([dict(row=row, key=12)], 8)
        self.assertEqual(w.preview_window.entries, [(12, 'Backward')])
        image_path = self.root / 'preview.png'
        image = QImage(40, 20, QImage.Format.Format_RGB32); image.fill(0x00AA88)
        self.assertTrue(image.save(str(image_path)))
        w.preview_window.update_frame(12, 'Backward', image_path)
        self.assertEqual(w.preview_window.tiles[(12, 'Backward')].path, image_path)
        self.assertTrue(w.preview_window.tiles[(12, 'Backward')].pixmap.isNull())
        w.preview_window.show()
        self.app.processEvents()
        self.assertFalse(w.preview_window.tiles[(12, 'Backward')].pixmap.isNull())
        w.preview_window.layout_mode.setCurrentIndex(1)
        w.preview_window.resize(400, 900)
        self.app.processEvents()
        self.assertEqual(w.preview_window.grid.count(), 1)

    def test_flow_weight_check_uses_only_the_selected_file(self):
        with patch('reezsynth_config.__file__', str(self.root / 'reezsynth_config.py')):
            with self.assertRaisesRegex(ValueError, 'Sintel weights are missing'):
                validate_flow_model_available('sintel')
            model = self.root / 'ezsynth/utils/flow_utils/models/raft-kitti.pth'
            model.parent.mkdir(parents=True)
            model.write_bytes(b'test weight placeholder; never loaded')
            self.assertEqual(validate_flow_model_available('kitti'), model)
            ef_model = self.root / 'ezsynth/utils/flow_utils/ef_raft_models/ours_sintel.pth'
            ef_model.parent.mkdir(parents=True)
            ef_model.write_bytes(b'test weight placeholder; never loaded')
            with patch.dict(OPTIONAL_FLOW_HASHES, {'ours_sintel.pth': hashlib.sha256(ef_model.read_bytes()).hexdigest()}):
                self.assertEqual(validate_flow_model_available('ours_sintel', 'EF_RAFT'), ef_model)
            with self.assertRaisesRegex(ValueError, 'timm'):
                validate_flow_model_available('FlowDiffuser-things', 'FLOW_DIFF')


class SessionAndProjectTests(LifecycleFixture):
    def test_progress_preview_event_reaches_open_preview_window(self):
        row = self.w.rows[0]
        output = self.root / 'preview-output'
        output.mkdir()
        job_path = output / 'job.json'
        job_path.write_text(json.dumps(dict(key=row['key'], style='unused', frames=[[0, 'a'], [2, 'b']])))
        self.w.current = dict(row=row, weight=1, output=output, job_path=job_path)
        path = output / '.reezsynth-preview' / '0_forward.png'
        path.parent.mkdir()
        image = QImage(8, 8, QImage.Format.Format_RGB32); image.fill(0)
        self.assertTrue(image.save(str(path)))
        self.w.preview_window.begin([self.w.current], 8)
        self.w.preview_window.show()
        self.app.processEvents()
        event = dict(percent=95, stage='Saving 2/3',
                     preview=dict(key=row['key'], direction='Forward', path=str(path)))
        self.w.consume_line('out', gui.PREFIX + json.dumps(event))
        tile = self.w.preview_window.tiles[(row['key'], 'Forward')]
        self.assertEqual(tile.path, path)
        self.assertFalse(tile.pixmap.isNull())

    def test_save_log_while_running_and_history_survives_cancel_restart(self):
        self.w.show()
        self.mode('slow')
        self.run_queue()
        self.until(lambda: 'MOCK_STARTED' in self.w.log.toPlainText())
        self.w.tabs.setCurrentWidget(self.w.log)
        self.assertTrue(self.w.save_log_button.isEnabled())
        destination = self.root / 'session.log'
        with patch.object(gui.QFileDialog, 'getSaveFileName', return_value=(str(destination), '')):
            self.w.save_log_button.click()
        self.assertIn('MOCK_STARTED', destination.read_text(encoding='utf-8'))
        self.w.stop_queue()
        self.until(lambda: not self.w.busy)
        previous = self.w.log.toPlainText()
        self.mode('normal')
        self.run_queue()
        self.until(lambda: not self.w.busy)
        self.assertTrue(self.w.log.toPlainText().startswith(previous))
        for boundary in ('QUEUE RUN 1 STARTED', 'QUEUE RUN 1 ENDED', 'QUEUE RUN 2 STARTED', 'QUEUE RUN 2 ENDED'):
            self.assertEqual(self.w.log.toPlainText().count(boundary), 1)
        self.assertFalse(self.w.processing_width.isEnabled())

    def test_single_frame_queue_needs_no_flow_weights(self):
        row = self.w.rows[0]
        row['reverse'].setChecked(False)
        row['forward'].setChecked(False)
        with patch.object(gui, 'validate_flow_model_available', side_effect=AssertionError('No flow needed')):
            self.w.run_rows([row])
            self.until(lambda: not self.w.busy)
        self.assertEqual(row['state'].text(), 'Complete')

    def test_legacy_video_and_image_project_round_trips_keep_width_limit(self):
        w = self.w
        w.project_file = self.root / 'project.json'
        w.save_project()
        saved = json.loads(w.project_file.read_text())
        saved.pop('processing_size')
        saved['max_width'] = 512
        for image_only in (False, True):
            data = dict(saved)
            if image_only:
                data.update(project_mode='image', rows=[], grouped_video=None,
                            image_synthesis=dict(style=str(self.root / 'style.png'),
                                                 source=str(self.root / 'source.png'), target=str(self.root / 'target.png')))
            w.project_file.write_text(json.dumps(data))
            with patch.object(gui.QFileDialog, 'getOpenFileName', return_value=(str(w.project_file), '')):
                w.open_project()
            self.assertEqual(w.processing_max_width(), 512)
            self.assertIsNone(w.processing_size())
            w.save_project()
            resaved = json.loads(w.project_file.read_text())
            self.assertEqual(resaved['max_width'], 512)
            self.assertIsNone(resaved['processing_size'])


if __name__ == '__main__':
    unittest.main()
