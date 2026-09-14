"""Versioned frontend settings; no rendering-engine imports."""
import copy
import hashlib
import json
import importlib.util
import importlib.metadata
import math
import shutil
from pathlib import Path
from reezsynth_serialization import read_document, write_document
from reezsynth_video_plan import validate_blend_options, validate_grouped_selection
from reezsynth_artifacts import validate_exports
from reezsynth_image import validate_image_settings
from reezsynth_engines import LEGACY, FUOUM, validate_engine, validate_revision
from reezsynth_iterations import SCHEDULE_FIELDS, parse_schedule, validate_schedule
from reezsynth_modulation import VIDEO_MODES

WEIGHTS = {"edg_wgt": 1.0, "img_wgt": 6.0, "pos_wgt": 2.0, "wrp_wgt": 0.5,
           "key_wgt": 1.0, "mask_wgt": 0.0}
PREVIEW = dict(uniformity=3500.0, patchsize=5, pyramidlevels=3,
               searchvoteiters=4, patchmatchiters=3, extrapass3x3=False,
               searchvote_schedule=[], patchmatch_schedule=[])
STANDARD = dict(uniformity=3500.0, patchsize=7, pyramidlevels=6,
                searchvoteiters=12, patchmatchiters=6, extrapass3x3=True,
                searchvote_schedule=[], patchmatch_schedule=[])
HIGHEST = dict(STANDARD, pyramidlevels=-1)
RENDER = dict(engine=LEGACY, **STANDARD, edge_method="Classic", do_mask=False, pre_mask=False, feather=0,
              custom_edge_guides=False, memory_efficient_raft=False, flow_arch="RAFT",
              flow_model="sintel", ebsynth_backend="cuda", temporal_nnf=True, sparse_features=True,
              fuoum_vote_mode="weighted", fuoum_cost_function="ssd", fuoum_stop_threshold=5,
              fuoum_search_pruning_threshold=50.0, fuoum_sparse_anchor_weight=10.0,
              fuoum_flow_engine='RAFT', fuoum_neuflow_model='neuflow_sintel', fuoum_raft_model='sintel',
              fuoum_bidirectional_flow=False, stream_frames=False,
              modulation_guide='Off', modulation_dir='', fuoum_backend='cuda')
APPLICATION = dict(discover=False, keys_prefix="keys", video_prefix="video",
    auto_start=False, wait_for_mask=False, parallel=False, parallel_limit=2,
    sound_enabled=True, sound_each=False, sound_queue=True, sound_file="",
    reuse_queue_worker=True, preview_limit=8, fuoum_source='', fuoum_python='')
GROUPS = ("directories", "output", "weights", "render", "grouped", "application", "image")
LIMITS = {"uniformity": (0, 100000), "patchsize": (3, 99), "pyramidlevels": (-1, 32),
    "searchvoteiters": (1, 1000), "patchmatchiters": (1, 1000), "feather": (0, 999),
    "fuoum_stop_threshold": (0, 100000), "fuoum_search_pruning_threshold": (0, 100000),
    "fuoum_sparse_anchor_weight": (0, 10000), "parallel_limit": (0, 64), "preview_limit": (1, 64)}
# UI projections of integer rules that remain authoritatively validated in
# validate_render().
SPIN_RULES = {
    'patchsize': 'odd',
    'feather': 'zero_or_odd',
    'pyramidlevels': 'nonzero',
}
OPTIONAL_FLOW_HASHES = {
    '25000_ours-sintel.pth': '4fb2df7d7a44f2479262aa5f873472c9c48ee2fd4c4f5bf5e9b2df50a94ea52c',
    'ours-things.pth': 'adab5f373882e66aca4cefcd8783e50b280165367f145b16af708fe5aaf9fbc8',
    'ours_sintel.pth': '8e1be5a14f7c734fee9289f68a6ffd35a446039de488f2f4b9bf94738b1e87ad',
    'FlowDiffuser-things.pth': 'a653fa5d549aa80677ed02c158fe0363b453183ed0235eb0cc8557e488a8b1c3',
}

QUALITY_PROFILES = {
    "Preview": PREVIEW,
    "Standard": STANDARD,
    "Highest": HIGHEST,
}


def quality_profile(name):
    """Return the built-in synthesis-only settings for a named quality level."""
    try:
        return copy.deepcopy(QUALITY_PROFILES[name])
    except KeyError as exc:
        raise ValueError("Unknown quality preset.") from exc

PROCESSING_PRESETS = (
    ('original', 'Original resolution', None), ('square_512', '512 1:1', (512, 512)),
    ('square_1024', '1024 1:1', (1024, 1024)), ('landscape_720', '720p 16:9', (1280, 720)),
    ('portrait_720', '720p 9:16', (720, 1280)), ('landscape_1080', '1080p 16:9', (1920, 1080)),
    ('portrait_1080', '1080p 9:16', (1080, 1920)), ('custom', 'Custom', None),
)

def validate_processing_size(value):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(type(item) is not int for item in value):
        raise ValueError('Processing size must be Original resolution or a width and height.')
    if not all(128 <= item <= 16384 for item in value):
        raise ValueError('Processing width and height must be between 128 and 16384.')
    return [*value]


def validate_processing_settings(data):
    """Retain legacy width limits; exact dimensions and width limits are exclusive."""
    size = validate_processing_size(data.get('processing_size'))
    width = data.get('max_width', 0)
    if type(width) is not int or width not in (0, 512, 960):
        raise ValueError('Unknown legacy maximum width.')
    if size is not None and width:
        raise ValueError('Choose exact processing dimensions or a legacy maximum width, not both.')
    return dict(processing_size=size, max_width=width)


def validate_flow_model_available(flow_model, flow_arch="RAFT"):
    """Preflight optional flow assets without importing torch or loading a model."""
    root = Path(__file__).parent / "ezsynth" / "utils" / "flow_utils"
    if flow_arch == "RAFT":
        if flow_model not in ("sintel", "kitti"):
            raise ValueError("Unknown RAFT flow model.")
        path, label = root / "models" / f"raft-{flow_model}.pth", f"RAFT {flow_model.title()}"
    elif flow_arch == "EF_RAFT":
        if flow_model not in ("25000_ours-sintel", "ours_sintel", "ours-things"):
            raise ValueError("Unknown EF-RAFT flow model.")
        path, label = root / "ef_raft_models" / f"{flow_model}.pth", f"EF-RAFT {flow_model}"
    elif flow_arch == "FLOW_DIFF":
        if flow_model != "FlowDiffuser-things":
            raise ValueError("FlowDiffuser uses the FlowDiffuser-things model.")
        status = optional_flow_status()['FLOW_DIFF']
        if not status['dependencies'] or not status['backbones']:
            raise ValueError("FlowDiffuser timm dependencies/backbones are incomplete. Run setup_flowdiffuser.py or use Settings > Optional flow components.")
        path, label = root / "flow_diffusion_models" / "FlowDiffuser-things.pth", "FlowDiffuser"
    else:
        raise ValueError("Unknown flow architecture.")
    if not path.is_file():
        raise ValueError(f"{label} weights are missing: {path}")
    if flow_arch != 'RAFT':
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != OPTIONAL_FLOW_HASHES[path.name]:
            raise ValueError(f'{label} weights failed the official checkpoint checksum: {path}')
    return path


def optional_flow_status(root=None, find_spec=importlib.util.find_spec):
    """Return installed optional-model names and missing non-file dependencies."""
    root = Path(root or Path(__file__).parent) / "ezsynth" / "utils" / "flow_utils"
    ef_names = ("25000_ours-sintel", "ours_sintel", "ours-things")
    ef = [name for name in ef_names if (root / "ef_raft_models" / f"{name}.pth").is_file()]
    flow_root = root / "flow_diffusion_models"
    flow_file = flow_root / "FlowDiffuser-things.pth"
    try:
        versions = {name: importlib.metadata.version(name) for name in ('timm', 'huggingface_hub', 'safetensors')}
    except importlib.metadata.PackageNotFoundError:
        versions = {}
    dependencies = (find_spec("timm") is not None and versions ==
                    {'timm': '1.0.29', 'huggingface_hub': '1.31.0', 'safetensors': '0.8.0'})
    backbones = all((flow_root / f'{name}.pth').is_file()
                    for name in ('twins_svt_large', 'twins_svt_small'))
    return {
        "EF_RAFT": {"models": ef, "missing": [name for name in ef_names if name not in ef]},
        "FLOW_DIFF": {"models": ["FlowDiffuser-things"] if flow_file.is_file() else [],
                      "missing": ([] if flow_file.is_file() else ["FlowDiffuser-things"]),
                      "timm": find_spec("timm") is not None,
                      "dependencies": dependencies, "versions": versions,
                      "backbones": backbones},
    }


def install_optional_flow_files(flow_arch, paths, root=None):
    """Copy user-selected official checkpoints into their expected locations."""
    status = optional_flow_status(root)
    if flow_arch not in status:
        raise ValueError("Choose EF-RAFT or FlowDiffuser to install optional model files.")
    selected = [(Path(path).name, Path(path)) for path in paths]
    if len({name.casefold() for name, _ in selected}) != len(selected):
        raise ValueError("Select each checkpoint file only once.")
    allowed = {f"{name}.pth" for name in ("25000_ours-sintel", "ours_sintel", "ours-things")}
    if flow_arch == "FLOW_DIFF":
        allowed = {"FlowDiffuser-things.pth"}
    unexpected = {name for name, _ in selected} - allowed
    if unexpected:
        raise ValueError("Selected file is not a recognized checkpoint: " + ", ".join(sorted(unexpected)))
    if not selected:
        raise ValueError("Select one or more checkpoint files.")
    destination = (Path(root or Path(__file__).parent) / "ezsynth" / "utils" / "flow_utils" /
                   ("ef_raft_models" if flow_arch == "EF_RAFT" else "flow_diffusion_models"))
    destination.mkdir(parents=True, exist_ok=True)
    work = []
    for name, source in selected:
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError(f"Checkpoint is missing or empty: {source}")
        with source.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != OPTIONAL_FLOW_HASHES[name]:
            raise ValueError(f'Checkpoint failed the official checksum: {name}')
        target = destination / name
        if target.exists() and not source.samefile(target):
            raise ValueError(f"Checkpoint is already installed: {target.name}")
        work.append((source, target))
    copied = []
    for source, target in work:
        if target.exists() and source.samefile(target):
            copied.append(target)
            continue
        temporary = target.with_suffix(target.suffix + '.part')
        shutil.copy2(source, temporary)
        temporary.replace(target)
        copied.append(target)
    return copied


def validate_synthesis_dimensions(patch_size, *sizes):
    """Require at least one level under EbsynthRunner.get_max_pyramid_level.

    Sizes are processed (width, height) pairs for style and target images.
    The local wrapper requires each dimension to be at least 2 * patch + 1;
    merely fitting the patch would otherwise pass zero levels to the DLL.
    """
    minimum = 2 * patch_size + 1
    for width, height in sizes:
        if min(width, height) < minimum:
            raise ValueError(
                f'Patch size {patch_size} requires processed style and target images '
                f'to be at least {minimum} x {minimum} pixels for one EbSynth pyramid level. '
                f'Found {width} x {height}. Reduce Patch size in Rendering or increase Processing size.'
            )


def validate_render(data=None):
    if data is None:
        data = {}
    if not isinstance(data, dict) or set(data) - set(RENDER):
        raise ValueError("Unknown or invalid rendering settings.")
    result = dict(RENDER, **data)
    if 'fuoum_raft_model' not in data and data.get('flow_model') in ('sintel', 'kitti'):
        result['fuoum_raft_model'] = data['flow_model']
    for name, default in RENDER.items():
        value = result[name]
        if name in SCHEDULE_FIELDS:
            result[name] = validate_schedule(value)
        elif isinstance(default, bool):
            if type(value) is not bool:
                raise ValueError(f"{name} must be true or false.")
        elif name == 'fuoum_backend':
            if value not in ('cuda', 'torch'):
                raise ValueError('Unknown FuouM synthesis backend.')
        elif name == 'modulation_guide':
            if value not in VIDEO_MODES:
                raise ValueError('Unknown video modulation guide.')
        elif name == 'modulation_dir':
            if not isinstance(value, str):
                raise ValueError('Modulation directory must be text.')
            result[name] = value.strip()
        elif name == "engine":
            validate_engine(value)
        elif name == "edge_method":
            if value not in ("Classic", "PST", "PAGE"):
                raise ValueError("Unknown edge method.")
        elif name == "flow_arch":
            if value not in ("RAFT", "EF_RAFT", "FLOW_DIFF"):
                raise ValueError("Unknown flow architecture.")
        elif name == "flow_model":
            models = {"RAFT": ("sintel", "kitti"),
                      "EF_RAFT": ("25000_ours-sintel", "ours_sintel", "ours-things"),
                      "FLOW_DIFF": ("FlowDiffuser-things",)}
            if value not in models[result["flow_arch"]]:
                raise ValueError("Unknown flow model for the selected architecture.")
        elif name == "ebsynth_backend":
            if value not in ("cuda", "auto", "cpu"):
                raise ValueError("Unknown EbSynth backend.")
        elif name == "fuoum_vote_mode":
            if value not in ("weighted", "plain"):
                raise ValueError("Unknown FuouM vote mode.")
        elif name == 'fuoum_flow_engine':
            if value not in ('RAFT', 'NeuFlow'):
                raise ValueError('Unknown FuouM flow engine.')
        elif name == 'fuoum_raft_model':
            if value not in ('sintel', 'kitti'):
                raise ValueError('Unknown FuouM RAFT checkpoint.')
        elif name == 'fuoum_neuflow_model':
            if value not in ('neuflow_sintel', 'neuflow_mixed', 'neuflow_things'):
                raise ValueError('Unknown NeuFlow checkpoint.')
        elif name == "fuoum_cost_function":
            if value not in ("ssd", "ncc"):
                raise ValueError("Unknown FuouM cost function.")
        else:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number.")
            if isinstance(default, int) and type(value) is not int:
                raise ValueError(f"{name} must be an integer.")
            low, high = LIMITS[name]
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}.")
    if result["patchsize"] % 2 != 1:
        raise ValueError("Patch size must be odd.")
    if result['pyramidlevels'] == 0:
        raise ValueError('Pyramid levels must be Automatic (-1) or a positive number.')
    if result["feather"] and result["feather"] % 2 != 1:
        raise ValueError("Mask feather size must be zero or odd.")
    if result["memory_efficient_raft"] and result["flow_arch"] != "RAFT":
        raise ValueError("Memory-efficient correlation is available only with the RAFT architecture.")
    return result


def validate_weights(data=None):
    if data is None:
        data = {}
    if not isinstance(data, dict) or set(data) - set(WEIGHTS):
        raise ValueError("Unknown or invalid guide weights.")
    result = dict(WEIGHTS, **data)
    for value in result.values():
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10000:
            raise ValueError("Guide weights must be finite numbers between 0 and 10000.")
    if result['key_wgt'] < 0.001:
        raise ValueError('Key weight must be at least 0.001.')
    return result


def validate_application(data):
    if not isinstance(data, dict) or set(data) - set(APPLICATION):
        raise ValueError("Unknown application settings.")
    result = dict(APPLICATION, **data)
    for name, default in APPLICATION.items():
        if type(result[name]) is not type(default):
            raise ValueError(f"Invalid application setting: {name}")
    if not 0 <= result["parallel_limit"] <= 64:
        raise ValueError("Parallel limit must be between 0 (GPU-aware automatic) and 64.")
    if not 1 <= result["preview_limit"] <= 64:
        raise ValueError("Maximum live previews must be between 1 and 64.")
    for name in ("keys_prefix", "video_prefix"):
        prefix = result[name]
        if not prefix.strip() or any(c in prefix for c in '/\\<>:"|?*'):
            raise ValueError("Discovery prefixes must be nonempty folder-name prefixes.")
    if result["keys_prefix"].casefold() == result["video_prefix"].casefold():
        raise ValueError("Keyframe and video prefixes must differ.")
    return result


def validate_group(group, data):
    if group == 'image':
        return validate_image_settings(data)
    if group == "weights":
        return validate_weights(data)
    if group == "application":
        return validate_application(data)
    if not isinstance(data, dict):
        raise ValueError("Preset must contain an object.")
    if group == "directories":
        fields = {"project_dir", "keyframe_dir", "video_dir", "mask_dir", "edge_dir"}
        if set(data) - fields or any(not isinstance(v, str) for v in data.values()):
            raise ValueError("Invalid directory preset.")
        return {name: data.get(name, "") for name in fields}
    if group == "output":
        from reezsynth_project_controls import validate_project_naming
        return validate_project_naming(data)
    if group == "grouped":
        if not isinstance(data, dict) or set(data) != {"selection", "blend_options"}:
            raise ValueError("Invalid Blend / Flow preset.")
        return dict(selection=validate_grouped_selection(data["selection"]),
                    blend_options=validate_blend_options(data["blend_options"]))
    if group == "render":
        from reezsynth_project_controls import validate_project_naming
        if set(data) - {"options", "quality", "max_width", "processing_size", "output_naming", "blend_options", "exports", "video_export", "engine_revision"}:
            raise ValueError("Unknown render preset field.")
        quality = data.get("quality", "Standard")
        processing = validate_processing_settings(data)
        if quality not in QUALITY_PROFILES:
            raise ValueError("Invalid quality or processing size.")
        options = data.get('options', {})
        if not isinstance(options, dict):
            raise ValueError('Invalid rendering settings.')
        options = dict(quality_profile(quality), **options)
        for name in SCHEDULE_FIELDS:
            if isinstance(options.get(name), str):
                options[name] = parse_schedule(options[name])
        revision = validate_revision(options.get('engine', LEGACY), data.get('engine_revision'))
        from reezsynth_video_export import validate_video_export
        return dict(options=validate_render(options), quality=quality,
                    engine_revision=revision,
                    **processing, output_naming=validate_project_naming(data.get("output_naming")),
                    blend_options=validate_blend_options(data.get("blend_options")),
                    exports=validate_exports(data.get("exports")),
                    video_export=validate_video_export(data.get('video_export')))
    raise ValueError("Unknown preset group.")


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


class PresetStore:
    def __init__(self, path):
        self.path = Path(path)
        self.groups = {group: {} for group in GROUPS}
        if self.path.exists():
            self.groups = self.read(self.path)

    @staticmethod
    def read(path):
        data = read_document(path)
        if not isinstance(data, dict) or data.get("version") != 1 or data.get("format") != "ReEzSynth-presets":
            raise ValueError("Unsupported preset file.")
        groups = data.get("groups")
        if not isinstance(groups, dict) or set(groups) - set(GROUPS):
            raise ValueError("Invalid preset groups.")
        result = {group: {} for group in GROUPS}
        for group, presets in groups.items():
            if not isinstance(presets, dict):
                raise ValueError("Invalid preset collection.")
            for name, value in presets.items():
                PresetStore.validate_name(name)
                if name.casefold() in {n.casefold() for n in result[group]}:
                    raise ValueError("Duplicate preset names.")
                result[group][name] = validate_group(group, value)
        return result

    @staticmethod
    def validate_name(name):
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError("Preset names must contain 1 to 80 printable characters.")

    def existing(self, group, name):
        return next((n for n in self.groups[group] if n.casefold() == name.casefold()), None)

    def save(self, group, name, value, overwrite=False):
        name = name.strip()
        self.validate_name(name)
        validated = validate_group(group, value)
        existing = self.existing(group, name)
        if existing and not overwrite:
            raise ValueError("Preset name already exists.")
        updated = copy.deepcopy(self.groups)
        if existing:
            del updated[group][existing]
        updated[group][name] = validated
        self.write(updated)

    def remove(self, group, name):
        updated = copy.deepcopy(self.groups)
        del updated[group][name]
        self.write(updated)

    def write(self, groups, path=None):
        destination = path or self.path
        data = dict(format="ReEzSynth-presets", version=1, groups=groups)
        if Path(destination).suffix.casefold() in {'.yaml', '.yml'}:
            write_document(destination, data)
        else:
            atomic_json(destination, data)
        if path is None:
            self.groups = groups


def discover_pairs(root, keys_prefix="keys", video_prefix="video"):
    """Match sibling directories by suffix, including nested parent directories."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        return []
    import os
    pairs = []
    for parent, names, _ in os.walk(root, followlinks=False):
        names[:] = sorted(n for n in names if n not in {".git", "renders", "__pycache__"}
                          and not (Path(parent) / n).is_symlink())
        keys = [n for n in names if n.casefold().startswith(keys_prefix.casefold())]
        videos = [n for n in names if n.casefold().startswith(video_prefix.casefold())]
        for key in keys:
            suffix = key[len(keys_prefix):].casefold()
            for video in videos:
                if key != video and video[len(video_prefix):].casefold() == suffix:
                    pairs.append((Path(parent) / key, Path(parent) / video))
    return pairs
