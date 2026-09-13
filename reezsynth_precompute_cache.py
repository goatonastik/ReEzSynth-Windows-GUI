"""Validated, content-addressed flow/edge caches; no Qt or engine imports."""
import hashlib
import json
import os
from pathlib import Path
import uuid

import numpy as np

from reezsynth_engines import (FUOUM, file_sha256, fuoum_checkpoint,
                               legacy_checkpoint)


CACHE_VERSION = 2


def publish_once(temporary, destination):
    """Atomically publish without replacing an existing reader's file."""
    if os.name == 'nt':
        # Windows rename refuses existing destinations, including on exFAT.
        os.rename(temporary, destination)
    else:
        os.link(temporary, destination)


def array_digest(value):
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(f'ReEzSynth array v{CACHE_VERSION}\0'.encode())
    digest.update(str(array.dtype).encode() + b'\0')
    digest.update(json.dumps(array.shape).encode() + b'\0')
    digest.update(memoryview(array).cast('B'))
    return digest.hexdigest()


def flow_identity(options, runtime):
    engine = runtime['engine']
    source = Path(runtime['source']).resolve()
    checkpoint = (fuoum_checkpoint(options, source) if engine == FUOUM
                  else legacy_checkpoint(options, source))
    checkpoints = [checkpoint]
    if engine != FUOUM and options.get('flow_arch') == 'FLOW_DIFF':
        checkpoints += [checkpoint.parent / 'twins_svt_large.pth',
                        checkpoint.parent / 'twins_svt_small.pth']
    hashes = []
    for path in checkpoints:
        if not path.is_file():
            raise ValueError(f'Optical-flow cache checkpoint is missing: {path}')
        hashes.append([str(path.resolve()), file_sha256(path)])
    return dict(engine=engine, revision=runtime['revision'], checkpoints=hashes,
                architecture=(options.get('fuoum_flow_engine') if engine == FUOUM
                              else options.get('flow_arch')),
                memory_efficient_raft=(False if engine == FUOUM else
                                       bool(options.get('memory_efficient_raft'))),
                model=(options.get('fuoum_neuflow_model') if engine == FUOUM and
                       options.get('fuoum_flow_engine') == 'NeuFlow' else
                       options.get('fuoum_raft_model') if engine == FUOUM else
                       options.get('flow_model')))


def cache_entry(job, kind, frames, identity):
    return cache_entry_from_digests(job, kind, [array_digest(value) for value in frames], identity)


def cache_entry_from_digests(job, kind, frame_digests, identity):
    root = job.get('precompute_cache')
    if not root:
        return None
    root = Path(root).expanduser()
    if not root.is_absolute():
        raise ValueError('Precomputation cache path must be absolute.')
    payload = dict(version=CACHE_VERSION, kind=kind, frames=list(frame_digests),
                   identity=identity)
    key = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()
    path = root.resolve() / f'v{CACHE_VERSION}' / kind / key
    path.mkdir(parents=True, exist_ok=True)
    manifest = path / 'identity.json'
    if not manifest.exists():
        temporary = manifest.with_name(manifest.name + f'.part-{os.getpid()}-{uuid.uuid4().hex}')
        try:
            temporary.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
            # Both names are on the same filesystem. Readers never observe an
            # incomplete document and competing producers never replace it.
            try:
                publish_once(temporary, manifest)
            except FileExistsError:
                pass
            except PermissionError:
                if not manifest.is_file():
                    raise
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    if json.loads(manifest.read_text(encoding='utf-8')) != payload:
        raise RuntimeError('Precomputation cache identity collision.')
    return path


def load_array(path, shape, *, mmap=False, kinds=('f',)):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        digest = file_sha256(path)
        marker = path.with_name(path.name + f'.{digest}.sha256')
        if not marker.is_file():
            return None
        value = np.load(path, allow_pickle=False, mmap_mode='r' if mmap else None)
        if (value.shape != tuple(shape) or value.dtype.kind not in kinds or
                not np.isfinite(value).all()):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def store_array(path, value):
    path = Path(path)
    array = np.asarray(value)
    if array.dtype.kind not in ('f', 'u', 'i') or not np.isfinite(array).all():
        raise ValueError('Only finite numerical precomputation arrays can be cached.')
    temporary = path.with_name(path.name + f'.part-{os.getpid()}-{uuid.uuid4().hex}')
    try:
        with temporary.open('wb') as stream:
            np.save(stream, array, allow_pickle=False)
        digest = file_sha256(temporary)
        # Publish validation before the atomic rename: a simultaneous reader can
        # otherwise see the new array before its marker, treat it as invalid and
        # attempt to replace a file another Windows worker already has open.
        path.with_name(path.name + f'.{digest}.sha256').touch(exist_ok=True)
        existing = load_array(path, array.shape, kinds=(array.dtype.kind,))
        if existing is None:
            try:
                publish_once(temporary, path)
            except FileExistsError:
                # An existing valid winner is immutable. Only a corrupt or
                # incomplete artifact needs replacement.
                if load_array(path, array.shape, kinds=(array.dtype.kind,)) is None:
                    try:
                        temporary.replace(path)
                    except PermissionError:
                        if load_array(path, array.shape, kinds=(array.dtype.kind,)) is None:
                            raise
            except PermissionError:
                # An identical parallel producer may have published and mapped it.
                if load_array(path, array.shape, kinds=(array.dtype.kind,)) is None:
                    raise
    finally:
        for candidate in (temporary,):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass


def edge_identity(engine, revision, method):
    return dict(engine=engine, revision=revision, method=method)
