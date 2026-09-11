"""Versioned frontend settings; no rendering-engine imports."""
import copy
import json
import math
from pathlib import Path
from reezsynth_video_plan import validate_blend_options
from reezsynth_artifacts import validate_exports
from reezsynth_image import validate_image_settings

WEIGHTS = {"edg_wgt": 1.0, "img_wgt": 6.0, "pos_wgt": 2.0, "wrp_wgt": 0.5,
           "key_wgt": 1.0, "mask_wgt": 0.0}
PREVIEW = dict(uniformity=3500.0, patchsize=5, pyramidlevels=3,
               searchvoteiters=4, patchmatchiters=3, extrapass3x3=False)
STANDARD = dict(uniformity=3500.0, patchsize=7, pyramidlevels=6,
                searchvoteiters=12, patchmatchiters=6, extrapass3x3=True)
RENDER = dict(STANDARD, edge_method="Classic", do_mask=False, pre_mask=False, feather=0,
              memory_efficient_raft=False)
APPLICATION = dict(discover=False, keys_prefix="keys", video_prefix="video",
    auto_start=False, wait_for_mask=False, parallel=False, parallel_limit=2,
    sound_enabled=True, sound_each=False, sound_queue=True, sound_file="",
    reuse_queue_worker=True)
GROUPS = ("directories", "weights", "render", "application", "image")
LIMITS = {"uniformity": (0, 100000), "patchsize": (3, 99), "pyramidlevels": (1, 20),
    "searchvoteiters": (1, 1000), "patchmatchiters": (1, 1000), "feather": (0, 999)}


def validate_render(data=None):
    if data is None:
        data = {}
    if not isinstance(data, dict) or set(data) - set(RENDER):
        raise ValueError("Unknown or invalid rendering settings.")
    result = dict(RENDER, **data)
    for name, default in RENDER.items():
        value = result[name]
        if isinstance(default, bool):
            if type(value) is not bool:
                raise ValueError(f"{name} must be true or false.")
        elif name == "edge_method":
            if value not in ("Classic", "PST", "PAGE"):
                raise ValueError("Unknown edge method.")
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
    if result["feather"] and result["feather"] % 2 != 1:
        raise ValueError("Mask feather size must be zero or odd.")
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
        raise ValueError("Parallel limit must be between 0 (unlimited) and 64.")
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
        fields = {"project_dir", "keyframe_dir", "video_dir", "mask_dir"}
        if set(data) - fields or any(not isinstance(v, str) for v in data.values()):
            raise ValueError("Invalid directory preset.")
        return {name: data.get(name, "") for name in fields}
    if group == "render":
        from reezsynth_project_controls import validate_project_naming
        if set(data) - {"options", "quality", "max_width", "output_naming", "blend_options", "exports"}:
            raise ValueError("Unknown render preset field.")
        quality, width = data.get("quality", "Standard"), data.get("max_width", 0)
        if quality not in ("Preview", "Standard") or type(width) is not int or width not in (0, 512, 960):
            raise ValueError("Invalid quality or processing size.")
        options = data.get('options', {})
        if not isinstance(options, dict):
            raise ValueError('Invalid rendering settings.')
        options = dict(STANDARD if quality == 'Standard' else PREVIEW, **options)
        return dict(options=validate_render(options), quality=quality,
                    max_width=width, output_naming=validate_project_naming(data.get("output_naming")),
                    blend_options=validate_blend_options(data.get("blend_options")),
                    exports=validate_exports(data.get("exports")))
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
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
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
        atomic_json(path or self.path, dict(format="ReEzSynth-presets", version=1, groups=groups))
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
