"""Preset, settings, automation, project and parallel-queue regressions."""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import reezsynth_options as options_module

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QCloseEvent, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox

from test_reezsynth_gui import GuiFixture, gui, controls
from test_reezsynth_lifecycle import LifecycleFixture
from reezsynth_config import (APPLICATION, GROUPS, LIMITS, PREVIEW, RENDER, SPIN_RULES, STANDARD, WEIGHTS, PresetStore,
    discover_pairs, validate_group, validate_render, validate_weights)
from reezsynth_jobs import validate_masks
from reezsynth_resources import estimate_job_vram, gpu_snapshot, safety_reserve_mib
from reezsynth_engines import FUOUM, LEGACY
from reezsynth_widget_style import ConstrainedQueueSpinBox


REAL_NOTIFY = gui.Options.notify


class ResourceSchedulingUnitTests(unittest.TestCase):
    def test_gpu_snapshot_selects_cuda_visible_device(self):
        result = MagicMock(returncode=0, stdout=(
            "0, GPU-zero, First GPU, 8192, 2048, 6144\n"
            "1, GPU-one, Second GPU, 24576, 4096, 20480\n"))
        snapshot = gpu_snapshot(run=MagicMock(return_value=result),
                                environ={"CUDA_VISIBLE_DEVICES": "GPU-one"})
        self.assertEqual(snapshot["index"], 1)
        self.assertEqual(snapshot["free_mib"], 20480)
        self.assertEqual(safety_reserve_mib(snapshot), 2457)
        self.assertIsNone(gpu_snapshot(run=MagicMock(return_value=result),
                                       environ={"CUDA_VISIBLE_DEVICES": "-1"}))

    def test_vram_estimate_uses_processed_resolution_engine_and_blending(self):
        legacy = estimate_job_vram(dict(processing_size=[1920, 1080],
            render_options=dict(engine=LEGACY, flow_arch="RAFT", memory_efficient_raft=True)))
        fuoum = estimate_job_vram(dict(type="grouped_video", processing_size=[1920, 1080],
            render_options=dict(engine=FUOUM, fuoum_flow_engine="RAFT"),
            blend_options=dict(use_gpu=True, use_poisson_cupy=True)))
        self.assertEqual((legacy["width"], legacy["height"]), (1920, 1080))
        self.assertGreater(fuoum["estimated_mib"], legacy["estimated_mib"])


class PresetTests(GuiFixture):
    def test_snapshot_captures_hostile_live_state_without_validation(self):
        w = self.window()
        w.batch_name_pattern.setText('{not_a_batch_field}')
        w.resolution.setCurrentIndex(w.resolution.findData('custom'))
        w.processing_width.setValue(64)
        w.processing_height.setValue(64)
        w.options.widgets['render']['patchsize'].setValue(4)

        output = w.options.snapshot('output')
        render = w.options.snapshot('render', include_related=True)
        self.assertEqual(output['batch_pattern'], '{not_a_batch_field}')
        self.assertEqual(render['processing_size'], [64, 64])
        self.assertEqual(render['options']['patchsize'], 4)
        for group in GROUPS:
            w.options.snapshot(group, include_related=(group == 'render'))

    def test_constrained_render_spins_commit_only_validator_legal_values(self):
        w = self.window()
        controls = w.options.widgets['render']
        patch, feather, levels = (controls[name] for name in ('patchsize', 'feather', 'pyramidlevels'))

        patch.setValue(3); patch.stepUp()
        self.assertEqual(patch.value(), 5)
        patch.setValue(7); patch.lineEdit().setFocus()
        QTest.keyClick(patch.lineEdit(), Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(patch.lineEdit(), '21')
        self.assertEqual(patch.value(), 7)
        QTest.keyClick(patch.lineEdit(), Qt.Key.Key_Return)
        self.assertEqual(patch.value(), 21)

        feather.setValue(0); feather.stepUp(); feather.stepUp()
        self.assertEqual(feather.value(), 3)
        feather.lineEdit().setText('2'); feather.interpretText(); feather.editingFinished.emit()
        self.assertEqual(feather.value(), 3)

        levels.setValue(-1); levels.stepUp()
        self.assertEqual(levels.value(), 1)
        levels.lineEdit().setText('0'); levels.interpretText(); levels.editingFinished.emit()
        self.assertEqual(levels.value(), 1)
        for name in SPIN_RULES:
            widget = controls[name]
            for value in range(LIMITS[name][0], LIMITS[name][1] + 1):
                widget.setValue(value)
                widget.editingFinished.emit()
                validate_render(dict(RENDER, **{name: widget.value()}))
                try:
                    validate_render(dict(RENDER, **{name: value}))
                except ValueError:
                    continue
                self.assertEqual(widget.value(), value)

    def test_constrained_spin_impossible_range_terminates(self):
        widget = ConstrainedQueueSpinBox('odd')
        widget.setRange(4, 4)
        widget.setValue(4)
        self.assertIsNone(widget.legal_value(4, 1))
        widget.stepUp()
        self.assertEqual(widget.value(), 4)

    def test_schedule_snapshot_is_raw_and_group_validation_canonicalizes_it(self):
        w = self.window()
        field = w.options.widgets['render']['searchvote_schedule']
        for text, expected in (('', []), ('   ', []), ('12, 8, 4', [12, 8, 4])):
            with self.subTest(text=text):
                field.setText(text)
                state = w.options.snapshot('render')
                self.assertEqual(state['options']['searchvote_schedule'], text)
                self.assertEqual(validate_group('render', state)['options']['searchvote_schedule'], expected)
        for text in ('1,', '1,,2', '0', '1001'):
            with self.subTest(text=text):
                field.setText(text)
                with self.assertRaises(ValueError):
                    validate_group('render', w.options.snapshot('render'))
                with self.assertRaises(ValueError):
                    validate_render(dict(searchvote_schedule=text))

    def test_memory_efficient_control_projects_flow_arch_validator_rule(self):
        w = self.window()
        controls = w.options.widgets['render']
        architecture, memory = controls['flow_arch'], controls['memory_efficient_raft']
        for flow_arch, model in (('RAFT', 'sintel'), ('EF_RAFT', '25000_ours-sintel'), ('FLOW_DIFF', 'FlowDiffuser-things')):
            with self.subTest(flow_arch=flow_arch):
                architecture.blockSignals(True)
                architecture.setCurrentText(flow_arch)
                architecture.blockSignals(False)
                controls['flow_model'].blockSignals(True)
                controls['flow_model'].clear()
                controls['flow_model'].addItem(model)
                controls['flow_model'].blockSignals(False)
                memory.setChecked(True)
                w.options.refresh_engine_controls()
                accepted = dict(w.options.snapshot('render')['options'], flow_arch=flow_arch,
                                flow_model=model, memory_efficient_raft=(flow_arch == 'RAFT'))
                validate_group('render', dict(w.options.snapshot('render'), options=accepted))
                self.assertEqual(memory.isEnabled(), flow_arch == 'RAFT')
                self.assertEqual(memory.isChecked(), flow_arch == 'RAFT')
                if flow_arch != 'RAFT':
                    with self.assertRaises(ValueError):
                        validate_group('render', dict(w.options.snapshot('render'),
                            options=dict(accepted, memory_efficient_raft=True)))

    def test_invalid_output_persist_keeps_known_good_group_and_saves_others(self):
        w = self.window()
        o = w.options
        w.batch_name_pattern.setText('good_{date}')
        o.persist()
        original = json.loads(o.last_path.read_text())['groups']['output']
        w.batch_name_pattern.setText('{invalid}')
        o.widgets['application']['sound_enabled'].setChecked(False)
        o.policy_boxes['application'].setCurrentIndex(o.policy_boxes['application'].findData('defaults'))
        o.persist()
        saved = json.loads(o.last_path.read_text())['groups']
        policy = json.loads(o.app_path.read_text())['startup']
        self.assertEqual(saved['output'], original)
        self.assertFalse(saved['application']['sound_enabled'])
        self.assertEqual(policy['application'], 'defaults')
        self.assertIn('Output settings were not saved', w.status.text())

        w.close()
        restored = self.window()
        self.assertEqual(restored.batch_name_pattern.text(), 'good_{date}')

    def test_failed_write_does_not_advance_known_good_groups(self):
        w = self.window()
        o = w.options
        w.batch_name_pattern.setText('saved_a_{date}')
        o.persist()
        original = json.loads(o.last_path.read_text())['groups']['output']
        w.batch_name_pattern.setText('never_written_b_{date}')
        real_atomic = options_module.atomic_json
        def fail_last_used(path, data):
            if Path(path) == o.last_path:
                raise OSError('simulated disk failure')
            return real_atomic(path, data)
        with patch('reezsynth_options.atomic_json', side_effect=fail_last_used):
            o.persist()
        self.assertEqual(json.loads(o.last_path.read_text())['groups']['output'], original)
        self.assertEqual(o.saved_groups['output'], original)
        w.batch_name_pattern.setText('{invalid}')
        o.persist()
        self.assertEqual(json.loads(o.last_path.read_text())['groups']['output'], original)

    def test_successful_persist_clears_its_stale_error_status(self):
        w = self.window()
        o = w.options
        o.persist()
        w.batch_name_pattern.setText('{invalid}')
        o.persist()
        self.assertIn('Output settings were not saved', w.status.text())
        w.batch_name_pattern.setText('valid_{date}')
        o.persist()
        self.assertNotIn('settings were not saved', w.status.text())

    def test_successful_persist_leaves_unrelated_status_and_clears_error_ownership(self):
        w = self.window()
        o = w.options
        w.batch_name_pattern.setText('{invalid}')
        o.persist()
        self.assertIsNotNone(o.persistence_error_status)
        w.status.setText('Independent worker status')
        w.batch_name_pattern.setText('valid_{date}')
        o.persist()
        self.assertEqual(w.status.text(), 'Independent worker status')
        self.assertIsNone(o.persistence_error_status)

    def test_write_failure_sets_and_success_clears_persistence_status(self):
        w = self.window()
        o = w.options
        real_atomic = options_module.atomic_json
        with patch('reezsynth_options.atomic_json', side_effect=OSError('disk full')):
            o.persist()
        self.assertIn('Settings could not be saved: disk full', w.status.text())
        self.assertIsNotNone(o.persistence_error_status)
        with patch('reezsynth_options.atomic_json', side_effect=real_atomic):
            o.persist()
        self.assertFalse(w.status.text())
        self.assertIsNone(o.persistence_error_status)

    def test_invalid_processing_size_keeps_render_known_good_and_saves_others(self):
        w = self.window()
        o = w.options
        w.set_processing_size([512, 512])
        o.persist()
        original = json.loads(o.last_path.read_text())['groups']['render']
        w.resolution.setCurrentIndex(w.resolution.findData('custom'))
        w.processing_width.setValue(64)
        w.processing_height.setValue(64)
        o.widgets['application']['sound_enabled'].setChecked(False)
        o.persist()
        saved = json.loads(o.last_path.read_text())['groups']
        self.assertEqual(saved['render'], original)
        self.assertFalse(saved['application']['sound_enabled'])
        self.assertIn('Rendering settings were not saved', w.status.text())

    def test_corrupt_last_used_does_not_abort_restore(self):
        configuration = self.root / 'configuration'
        configuration.mkdir()
        (configuration / 'last-used.json').write_text('{not json', encoding='utf-8')
        w = self.window()
        self.assertFalse(w.options.loading)
        self.assertTrue(all(box.count() for box in w.options.policy_boxes.values()))
        self.assertTrue(any('Last-used settings could not be restored' in error for error in w.options.errors))

    def test_corrupt_startup_policy_does_not_abort_last_used_restore(self):
        configuration = self.root / 'configuration'
        configuration.mkdir()
        (configuration / 'application.json').write_text('{not json', encoding='utf-8')
        (configuration / 'last-used.json').write_text(json.dumps(dict(version=1,
            groups=dict(weights=dict(img_wgt=8)))), encoding='utf-8')
        w = self.window()
        self.assertEqual(w.options.weights()['img_wgt'], 8)
        self.assertTrue(all(box.count() for box in w.options.policy_boxes.values()))
        self.assertTrue(any('Startup policy file could not be restored' in error for error in w.options.errors))

    def test_rejected_last_used_group_is_preserved_for_diagnostics(self):
        configuration = self.root / 'configuration'
        configuration.mkdir()
        rejected = dict(options=dict(patchsize=4), quality='Standard')
        (configuration / 'last-used.json').write_text(json.dumps(dict(version=1,
            groups=dict(render=rejected))), encoding='utf-8')
        w = self.window()
        preserved = json.loads((configuration / 'last-used.rejected.json').read_text())
        self.assertEqual(preserved['groups']['render'], rejected)
        self.assertEqual(w.options.render()['patchsize'], 7)

    def test_restore_exception_resets_loading_state(self):
        with patch.object(gui.Options, '_restore', side_effect=RuntimeError('injected restore failure')):
            w = self.window()
        self.assertFalse(w.options.loading)
        self.assertTrue(any('injected restore failure' in error for error in w.options.errors))

    def test_project_data_validates_video_export_without_validating_snapshot(self):
        w = self.window()
        w.options.video_export_enabled.setChecked(True)
        w.options.video_export_fps.setValue(30)
        w.options.video_export_audio.setText('  "audio.mp3"  ')
        self.assertEqual(w.options.snapshot('render')['video_export']['audio'], '  "audio.mp3"  ')
        self.assertEqual(w.options.project_data()['video_export'],
                         dict(enabled=True, fps=30.0, audio='audio.mp3'))

    def test_persist_group_order_covers_canonical_groups(self):
        self.assertEqual(set(options_module.PERSIST_GROUP_ORDER), set(GROUPS))
        self.assertEqual(len(options_module.PERSIST_GROUP_ORDER), len(GROUPS))

    def test_missing_preset_store_does_not_abort_unrelated_restore(self):
        configuration = self.root / 'configuration'
        configuration.mkdir()
        (configuration / 'presets.json').write_text('{not json', encoding='utf-8')
        (configuration / 'application.json').write_text(json.dumps(dict(version=1,
            startup=dict(render='preset:missing'))), encoding='utf-8')
        (configuration / 'last-used.json').write_text(json.dumps(dict(version=1,
            groups=dict(weights=dict(img_wgt=8)))), encoding='utf-8')
        w = self.window()
        self.assertIsNone(w.options.store)
        self.assertEqual(w.options.weights()['img_wgt'], 8)
        self.assertTrue(all(box.count() for box in w.options.policy_boxes.values()))
        self.assertTrue(any('Startup preset unavailable for render' in error for error in w.options.errors))

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

    def test_float_controls_preserve_six_decimal_places_in_last_used_settings(self):
        w = self.window()
        self.assertEqual(w.image_synthesis.source_weight.decimals(), 6)
        self.assertEqual(w.image_synthesis.key_weight.decimals(), 6)
        w.options.widgets["weights"]["img_wgt"].setValue(6.123456)
        w.options.widgets["render"]["uniformity"].setValue(3500.123456)
        w.options.persist()
        restored = self.window()
        self.assertAlmostEqual(restored.options.weights()["img_wgt"], 6.123456, places=6)
        self.assertAlmostEqual(restored.options.render()["uniformity"], 3500.123456, places=6)

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

    def test_highest_quality_is_render_only(self):
        w = self.window()
        w.set_processing_size([1280, 720])
        w.job_name_pattern.setText('keep_{key}')
        before_blend = w.grouped.blend_options()
        w.quality.setCurrentText('Highest')
        self.assertEqual(w.options.render()['pyramidlevels'], -1)
        self.assertEqual(w.processing_size(), (1280, 720))
        self.assertEqual(w.job_name_pattern.text(), 'keep_{key}')
        self.assertEqual(w.grouped.blend_options(), before_blend)

    def test_every_section_has_builtin_default_and_reset_all_restores_it(self):
        w = self.window()
        self.assertEqual(set(w.options.preset_boxes),
                         {'directories', 'output', 'weights', 'render', 'grouped', 'application', 'image'})
        for box in w.options.preset_boxes.values():
            self.assertEqual(box.itemText(0), 'Default')
            self.assertEqual(box.itemData(0), '__default__')
        w.options.widgets['weights']['img_wgt'].setValue(99)
        w.quality.setCurrentText('Highest')
        w.batch_enabled.setChecked(False)
        w.grouped.mode.setCurrentIndex(w.grouped.mode.findData('forward'))
        w.options.widgets['application']['preview_limit'].setValue(4)
        with patch.object(gui.QMessageBox, 'question', return_value=gui.QMessageBox.StandardButton.Yes):
            w.options.reset_all()
        self.assertEqual(w.options.weights()['img_wgt'], 6)
        self.assertEqual(w.quality.currentText(), 'Standard')
        self.assertTrue(w.batch_enabled.isChecked())
        self.assertEqual(w.grouped.blend_options()['only_mode'], 'none')
        self.assertEqual(w.options.application()['preview_limit'], 8)

    def test_preview_limit_editor_only_offers_accepted_settings(self):
        w = self.window()
        editor = w.options.widgets['application']['preview_limit']
        editor.setValue(1)
        editor.stepDown()
        self.assertEqual(w.options.application()['preview_limit'], 1)
        editor.setValue(64)
        editor.stepUp()
        self.assertEqual(w.options.application()['preview_limit'], 64)
        w.options.persist()
        self.assertEqual(self.window().options.application()['preview_limit'], 64)

    def test_invalid_engine_parameters_are_rejected(self):
        for data in ({"patchsize": 4}, {"feather": 2}, {"uniformity": float("inf")},
                     {"do_mask": 1}, {"edge_method": "unknown"}, {"flow_model": "small"},
                     {"flow_arch": "Other"}, {"flow_arch": "EF_RAFT", "flow_model": "sintel"},
                     {"flow_arch": "FLOW_DIFF", "memory_efficient_raft": True}, {"ebsynth_backend": "vulkan"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_render(data)

    def test_flow_architecture_changes_available_model_choices(self):
        w = self.window()
        architecture = w.options.widgets['render']['flow_arch']
        model = w.options.widgets['render']['flow_model']
        status = {'EF_RAFT': {'models': ['ours_sintel'], 'missing': []},
                  'FLOW_DIFF': {'models': ['FlowDiffuser-things'], 'missing': [], 'timm': True}}
        with patch('reezsynth_options.optional_flow_status', return_value=status):
            architecture.setCurrentText('EF_RAFT')
            self.assertEqual([model.itemText(i) for i in range(model.count())], ['ours_sintel'])
            architecture.setCurrentText('FLOW_DIFF')
            self.assertEqual(model.currentText(), 'FlowDiffuser-things')
            self.assertFalse(model.isEnabled())
            architecture.setCurrentText('RAFT')
            self.assertEqual(model.currentText(), 'sintel')

    def test_uninstalled_optional_architecture_warns_and_reverts_to_raft(self):
        w = self.window()
        architecture = w.options.widgets['render']['flow_arch']
        status = {'EF_RAFT': {'models': [], 'missing': ['ours_sintel']},
                  'FLOW_DIFF': {'models': [], 'missing': ['FlowDiffuser-things'], 'timm': False}}
        with patch('reezsynth_options.optional_flow_status', return_value=status), \
             patch('reezsynth_options.QMessageBox.warning') as warning:
            architecture.setCurrentText('EF_RAFT')
        self.assertEqual(architecture.currentText(), 'RAFT')
        self.assertIn('not installed', warning.call_args.args[1])

    def test_failed_timm_installer_reenables_optional_component_buttons(self):
        w = self.window()
        options = w.options
        options.timm_install_pending = True
        for button in options.optional_flow_buttons:
            button.setEnabled(False)
        with patch('reezsynth_options.QMessageBox.warning') as warning:
            options.flowdiffuser_timm_install_error(None)
        self.assertFalse(options.timm_install_pending)
        self.assertTrue(all(button.isEnabled() for button in options.optional_flow_buttons))
        self.assertIn('failed', warning.call_args.args[2])

    def test_optional_component_installers_are_disabled_while_rendering(self):
        w = self.window()
        w.set_busy(True)
        self.assertTrue(all(not button.isEnabled() for button in w.options.optional_flow_buttons))
        w.set_busy(False)
        self.assertTrue(all(button.isEnabled() for button in w.options.optional_flow_buttons))

    def test_window_refuses_to_close_while_installing_optional_dependency(self):
        w = self.window()
        w.options.timm_install_pending = True
        event = QCloseEvent()
        with patch('reezsynth_gui.QMessageBox.information') as notice:
            w.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertIn('still running', notice.call_args.args[2])
        w.options.timm_install_pending = False

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
    def test_engine_readiness_action_streams_and_restores_controls(self):
        options = self.w.options
        with patch.object(gui.QMessageBox, 'information') as notice:
            options.start_engine_action('test readiness', sys.executable,
                                        ['-c', 'print("ENGINE_CHECK_OK")'])
            self.assertTrue(options.installation_active())
            self.assertTrue(all(not button.isEnabled() for button in options.engine_setup_buttons))
            self.until(lambda: not options.installation_active())
        self.assertIn('ENGINE_CHECK_OK', self.w.log.toPlainText())
        self.assertIn('passed', options.engine_setup_status.text())
        self.assertTrue(all(button.isEnabled() for button in options.engine_setup_buttons))
        notice.assert_called_once()

    def test_engine_rebuild_requires_confirmation_and_uses_force(self):
        options = self.w.options
        with patch('reezsynth_options.rebuild_command',
                   return_value=(sys.executable, ['build_fuoum_engine.py', '--force'])) as command, \
             patch.object(options, 'start_engine_action') as start, \
             patch.object(gui.QMessageBox, 'question',
                          return_value=gui.QMessageBox.StandardButton.Yes):
            options.rebuild_engine_component('fuoum')
        command.assert_called_once_with('fuoum', options.application())
        self.assertIn('--force', start.call_args.args[2])

    def test_selected_raft_weights_are_checked_before_queue_start(self):
        self.w.options.widgets['render']['flow_model'].setCurrentText('kitti')
        with patch('reezsynth_gui.validate_flow_model_available', side_effect=ValueError('Kitti weights are missing')), \
             patch.object(gui.QMessageBox, 'warning') as warning:
            self.w.run_rows(list(self.w.rows))
        self.assertIn('Kitti weights are missing', warning.call_args.args[2])

    def test_project_round_trip_and_older_project_keeps_manual_names(self):
        w = self.w
        w.rows[0]["folder"].setText("manual")
        w.options.widgets["weights"]["img_wgt"].setValue(8)
        w.options.widgets["render"]["uniformity"].setValue(4100)
        w.options.widgets['render']['memory_efficient_raft'].setChecked(True)
        w.options.video_export_enabled.setChecked(True)
        w.options.video_export_fps.setValue(23.976)
        w.options.video_export_audio.setText(str(self.root / 'audio.wav'))
        w.set_processing_size([1536, 864])
        w.project_file = self.root / "project.json"
        w.save_project()
        data = json.loads(w.project_file.read_text())
        self.assertEqual(data["guide_weights"]["img_wgt"], 8)
        self.assertEqual(data['processing_size'], [1536, 864])
        self.assertEqual(data['video_export']['fps'], 23.976)
        w.options.widgets["weights"]["img_wgt"].setValue(2)
        with patch.object(gui.QFileDialog, "getOpenFileName", return_value=(str(w.project_file), "")):
            w.open_project()
        self.assertEqual(w.options.weights()["img_wgt"], 8)
        self.assertEqual(w.options.render()["uniformity"], 4100)
        self.assertTrue(w.options.render()['memory_efficient_raft'])
        self.assertTrue(w.options.snapshot('render')['video_export']['enabled'])
        self.assertEqual(w.processing_size(), [1536, 864])
        for key in ("guide_weights", "render_options", "mask_dir", "output_naming", "video_export"):
            data.pop(key, None)
        data["quality"] = "Standard"
        w.project_file.write_text(json.dumps(data))
        with patch.object(gui.QFileDialog, "getOpenFileName", return_value=(str(w.project_file), "")):
            w.open_project()
        self.assertEqual(w.rows[0]["folder"].text(), "manual")
        self.assertEqual(w.options.weights(), WEIGHTS)
        self.assertEqual(w.options.render()["patchsize"], STANDARD["patchsize"])
        self.assertFalse(w.options.snapshot('render')['video_export']['enabled'])
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
        audio = self.root / 'audio.wav'
        audio.write_bytes(b'wav')
        self.w.options.widgets["render"]["do_mask"].setChecked(True)
        self.w.options.widgets["weights"]["img_wgt"].setValue(8)
        self.w.options.video_export_enabled.setChecked(True)
        self.w.options.video_export_fps.setValue(30)
        self.w.options.video_export_audio.setText(str(audio))
        with patch.object(self.w, "start_next"):
            self.run_queue()
        job = json.loads(self.w.pending[0]["job_path"].read_text())
        self.assertTrue(job["render_options"]["do_mask"])
        self.assertEqual(job["guide_weights"]["img_wgt"], 8)
        self.assertEqual(job['video_export'],
                         {'enabled': True, 'fps': 30.0, 'audio': str(audio.resolve())})
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

    def test_auto_start_retries_after_component_maintenance(self):
        o = self.w.options
        o.auto_timer.stop()
        o.widgets['application']['auto_start'].setChecked(True)
        o.auto_armed = True
        o.engine_action_pending = True
        with patch.object(gui.QMessageBox, 'information') as notice:
            o.maybe_start()
        self.assertTrue(o.auto_armed)
        self.assertIsNone(o.last_auto)
        self.assertTrue(o.auto_timer.isActive())
        self.assertFalse(self.w.busy)
        self.assertIsNone(self.w.process)
        notice.assert_not_called()

        o.engine_action_pending = False
        with patch.object(self.w, 'start_next'):
            o.maybe_start()
        self.assertFalse(o.auto_armed)
        self.assertIsNotNone(o.last_auto)
        self.assertTrue(self.w.busy)
        self.assertTrue(self.w.pending)
        self.w.stop_queue()

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

    def test_parallel_automatic_admits_only_estimated_safe_demand(self):
        self.enable_parallel(0)
        self.mode("slow")
        snapshot = dict(index=0, uuid="GPU-test", name="Test GPU",
                        total_mib=8192, used_mib=3192, free_mib=5000)
        estimate = dict(estimated_mib=3000, width=1920, height=1080,
                        engine=LEGACY, basis="test")
        with patch("reezsynth_parallel.gpu_snapshot", return_value=snapshot), \
             patch("reezsynth_parallel.estimate_job_vram", return_value=estimate):
            self.run_queue()
            self.until(lambda: "MOCK_STARTED" in self.w.log.toPlainText())
            pool = self.w.parallel_queue
            self.assertEqual(len(pool.active), 1)
            self.assertEqual(len(pool.pending), 1)
            self.assertEqual(self.w.rows[1]["state"].text(), "Waiting for GPU memory")
            self.assertIn("estimated peak", self.w.rows[0]["state"].toolTip())
            self.w.stop_queue()
            self.until(lambda: not self.w.busy)

    def test_parallel_automatic_serializes_without_gpu_telemetry(self):
        self.enable_parallel(0)
        self.mode("slow")
        estimate = dict(estimated_mib=1024, width=512, height=288,
                        engine=LEGACY, basis="test")
        with patch("reezsynth_parallel.gpu_snapshot", return_value=None), \
             patch("reezsynth_parallel.estimate_job_vram", return_value=estimate):
            self.run_queue()
            self.until(lambda: "MOCK_STARTED" in self.w.log.toPlainText())
            self.assertEqual(len(self.w.parallel_queue.active), 1)
            self.assertEqual(len(self.w.parallel_queue.pending), 1)
            self.assertIn("telemetry unavailable", self.w.log.toPlainText())
            self.w.stop_queue()
            self.until(lambda: not self.w.busy)

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
