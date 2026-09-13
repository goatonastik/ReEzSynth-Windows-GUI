"""Job-scoped disk-backed array sequences with a bounded decoded read cache."""
from collections import OrderedDict
from collections.abc import MutableSequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import tempfile

import numpy as np


_storage = ContextVar('reezsynth_frame_storage', default=None)


class NumberedArray(np.ndarray):
    def __array_finalize__(self, source):
        self.frame_number = getattr(source, 'frame_number', None)


def copy_number(value, source):
    number = getattr(source, 'frame_number', None)
    if number is not None:
        value = np.asarray(value).view(NumberedArray)
        value.frame_number = number
    return value


def number_of(value, fallback):
    number = getattr(value, 'frame_number', None)
    return number if number is not None else fallback.get(id(value))


def number_lookup(sequence, numbers):
    return {} if isinstance(sequence, DiskSequence) else {
        id(value): number for value, number in zip(sequence, numbers)}


class ArrayStorage:
    def __init__(self, root, cache_bytes=64 * 1024 ** 2, cache_items=8):
        self.root = Path(root)
        self.cache_bytes, self.cache_items = cache_bytes, cache_items
        self.cached = OrderedDict()
        self.cached_bytes = self.peak_cached_bytes = self.written_bytes = 0
        self.files = 0

    def write(self, value, number=None):
        if value is None:
            return None
        array = np.asarray(value)
        if array.dtype.kind not in 'buif' or not array.size:
            raise ValueError('Frame storage accepts nonempty numerical arrays only.')
        number = getattr(value, 'frame_number', None) if number is None else number
        path = self.root / f'{self.files:09d}.npy'
        self.files += 1
        with path.open('xb') as stream:
            np.save(stream, array, allow_pickle=False)
        self.written_bytes += path.stat().st_size
        return path, number

    def read(self, reference):
        if reference is None:
            return None
        path, number = reference
        if path in self.cached:
            value = self.cached.pop(path)
        else:
            # Ordinary arrays let eviction release memory and close every file
            # immediately. Long-lived memory maps can pin files on Windows.
            value = np.load(path, allow_pickle=False).view(NumberedArray)
            value.frame_number = number
            value.flags.writeable = False
            while self.cached and (self.cached_bytes + value.nbytes > self.cache_bytes or
                                   len(self.cached) >= self.cache_items):
                _, previous = self.cached.popitem(last=False)
                self.cached_bytes -= previous.nbytes
            if value.nbytes > self.cache_bytes:
                return value
            self.cached_bytes += value.nbytes
        self.cached[path] = value
        self.peak_cached_bytes = max(self.peak_cached_bytes, self.cached_bytes)
        return value


class DiskSequence(MutableSequence):
    def __init__(self, storage, values=(), *, numbers=None):
        self.storage, self.references, self.numbers = storage, [], numbers
        self.extend(values)

    def __len__(self):
        return len(self.references)

    def __getitem__(self, index):
        if isinstance(index, slice):
            result = DiskSequence(self.storage)
            result.references = self.references[index]
            return result
        return self.storage.read(self.references[index])

    def __setitem__(self, index, value):
        if isinstance(index, slice):
            refs = (value.references if isinstance(value, DiskSequence) and value.storage is self.storage
                    else [self.storage.write(item) for item in value])
            self.references[index] = refs
        else:
            self.references[index] = self.storage.write(value)

    def __delitem__(self, index):
        del self.references[index]

    def insert(self, index, value):
        number = self.numbers[index] if self.numbers is not None else None
        self.references.insert(index, self.storage.write(value, number))

    def extend(self, values):
        if isinstance(values, DiskSequence) and values.storage is self.storage:
            self.references.extend(values.references)
        else:
            for value in values:
                self.append(value)

    def reverse(self):
        self.references.reverse()

    def __add__(self, values):
        result = self[:]
        result.extend(values)
        return result


def array_sequence(values=(), *, numbers=None):
    storage = _storage.get()
    return list(values) if storage is None else DiskSequence(storage, values, numbers=numbers)


def storage_enabled():
    return _storage.get() is not None


def completion_path(output):
    return Path(output) / ('.COMPLETE.storage-pending' if storage_enabled() else 'COMPLETE.txt')


@contextmanager
def frame_storage(job):
    enabled = job.get('render_options', {}).get('stream_frames', False)
    if type(enabled) is not bool:
        raise ValueError('stream_frames must be true or false.')
    if not enabled or job.get('type') == 'image_synthesis':
        yield
        return
    output = Path(job['output']).resolve()
    pending = None
    with tempfile.TemporaryDirectory(prefix='.frame-storage-', dir=output) as directory:
        storage = ArrayStorage(directory)
        token = _storage.set(storage)
        try:
            print('[Memory] Disk-backed frame storage enabled; decoded cache limited to 64 MiB / 8 arrays.', flush=True)
            yield
            candidate = output / '.COMPLETE.storage-pending'
            if candidate.is_file():
                pending = candidate
        finally:
            from reezsynth_config import atomic_json
            _storage.reset(token)
            storage.cached.clear()
            storage.cached_bytes = 0
            atomic_json(output / 'frame_storage.json', dict(version=1,
                cache_limit_bytes=storage.cache_bytes, cache_limit_arrays=storage.cache_items,
                peak_cached_bytes=storage.peak_cached_bytes, arrays_written=storage.files,
                disk_bytes_written=storage.written_bytes,
                scope='Decoded array cache only; active synthesis tensors and OS file cache are additional.'))
    if pending is not None:
        pending.replace(output / 'COMPLETE.txt')
