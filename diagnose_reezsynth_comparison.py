"""Opt-in real three-frame FuouM comparison and contact-sheet diagnostic."""
from datetime import datetime
from pathlib import Path
import subprocess
import sys

from reezsynth_comparison import comparison_plans
from reezsynth_config import atomic_json, quality_profile
from reezsynth_engines import FUOUM, prepare_runtime, file_sha256
from reezsynth_synthetic_inputs import frame, style, write

def main():
    root = Path(__file__).resolve().parent
    batch = root / 'diagnostic_outputs' / ('comparison_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    batch.mkdir(parents=True)
    inputs = batch / 'inputs'; inputs.mkdir()
    video, keys = {}, {}
    for n in range(3):
        video[n] = inputs / f'frame{n:03}.png'
        write(video[n], frame((128, 128), n, 3))
    for n in (0, 2):
        keys[n] = inputs / f'key{n:03}.png'
        write(keys[n], style(frame((128, 128), n, 3)))
    plans = comparison_plans(video, keys, 0, 2, 'directions',
        dict(quality_profile('Preview'), engine=FUOUM), {})
    variants = []
    jobs = []
    for variant in plans:
        output = batch / variant['folder']; output.mkdir()
        runtime = prepare_runtime(variant['render_options'], {})
        job = dict(variant['plan'], output=str(output), quality='Preview', padding=3, max_width=0,
            render_options=variant['render_options'], engine_runtime=runtime,
            precompute_cache=str(batch / 'cache'))
        path = output / 'job.json'; atomic_json(path, job)
        variants.append(dict(label=variant['label'], job=str(path), job_sha256=file_sha256(path)))
        jobs.append((runtime['python'], path, output))
    output = batch / 'comparison_sheet'; output.mkdir()
    path = output / 'job.json'
    atomic_json(path, dict(type='comparison_sheet', output=str(output), frames=plans[0]['plan']['frames'],
        comparison_kind='directions', comparison_variants=variants))
    jobs.append((sys.executable, path, output))
    for python, path, output in jobs:
        result = subprocess.run([python, '-B', str(root / 'reezsynth_jobs.py'), str(path)],
            cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (output / 'diagnostic.log').write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
        if result.returncode or not (output / 'COMPLETE.txt').is_file():
            raise RuntimeError(f'Diagnostic failed: {output}')
        print(f'{output.name}: passed', flush=True)
    print(f'Retained comparison: {output / "contact_sheet.png"}', flush=True)

if __name__ == '__main__':
    main()
