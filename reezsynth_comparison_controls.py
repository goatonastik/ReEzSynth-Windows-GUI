"""Short, frozen-settings comparisons submitted to the ordinary isolated queue."""
import sys
from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QLabel,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout)

from reezsynth_comparison import COMPARISON_KINDS, comparison_plans


def submit_comparison(window, video, keys, padding, start, end, kind):
    from reezsynth_config import atomic_json, validate_application
    from reezsynth_jobs import ROOT, validate_masks, validate_edge_guides, validate_video_dimensions
    from reezsynth_engines import prepare_runtime, validate_capabilities, preflight_flow, file_sha256
    from reezsynth_modulation import validate_video_maps
    from reezsynth_project_controls import create_batch_directory
    from reezsynth_output_location import create_unique_directory
    from reezsynth_fuoum_pipeline import work_count

    options = window.options
    if (window.busy or window.process is not None or window.close_when_idle or
            options.installation_active() or options.edge_preview_active()):
        raise ValueError('Finish or cancel the current render, preview, or component operation first.')
    plans = comparison_plans(video, keys, start, end, kind,
        options.render(effective=True), window.grouped.blend_options(effective=True))
    application = validate_application(dict(options.application(), parallel=False))
    selected = dict(plans[0]['plan']['frames'])
    validate_video_dimensions(selected, dict(plans[0]['plan']['styles']))
    processing_size, max_width = window.processing_size(), window.processing_max_width()
    weights = options.weights()
    prepared = []
    for variant in plans:
        render = variant['render_options']
        runtime = prepare_runtime(render, application)
        validate_capabilities(render, blend=variant['plan']['blend_options'], exports={})
        preflight_flow(render, runtime)
        masks = validate_masks(window.mask_dir.text(), video) if render['do_mask'] else {}
        edges = validate_edge_guides(window.edge_dir.text(), video) if render['custom_edge_guides'] else {}
        maps = validate_video_maps(render, video)
        prepared.append((variant, runtime, masks, edges, maps))
    project = Path(window.path_value(window.project_dir))
    batch = create_batch_directory(window, project)
    records, descriptors = [], []
    for variant, runtime, masks, edges, maps in prepared:
        destination = create_unique_directory(batch, variant['folder'])
        plan = variant['plan']
        numbers = [n for n, _ in plan['frames']]
        weight = work_count(len(numbers), [numbers.index(n) for n, _ in plan['styles']], plan['blend_options']['only_mode'])
        job = dict(plan, output=str(destination), padding=padding,
            quality=window.quality.currentText(), processing_size=processing_size, max_width=max_width,
            precompute_cache=str((project / '.reezsynth-cache').resolve()),
            synthesis_work=weight, render_options=variant['render_options'], engine_runtime=runtime,
            exports={}, video_export={}, guide_weights=weights,
            masks=[[n, str(masks[n])] for n in numbers] if masks else [],
            edge_guides=[[n, str(edges[n])] for n in numbers] if edges else [],
            modulation_frames=[[n, str(maps[n])] for n in numbers] if maps else [])
        path = destination / 'job.json'
        atomic_json(path, job)
        descriptors.append(dict(label=variant['label'], job=str(path), job_sha256=file_sha256(path)))
        records.append(dict(key=variant['label'], job_path=path, output=destination,
            weight=max(1, weight), python=runtime['python']))
    destination = create_unique_directory(batch, 'comparison_sheet')
    path = destination / 'job.json'
    atomic_json(path, dict(type='comparison_sheet', output=str(destination),
        frames=plans[0]['plan']['frames'], comparison_kind=kind, comparison_variants=descriptors))
    records.append(dict(key='Static comparison sheet', job_path=path,
        output=destination, weight=1, python=sys.executable))
    options.last_comparison_sheet = destination / 'contact_sheet.png'
    for record in records:
        record['row'] = window.recovery_row(dict(key=record['key'], label=record['key']), record['output'])
    options.auto_timer.stop()
    options.auto_armed = False
    window.start_records(records, batch, False, False, ROOT / 'reezsynth_jobs.py', application)
    if not window.busy:
        raise RuntimeError('The comparison queue did not start. See the queue error; prepared job files were preserved.')
    return batch


def open_comparison(window):
    from reezsynth_jobs import build_plan
    try:
        video, keys, padding, _ = build_plan(window.path_value(window.video_dir), window.path_value(window.keyframe_dir))
    except Exception as exc:
        QMessageBox.warning(window, 'Cannot compare', str(exc))
        return
    dialog = QDialog(window)
    dialog.setWindowTitle('Short comparison renders')
    layout = QVBoxLayout(dialog)
    note = QLabel('Render the same short range with named settings variants. All other current settings stay fixed.\n'
        'Choose 2–64 consecutive frames containing at least one keyframe and a non-keyframe.\n'
        'Reconstruction comparisons need at least two keyframes and normal blending.\n'
        'Outputs are PNG sequences plus a static contact sheet, not synchronized playback or a speed benchmark.\n'
        'Experimental torch can differ from CUDA. Each variant runs in its own process, sequentially.')
    note.setWordWrap(True)
    layout.addWidget(note)
    form = QFormLayout()
    start, end = QSpinBox(), QSpinBox()
    for spin in (start, end):
        spin.setRange(min(video), max(video))
    first = min(keys)
    start.setValue(max(min(video), first - 2))
    second = sorted(keys)[1] if len(keys) > 1 else first
    end.setValue(min(max(video), max(start.value() + 4, second)))
    kind = QComboBox()
    for value, label in COMPARISON_KINDS.items():
        kind.addItem(label, value)
    form.addRow('First frame', start)
    form.addRow('Last frame', end)
    form.addRow('Compare', kind)
    layout.addLayout(form)
    queue = QPushButton('Queue comparisons')
    layout.addWidget(queue)
    def submit():
        try:
            batch = submit_comparison(window, video, keys, padding, start.value(), end.value(), kind.currentData())
        except Exception as exc:
            QMessageBox.warning(dialog, 'Cannot queue comparisons', str(exc))
            return
        dialog.accept()
        window.status.setText('Comparison queue started. The final output folder contains contact_sheet.png and comparison_manifest.json.')
        # The existing output-folder action remains usable after completion.
        window.log.appendPlainText('Comparison batch: ' + str(batch))
    queue.clicked.connect(submit)
    dialog.exec()
