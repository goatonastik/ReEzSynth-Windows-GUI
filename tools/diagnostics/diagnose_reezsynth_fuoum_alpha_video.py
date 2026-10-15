"""Opt-in transparent FuouM end-to-end small-job matrix; no bundled media."""

# Support direct execution from any working directory.
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np
from reezsynth_config import atomic_json, validate_render
from reezsynth_engines import FUOUM, prepare_runtime, file_sha256
from reezsynth_synthetic_inputs import frame, write


def preview_sheet(report):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout
    from PySide6.QtGui import QFont
    from reezsynth_preview import PreviewTile
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont('Segoe UI', 10))
    widget = QWidget(); layout = QHBoxLayout(widget)
    for title, relative in [('Original keyframe', 'inputs/key000.png'),
                            ('Transparent artwork', 'mask_clip/000.png'),
                            ('Composite onto source', 'mask_composite/000.png')]:
        tile = PreviewTile(title)
        tile.set_path(report / relative)
        layout.addWidget(tile)
    widget.resize(960, 320); widget.show(); app.processEvents()
    widget.grab().save(str(report / 'preview.png'))
    widget.close()


def main():
    root = Path(__file__).resolve().parents[2]
    report = root / 'diagnostic_outputs' / ('fuoum_alpha_video_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    report.mkdir(parents=True)
    inputs = report / 'inputs'; inputs.mkdir()
    frames, styles, masks = [], [], []
    for n in range(3):
        path = inputs / f'frame{n:03}.png'; write(path, frame((128, 128), n, 3))
        frames.append([n, str(path)])
        path = inputs / f'mask{n:03}.png'; write(path, np.full((128, 128), 128, np.uint8))
        masks.append([n, str(path)])
    for n in (0, 2):
        image = np.zeros((128, 128, 4), np.uint8)
        cv2.circle(image, (54 + n * 5, 64), 30, (0, 0, 0, 255), 2, cv2.LINE_AA)
        cv2.circle(image, (46 + n * 5, 55), 4, (255, 255, 255, 255), -1, cv2.LINE_AA)
        cv2.ellipse(image, (54 + n * 5, 78), (10, 4), 0, 0, 180, (0, 0, 90, 255), -1, cv2.LINE_AA)
        image[image[..., 3] == 0, :3] = 255  # Invisible RGB must not leak into generated frames.
        path = inputs / f'key{n:03}.png'; write(path, image)
        styles.append([n, str(path)])
    options = validate_render(dict(engine=FUOUM, patchsize=3, pyramidlevels=1,
        searchvoteiters=1, patchmatchiters=1, extrapass3x3=True))
    input_hashes = {path.name: file_sha256(path) for path in inputs.iterdir()}
    runtime = prepare_runtime(options, {})
    cases = [(solver, {}, {}, solver) for solver in ('lsqr', 'lsmr', 'cg', 'amg', 'seamless', 'disabled')]
    cases += [('forward', {}, {'only_mode': 'forward'}, 'disabled'),
        ('reverse', {}, {'only_mode': 'reverse'}, 'disabled'),
        ('bidirectional_disk', {'fuoum_bidirectional_flow': True, 'stream_frames': True}, {}, 'lsqr'),
        ('mask_clip', {'do_mask': True, 'feather': 3}, {}, 'lsqr'),
        ('mask_composite', {'do_mask': True, 'fuoum_alpha_mask_mode': 'Composite onto source'}, {}, 'lsqr'),
        ('premask', {'do_mask': True, 'pre_mask': True}, {}, 'lsqr'),
        ('mixed', {}, {}, 'lsqr'), ('torch', {'fuoum_backend': 'torch'}, {}, 'lsqr'),
        ('single', {}, {}, 'lsqr'), ('image', {}, {}, 'lsqr')]
    passed = []
    for label, changes, blend_changes, solver in cases:
        output = report / label; output.mkdir()
        selected_styles = [list(entry) for entry in styles]
        if label == 'mixed':
            selected_styles[0][1] = frames[0][1]
        selected = dict(options, **changes)
        job = dict(type='grouped_video', key=0, style=selected_styles[0][1], frames=frames,
            styles=selected_styles, output=str(output), padding=3, quality='Preview', max_width=0,
            render_options=selected, engine_runtime=runtime, precompute_cache=str(report / 'cache'),
            blend_options=dict(fuoum_poisson_solver=solver, poisson_maxiter=20, **blend_changes),
            masks=masks if selected['do_mask'] else [])
        if label == 'single':
            job.update(type=None, frames=frames[:1]); job.pop('styles')
        elif label == 'image':
            job.update(type='image_synthesis', image_synthesis=dict(style=styles[0][1], source=frames[0][1], target=frames[1][1]))
        path = output / 'job.json'; atomic_json(path, job)
        result = subprocess.run([runtime['python'], '-B', str(root / 'reezsynth_jobs.py'), str(path)],
            cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (output / 'diagnostic.log').write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
        if result.returncode or not (output / 'COMPLETE.txt').is_file():
            raise RuntimeError(f'{label} failed; inspect {output / "diagnostic.log"}')
        files = sorted(output.glob('*.png'))
        if len(files) != (1 if label in ('single', 'image') else 3):
            raise RuntimeError(f'{label}: unexpected output count')
        for image_path in files:
            pixels = cv2.imdecode(np.frombuffer(image_path.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
            assert pixels.shape == (128, 128, 4) and pixels.dtype == np.uint8
            if label == 'mask_composite':
                assert np.all(pixels[..., 3] == 255)
            elif label != 'mixed' or image_path.stem != '000':
                assert np.any(pixels[..., 3] < 255)
        if label not in ('mask_clip', 'mask_composite', 'premask', 'image'):
            for n, input_path in selected_styles:
                if label == 'single' and n != 0:
                    continue
                expected = cv2.imread(input_path, cv2.IMREAD_UNCHANGED)
                if expected.shape[2] == 3:
                    expected = cv2.cvtColor(expected, cv2.COLOR_BGR2BGRA)
                np.testing.assert_array_equal(cv2.imread(str(output / f'{n:03}.png'), cv2.IMREAD_UNCHANGED), expected)
        assert not list(output.glob('.frame-storage-*')) and not list(output.glob('.fuoum-cache-*'))
        passed.append(label)
        print(label + ': passed', flush=True)
    assert input_hashes == {path.name: file_sha256(path) for path in inputs.iterdir()}
    atomic_json(report / 'summary.json', dict(passed=True, size=[128, 128], cases=passed, input_sha256=input_hashes,
        exact_unmasked_keys=True, source_inputs_unchanged=True,
        note='Small contract checks, not production-resolution visual quality certification.'))
    print('Retained diagnostic: ' + str(report), flush=True)
    preview_sheet(report)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--preview':
        preview_sheet(Path(sys.argv[2]))
    else:
        main()
