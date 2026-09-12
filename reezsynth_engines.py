"""Engine identity, capability validation and process routing; no Qt/engine imports."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
LEGACY = 'Trentonom0r3/Ezsynth'
FUOUM = 'FuouM/ReEzSynth'
FUOUM_REVISION = 'aaa8d06170e6cc59054410aa9c422edd789f7ab2'
LEGACY_REVISION = 'b198f2d7051eee542c4efc51c2d43dc442630bbf'
ENGINE_OPTIONS = ('engine', 'temporal_nnf', 'sparse_features')


def engine_revision(engine):
    return FUOUM_REVISION if validate_engine(engine) == FUOUM else LEGACY_REVISION


def validate_revision(engine, revision=None):
    expected = engine_revision(engine)
    if revision is not None and revision != expected:
        raise ValueError(f'This frontend supports {engine} revision {expected}; the file requests {revision}.')
    return expected


def validate_engine(engine):
    if engine not in (LEGACY, FUOUM):
        raise ValueError(f'Unknown synthesis engine: {engine}')
    return engine


def default_runtime():
    return dict(fuoum_source=str(ROOT / 'engine_sources' / 'fuoum_reezsynth'),
                fuoum_python=str(ROOT / '.engine_envs' / 'fuoum' / 'Scripts' / 'python.exe'))


def source_revision(root):
    result = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True, timeout=10,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('FuouM source must be a Git checkout. See DUAL_ENGINE.md.')
    return result.stdout.strip()


def prepare_runtime(options, application, require_native=True):
    engine = validate_engine(options.get('engine', LEGACY))
    if engine == LEGACY:
        return dict(engine=engine, revision=LEGACY_REVISION, python=sys.executable, source=str(ROOT))
    source = Path(application.get('fuoum_source') or default_runtime()['fuoum_source']).expanduser().resolve()
    python = Path(application.get('fuoum_python') or default_runtime()['fuoum_python']).expanduser().resolve()
    if not python.is_file():
        raise ValueError('Configure the FuouM Python executable in Settings. See DUAL_ENGINE.md for setup.')
    for name in ('ezsynth/config.py', 'ezsynth/pipeline.py', 'ezsynth/engines/synthesis_engine.py'):
        if not (source / name).is_file():
            raise ValueError(f'FuouM source folder is incomplete: {source / name}')
    revision = source_revision(source)
    if revision != FUOUM_REVISION:
        raise ValueError(f'The FuouM adapter requires revision {FUOUM_REVISION}; found {revision}.')
    if require_native and not list(source.glob('ebsynth_torch*.pyd')):
        raise ValueError('Build the FuouM CUDA extension with build_fuoum_engine.py before rendering. See DUAL_ENGINE.md.')
    return dict(engine=engine, revision=revision, python=str(python), source=str(source))


def validate_capabilities(options, *, image=False, blend=None, exports=None):
    if validate_engine(options.get('engine', LEGACY)) == LEGACY:
        return
    if options.get('ebsynth_backend', 'cuda') != 'cuda':
        raise ValueError('FuouM/ReEzSynth currently requires the CUDA synthesis backend.')
    if image:
        return
    unsupported = []
    for key, label in (('memory_efficient_raft', 'the legacy memory-efficient RAFT extension'),):
        if options.get(key):
            unsupported.append(label)
    if options.get('flow_arch', 'RAFT') != 'RAFT':
        unsupported.append('EF-RAFT/FlowDiffuser')
    if (blend or {}).get('use_gpu') or (blend or {}).get('use_poisson_cupy'):
        unsupported.append('CuPy blending')
    if unsupported:
        raise ValueError('FuouM/ReEzSynth does not yet support these frontend options: '
                         + ', '.join(unsupported) + '. Disable them or select Trentonom0r3/Ezsynth.')


def fuoum_checkpoint(options, source):
    if options.get('fuoum_flow_engine', 'RAFT') == 'NeuFlow':
        return Path(source) / 'models/neuflow' / (options.get('fuoum_neuflow_model', 'neuflow_sintel') + '.pth')
    return Path(source) / 'models/raft' / ('raft-' + options.get('fuoum_raft_model', options.get('flow_model', 'sintel')) + '.pth')


def legacy_checkpoint(options, source):
    root = Path(source) / 'ezsynth/utils/flow_utils'
    architecture, model = options.get('flow_arch', 'RAFT'), options.get('flow_model', 'sintel')
    if architecture == 'RAFT':
        return root / 'models' / f'raft-{model}.pth'
    if architecture == 'EF_RAFT':
        return root / 'ef_raft_models' / f'{model}.pth'
    if architecture == 'FLOW_DIFF':
        return root / 'flow_diffusion_models/FlowDiffuser-things.pth'
    raise ValueError('Unknown flow architecture.')


def file_sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def runtime_component(name):
    """Locate/hash the actual loaded or importable binary without initializing it."""
    module = sys.modules.get(name)
    origin = getattr(module, '__file__', None)
    if not origin:
        try:
            spec = importlib.util.find_spec(name)
            origin = spec.origin if spec else None
        except (ImportError, ValueError):
            origin = None
    if not origin or not Path(origin).is_file():
        return dict(available=False)
    path = Path(origin).resolve()
    return dict(available=True, path=str(path), sha256=file_sha256(path))


def preflight_flow(options, runtime):
    if options.get('engine', LEGACY) == LEGACY:
        from reezsynth_config import validate_flow_model_available
        return validate_flow_model_available(options['flow_model'], options['flow_arch'])
    model = fuoum_checkpoint(options, runtime['source'])
    if not model.is_file() or not model.stat().st_size:
        raise ValueError(f'FuouM optical-flow checkpoint is missing: {model}. See DUAL_ENGINE.md.')
    return model


def activate_fuoum(runtime):
    """Bind the namespace once in the dedicated worker; never swap imported engines."""
    import types
    from importlib.machinery import ModuleSpec
    root = Path(runtime['source']).resolve()
    if not Path(sys.executable).samefile(runtime['python']):
        raise RuntimeError('This job must run with its selected FuouM Python executable.')
    checked = prepare_runtime({'engine': FUOUM}, dict(fuoum_source=str(root), fuoum_python=sys.executable))
    if checked['revision'] != runtime['revision']:
        raise RuntimeError('FuouM source revision changed after the job was prepared.')
    loaded = sys.modules.get('ezsynth')
    if loaded is not None and getattr(loaded, '_frontend_source', None) != str(root):
        raise RuntimeError('Cannot load both ezsynth packages into one worker. Start a new queue.')
    if loaded is None:
        if any(name.startswith('ezsynth.') for name in sys.modules):
            raise RuntimeError('A different ezsynth engine is already loaded in this worker.')
        package = types.ModuleType('ezsynth')
        package.__path__ = [str(root / 'ezsynth')]
        package.__package__ = 'ezsynth'
        package.__spec__ = ModuleSpec('ezsynth', loader=None, is_package=True)
        package.__spec__.submodule_search_locations = package.__path__
        package._frontend_source = str(root)
        sys.modules['ezsynth'] = package
        sys.path.insert(0, str(root))
    os.chdir(root)


def write_engine_manifest(job):
    engine = validate_engine(job.get('render_options', {}).get('engine', LEGACY))
    runtime = job.get('engine_runtime') or prepare_runtime({'engine': engine}, {})
    if runtime.get('engine') != engine:
        raise ValueError('Job engine and runtime do not match.')
    from reezsynth_provenance import effective_settings
    effective = effective_settings(job)
    source = Path(runtime['source'])
    files = list((source / 'ezsynth').rglob('*.py'))
    if engine == FUOUM:
        files += list((source / 'ebsynth_extension').glob('*')) + list(source.glob('ebsynth_torch*.pyd'))
    else:
        files += list((source / 'ezsynth/utils').glob('ebsynth.dll'))
    hashes = {path.relative_to(source).as_posix(): file_sha256(path)
              for path in files if path.is_file()}
    components = {}
    if engine == FUOUM:
        components['ebsynth_torch'] = runtime_component('ebsynth_torch')
    if job.get('type') != 'image_synthesis' and len(job.get('frames', [])) > 1:
        options = job.get('render_options', {})
        if engine == FUOUM:
            checkpoint = fuoum_checkpoint(options, source)
        else:
            checkpoint = legacy_checkpoint(options, source)
        checkpoints = [checkpoint]
        if engine == LEGACY and options.get('flow_arch') == 'FLOW_DIFF':
            checkpoints += [checkpoint.parent / 'twins_svt_large.pth',
                            checkpoint.parent / 'twins_svt_small.pth']
        for selected in checkpoints:
            if selected.is_file():
                hashes[selected.relative_to(source).as_posix()] = file_sha256(selected)
        if engine == LEGACY and options.get('memory_efficient_raft'):
            components['alt_cuda_corr'] = runtime_component('alt_cuda_corr')
    import importlib.metadata
    versions = {}
    for name in ('torch', 'torchvision', 'numpy', 'opencv-python', 'pydantic', 'scipy', 'einops', 'pyamg',
                 'reezsynth-alt-cuda-corr', 'timm', 'huggingface_hub', 'safetensors',
                 'cupy', 'cupy-cuda12x', 'cupy-cuda13x'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    from reezsynth_config import atomic_json
    manifest = dict(version=2, **runtime, source_sha256=hashes, package_versions=versions,
                    runtime_components=components, effective_settings=effective,
                    adapter_sha256={name: file_sha256(ROOT / name)
                                    for name in ('reezsynth_jobs.py', 'reezsynth_image.py', 'reezsynth_fuoum.py',
                                                 'reezsynth_fuoum_pipeline.py', 'reezsynth_raft.py',
                                                 'reezsynth_engines.py', 'reezsynth_provenance.py',
                                                 'reezsynth_config.py', 'reezsynth_video_plan.py',
                                                 'reezsynth_artifacts.py', 'reezsynth_video_export.py',
                                                 'reezsynth_preview_transport.py',
                                                 'reezsynth_precompute_cache.py')},
                    render_options=job.get('render_options', {}), guide_weights=job.get('guide_weights', {}),
                    blend_options=job.get('blend_options', {}),
                    video_export=job.get('video_export', {}))
    atomic_json(Path(job['output']) / 'engine_manifest.json', manifest)
    print('[Engine] ' + json.dumps(dict(engine=engine, revision=runtime['revision'], python=sys.executable)), flush=True)
    return manifest
