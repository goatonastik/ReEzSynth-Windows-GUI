"""Confirmation-first native interchange; does not launch jobs or alter media."""
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog

from reezsynth_native_yaml import read_native_yaml, import_settings, export_project, write_native_yaml


def ensure_idle(window):
    if (window.busy or window.process is not None or window.close_when_idle or
            window.options.installation_active() or window.options.edge_preview_active()):
        raise ValueError('Finish or cancel the active render, preview, or component operation first.')


def confirm(window, title, summary, notes):
    box = QMessageBox(window)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(summary)
    box.setInformativeText('Review compatibility details before continuing. This is not a lossless native/frontend round trip.')
    box.setDetailedText('\n\n'.join(notes))
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


def apply_import(window, settings):
    """Replace validated render groups; preserve paths, queue, runtime and presets."""
    from reezsynth_config import validate_group
    ensure_idle(window)
    options = window.options
    render = validate_group('render', dict(options=settings['render_options'], quality='Standard', exports={}, video_export={}))
    weights = validate_group('weights', settings['guide_weights'])
    grouped = validate_group('grouped', dict(selection=window.grouped.selection(), blend_options=settings['blend_options']))
    previous = dict(render=options.snapshot('render'), weights=options.snapshot('weights'),
        grouped=options.snapshot('grouped'), processing_size=window.processing_size(), max_width=window.processing_max_width())
    loading = window.loading_project
    window.loading_project = True
    options.auto_timer.stop()
    options.auto_armed = False
    try:
        options.apply('render', render)
        options.apply('weights', weights)
        options.apply('grouped', grouped)
        window.set_processing_size(None, 0)
    except Exception:
        options.apply('render', previous['render'])
        options.apply('weights', previous['weights'])
        options.apply('grouped', previous['grouped'])
        window.set_processing_size(previous['processing_size'], previous['max_width'])
        raise
    finally:
        window.loading_project = loading
        options.auto_timer.stop()
        options.auto_armed = False
        options.refresh_engine_controls()
    options.changed()


def import_native(window):
    try:
        ensure_idle(window)
        path, _ = QFileDialog.getOpenFileName(window, 'Import native FuouM settings', '', 'Native FuouM YAML (*.yaml *.yml)')
        if not path:
            return
        settings, notes = import_settings(read_native_yaml(path))
        if not confirm(window, 'Import native FuouM settings?',
                'Replace rendering, weights and blending with supported native settings?\n'
                'Current inputs, keyframe selection and output naming will NOT change. Resolution resets to Original; exports are disabled.\n'
                'Unsupported native fields will NOT be applied.', notes):
            return
        apply_import(window, settings)
        window.log.appendPlainText('Native settings imported: ' + path + '\n' + '\n'.join(notes))
        window.status.setText('Native settings imported. Inputs unchanged; inspect Rendering and Blend / Flow, then save a GUI project if desired.')
    except Exception as exc:
        QMessageBox.warning(window, 'Cannot import native YAML', str(exc))


def export_native(window):
    from reezsynth_jobs import build_plan, validate_masks
    try:
        ensure_idle(window)
        video, keys, _, _ = build_plan(window.path_value(window.video_dir), window.path_value(window.keyframe_dir))
        path, _ = QFileDialog.getSaveFileName(window, 'Export native FuouM project', 'fuoum-native.yaml', 'Native FuouM YAML (*.yaml *.yml)')
        if not path:
            return
        path = Path(path)
        if path.suffix.lower() not in ('.yaml', '.yml'):
            raise ValueError('Use a .yaml or .yml filename for native interchange.')
        destination, accepted = QInputDialog.getText(window, 'Native output folder',
            'New folder for native CLI outputs (not created now):', text=str(path.resolve().parent / (path.stem + '_output')))
        if not accepted:
            return
        if not destination.strip() or not Path(destination).is_absolute():
            raise ValueError('Specify an absolute new native output-folder path.')
        render = window.options.render(effective=True)
        if render['do_mask']:
            validate_masks(window.mask_dir.text(), video)
        native, notes = export_project(video, keys, window.grouped.selection(), render,
            window.options.weights(), window.grouped.blend_options(effective=True), destination,
            mask_dir=window.mask_dir.text(), context=dict(window.options.snapshot('render'),
                processing_size=window.processing_size(), max_width=window.processing_max_width()))
        if not confirm(window, 'Export native FuouM project?',
                'Write a native YAML project for the full source folder?\n'
                'Unsupported GUI features are omitted; native results can differ. No render will start.', notes):
            return
        write_native_yaml(path, native, notes)
        window.log.appendPlainText('Native YAML exported: ' + str(path) + '\n' + '\n'.join(notes))
        window.status.setText('Native YAML exported. GUI project/settings unchanged; no jobs started.')
    except Exception as exc:
        QMessageBox.warning(window, 'Cannot export native YAML', str(exc))
