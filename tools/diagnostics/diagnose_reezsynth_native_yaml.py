"""Opt-in native YAML check against the installed pinned Pydantic schema; no render."""

# Support direct execution from any working directory.
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datetime import datetime
import json
from pathlib import Path
import subprocess

from reezsynth_config import atomic_json, validate_render
from reezsynth_engines import FUOUM, prepare_runtime
from reezsynth_native_yaml import export_project, import_settings, write_native_yaml, read_native_yaml
from reezsynth_synthetic_inputs import frame, style, write


def main():
    root = Path(__file__).resolve().parents[2]
    report = root / 'diagnostic_outputs' / ('native_yaml_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    report.mkdir(parents=True)
    source, drawing = report / 'source', report / 'keys'
    source.mkdir(); drawing.mkdir()
    video, keys = {}, {}
    for index, number in enumerate((100, 101, 102)):
        image = frame((128, 128), index, 3)
        video[number] = source / f'frame{number:03}.png'
        write(video[number], image)
        if index in (0, 2):
            keys[number] = drawing / f'key{number:03}.png'
            write(keys[number], style(image))
    options = validate_render(dict(engine=FUOUM, pyramidlevels=-1))
    native, notes = export_project(video, keys, {}, options, {'key_wgt': 2}, {}, report / 'native-output')
    path = report / 'native.yaml'
    write_native_yaml(path, native, notes)
    imported, import_notes = import_settings(read_native_yaml(path))
    runtime = prepare_runtime(options, {}, require_native=False)
    code = (
        'import importlib.util,json,sys,yaml;'
        'spec=importlib.util.spec_from_file_location("native_schema",sys.argv[1]);'
        'module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);'
        'data=yaml.safe_load(open(sys.argv[2],encoding="utf-8"));'
        'config=module.MainConfig(**data);'
        'assert config.project.style_indices == [0,2];'
        'assert config.pipeline.pyramid_levels == 32;'
        'assert config.ebsynth_params.image_weight == 3;'
        'print(json.dumps({"native_schema_accepted":True,"style_indices":config.project.style_indices}))'
    )
    result = subprocess.run([runtime['python'], '-c', code, str(Path(runtime['source']) / 'ezsynth/config.py'), str(path)],
        cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (report / 'schema.log').write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Native schema rejected the export; inspect {report / "schema.log"}')
    assert not (report / 'native-output').exists()
    assert not (report / 'native-output_cache').exists()
    atomic_json(report / 'summary.json', dict(passed=True, native_schema=json.loads(result.stdout),
        engine_runtime=runtime, export_notes=notes, imported_settings=imported, import_notes=import_notes,
        render_performed=False, native_output_or_cache_created=False))
    print(f'Pinned native schema accepted the export; supported settings imported. No render launched.\nRetained diagnostic: {report}', flush=True)


if __name__ == '__main__':
    main()
