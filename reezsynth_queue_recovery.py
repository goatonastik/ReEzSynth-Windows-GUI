"""Atomic queue journals and conservative restart auditing; no Qt imports."""
import hashlib
import json
from pathlib import Path

from reezsynth_config import atomic_json


JOURNAL_NAME = '.reezsynth-queue.json'
VERSION = 1
STATES = {'pending', 'running', 'complete', 'failed', 'interrupted'}


def file_sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _paths(job, job_path):
    values = []
    image = job.get('image_synthesis', {})
    for name in ('style', 'source', 'target', 'modulation'):
        if image.get(name):
            values.append(image[name])
    for guide in image.get('guides', []):
        values.extend([guide.get('source'), guide.get('target')])
        if guide.get('modulation'):
            values.append(guide['modulation'])
    for name in ('style',):
        if job.get(name):
            values.append(job[name])
    for name in ('frames', 'styles', 'masks', 'edge_guides'):
        values.extend(entry[1] for entry in job.get(name, []) if isinstance(entry, list) and len(entry) == 2)
    if job.get('render_options', {}).get('modulation_guide', 'Off') != 'Off':
        values.extend(entry[1] for entry in job.get('modulation_frames', []))
    audio = job.get('video_export', {}).get('audio')
    if audio:
        values.append(audio)
    result = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        path = Path(value).expanduser()
        path = path.resolve() if path.is_absolute() else (Path(job_path).parent / path).resolve()
        if path not in result:
            result.append(path)
    return result


def snapshot_inputs(job, job_path):
    result = []
    for path in _paths(job, job_path):
        try:
            stat = path.stat()
            result.append({'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns})
        except OSError:
            result.append({'path': str(path), 'missing': True})
    return result


def input_changes(snapshot):
    changes = []
    for expected in snapshot:
        path = Path(expected['path'])
        if expected.get('missing'):
            changes.append(str(path))
            continue
        try:
            stat = path.stat()
            actual = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
            if any(actual[name] != expected.get(name) for name in actual):
                changes.append(str(path))
        except OSError:
            changes.append(str(path))
    return changes


def create_journal(batch, records, mode, worker_script, parallel_limit=0, *, name=JOURNAL_NAME):
    batch = Path(batch).resolve()
    if Path(name).name != name:
        raise ValueError('Queue recovery journal name must be a filename.')
    entries = []
    for record in records:
        job_path = Path(record['job_path']).resolve()
        output = Path(record['output']).resolve()
        if not job_path.is_relative_to(batch) or not output.is_relative_to(batch):
            raise ValueError('Queue recovery journal paths must stay inside the batch directory.')
        job = json.loads(job_path.read_text(encoding='utf-8'))
        job_output = Path(job.get('output', ''))
        if not job_output.is_absolute() or job_output.resolve() != output:
            raise ValueError('Queue job output does not match its recovery record.')
        entries.append(dict(job=str(job_path.relative_to(batch)), output=str(output.relative_to(batch)),
                            key=record.get('key'), label=record['row'].get('label', ''),
                            weight=record['weight'], python=record.get('python', ''), state='pending',
                            job_sha256=file_sha256(job_path), inputs=snapshot_inputs(job, job_path)))
    path = batch / name
    atomic_json(path, dict(version=VERSION, state='active', mode=mode,
                           worker_script=Path(worker_script).name,
                           parallel_limit=parallel_limit, entries=entries))
    return path


def update_journal(path, job_path=None, state=None, *, overall=None):
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != VERSION:
        raise ValueError('Unsupported queue recovery journal.')
    if state is not None:
        if state not in STATES or job_path is None:
            raise ValueError('Invalid queue recovery state update.')
        relative = str(Path(job_path).resolve().relative_to(path.parent.resolve()))
        match = next((entry for entry in data['entries'] if entry['job'] == relative), None)
        if match is None:
            raise ValueError('Queue job is absent from its recovery journal.')
        match['state'] = state
    if overall is not None:
        if overall not in {'active', 'complete', 'failed', 'interrupted'}:
            raise ValueError('Invalid queue recovery overall state.')
        data['state'] = overall
    atomic_json(path, data)


def audit_journal(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != VERSION or not isinstance(data.get('entries'), list):
        raise ValueError('Unsupported or invalid queue recovery journal.')
    if data.get('mode') not in {'shared', 'isolated', 'parallel'}:
        raise ValueError('Queue recovery journal has an invalid worker mode.')
    batch = path.parent
    audited = []
    for entry in data['entries']:
        if not isinstance(entry, dict) or entry.get('state') not in STATES:
            raise ValueError('Queue recovery journal contains an invalid job entry.')
        if not isinstance(entry.get('job'), str) or not isinstance(entry.get('output'), str):
            raise ValueError('Queue recovery journal contains invalid paths.')
        job_path = (batch / entry['job']).resolve()
        output = (batch / entry['output']).resolve()
        if not job_path.is_relative_to(batch) or not output.is_relative_to(batch):
            raise ValueError('Queue recovery journal path escapes its batch directory.')
        changed = []
        job = None
        if not job_path.is_file():
            changed.append(str(job_path))
        else:
            if file_sha256(job_path) != entry.get('job_sha256'):
                changed.append(str(job_path))
            try:
                job = json.loads(job_path.read_text(encoding='utf-8'))
            except (OSError, ValueError, TypeError):
                changed.append(str(job_path))
            if job is not None:
                job_output = Path(job.get('output', ''))
                if not job_output.is_absolute() or job_output.resolve() != output:
                    changed.append(str(job_path))
        changed.extend(input_changes(entry.get('inputs', [])))
        complete = (output / 'COMPLETE.txt').is_file()
        partial = False
        if output.is_dir() and not complete:
            partial = any(item.name != job_path.name and item.name != '.reezsynth-preview'
                          for item in output.iterdir())
        audited.append(dict(entry=entry, job=job, job_path=job_path, output=output,
                            changed=sorted(set(changed)), complete=complete, partial=partial,
                            recoverable=not complete and not changed))
    return dict(path=path, batch=batch, data=data, entries=audited)
