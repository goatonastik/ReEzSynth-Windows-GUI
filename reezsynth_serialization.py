"""Safe JSON/YAML document I/O for shareable projects and preset libraries."""
import json
from pathlib import Path


YAML_SUFFIXES = {'.yaml', '.yml'}


def _yaml():
    try:
        import yaml
    except ImportError as exc:
        raise ValueError('YAML support requires PyYAML. Run the ReEzSynth setup or install PyYAML==6.0.2.') from exc
    return yaml


def read_document(path):
    path = Path(path)
    text = path.read_text(encoding='utf-8-sig')
    data = _yaml().safe_load(text) if path.suffix.casefold() in YAML_SUFFIXES else json.loads(text)
    if not isinstance(data, dict):
        raise ValueError('Configuration document must contain an object.')
    return data


def write_document(path, data):
    path = Path(path)
    if path.suffix.casefold() in YAML_SUFFIXES:
        text = _yaml().safe_dump(data, allow_unicode=True, sort_keys=False)
    else:
        text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8', newline='\n')
    temporary.replace(path)
