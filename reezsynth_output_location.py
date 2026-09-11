"""Output destinations and exclusive directory creation."""
from pathlib import Path

LOCATIONS = (
    ('project_renders', 'Project / renders (current default)'),
    ('keys_child', 'New outputs folder inside keyframes folder'),
    ('video_child', 'New outputs folder inside video folder'),
    ('keys_parent', 'Parent of keyframes folder'),
    ('video_parent', 'Parent of video folder'),
    ('project', 'Project folder'),
    ('custom', 'Custom folder'),
)
DEFAULTS = dict(batch_enabled=True, location='project_renders', custom_folder='')


def validate_location(data):
    result = {name: data.get(name, default) for name, default in DEFAULTS.items()}
    if type(result['batch_enabled']) is not bool or result['location'] not in dict(LOCATIONS):
        raise ValueError('Invalid output location settings.')
    if not isinstance(result['custom_folder'], str):
        raise ValueError('Custom output folder must be text.')
    return result


def output_root(settings, project, keys, video):
    settings = validate_location(settings)
    location = settings['location']
    text = settings['custom_folder'] if location == 'custom' else (
        keys if location.startswith('keys_') else video if location.startswith('video_') else project)
    if not str(text).strip():
        raise ValueError('The selected output location requires a folder.')
    root = Path(str(text).strip().strip('"')).expanduser().resolve()
    if location.endswith('_child'):
        root /= 'outputs'
    elif location.endswith('_parent'):
        root = root.parent
    elif location == 'project_renders':
        root /= 'renders'
    return root


def create_unique_directory(root, name):
    root = Path(root).resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError('Output directory escapes the selected root.')
    target.parent.mkdir(parents=True, exist_ok=True)
    for index in range(1, 10001):
        candidate = target if index == 1 else target.with_name(f'{target.name}_{index:03d}')
        try:
            candidate.mkdir(exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise ValueError('Too many output folders use this name.')
