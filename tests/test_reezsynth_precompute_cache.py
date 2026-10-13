import gc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from reezsynth_precompute_cache import (array_digest, cache_entry,
    edge_identity, flow_identity, load_array, store_array, publish_once)


class PrecomputeCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='reezsynth cache ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = {'precompute_cache': str(self.root / '.reezsynth-cache')}
        self.frames = [np.full((8, 9, 3), value, np.uint8) for value in (10, 20)]

    def test_keys_include_content_engine_revision_and_method(self):
        identity = edge_identity('engine-a', 'revision-a', 'Classic')
        first = cache_entry(self.job, 'edges', self.frames[:1], identity)
        self.assertEqual(first, cache_entry(self.job, 'edges', self.frames[:1], identity))
        changed = self.frames[0].copy()
        changed[0, 0, 0] += 1
        self.assertNotEqual(first, cache_entry(self.job, 'edges', [changed], identity))
        self.assertNotEqual(first, cache_entry(
            self.job, 'edges', self.frames[:1], edge_identity('engine-b', 'revision-a', 'Classic')))
        self.assertNotEqual(first, cache_entry(
            self.job, 'edges', self.frames[:1], edge_identity('engine-a', 'revision-a', 'PAGE')))

    def test_atomic_arrays_validate_shape_type_and_finite_values(self):
        directory = cache_entry(self.job, 'flow', self.frames, {'checkpoint': 'hash'})
        path = directory / 'flow.npy'
        value = np.ones((8, 9, 2), np.float32)
        store_array(path, value)
        loaded = load_array(path, value.shape, mmap=True)
        self.assertIsInstance(loaded, np.memmap)
        np.testing.assert_array_equal(loaded, value)
        self.assertIsNone(load_array(path, (9, 8, 2)))
        loaded._mmap.close()
        del loaded
        gc.collect()
        next(path.parent.glob(path.name + '.*.sha256')).unlink()
        self.assertIsNone(load_array(path, value.shape))
        store_array(path, value)
        path.write_bytes(b'not an npy')
        self.assertIsNone(load_array(path, value.shape))
        with self.assertRaisesRegex(ValueError, 'finite'):
            store_array(path, np.full(value.shape, np.nan, np.float32))

    def test_checkpoint_hash_changes_flow_identity(self):
        checkpoint = self.root / 'model.pth'
        checkpoint.write_bytes(b'first')
        runtime = {'engine': 'Trentonom0r3/Ezsynth', 'revision': 'rev', 'source': str(self.root)}
        with patch('reezsynth_precompute_cache.legacy_checkpoint', return_value=checkpoint):
            first = flow_identity({'flow_arch': 'RAFT', 'flow_model': 'sintel'}, runtime)
            efficient = flow_identity({'flow_arch': 'RAFT', 'flow_model': 'sintel',
                                       'memory_efficient_raft': True}, runtime)
            checkpoint.write_bytes(b'second')
            second = flow_identity({'flow_arch': 'RAFT', 'flow_model': 'sintel'}, runtime)
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, efficient)
        self.assertEqual(len(first['checkpoints'][0][1]), 64)

    def test_identical_parallel_publishers_leave_one_valid_artifact(self):
        value = np.arange(8 * 9 * 2, dtype=np.float32).reshape(8, 9, 2)
        def publish(_):
            directory = cache_entry(self.job, 'flow', self.frames, {'checkpoint': 'same'})
            store_array(directory / 'flow.npy', value)
            return directory
        with ThreadPoolExecutor(max_workers=4) as pool:
            directories = list(pool.map(publish, range(12)))
        self.assertEqual(len(set(directories)), 1)
        np.testing.assert_array_equal(load_array(directories[0] / 'flow.npy', value.shape), value)
        self.assertEqual(list(directories[0].glob('*.part-*')), [])

    def test_relative_cache_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'absolute'):
            cache_entry({'precompute_cache': 'relative'}, 'edges', self.frames, {})

    def test_array_is_valid_as_soon_as_atomic_publication_is_visible(self):
        path = self.root / 'flow.npy'
        value = np.ones((8, 9, 2), np.float32)
        original = publish_once
        observed = []
        def publish(temporary, destination):
            result = original(temporary, destination)
            observed.append(load_array(destination, value.shape))
            return result
        with patch('reezsynth_precompute_cache.publish_once', publish):
            store_array(path, value)
        self.assertEqual(len(observed), 1)
        np.testing.assert_array_equal(observed[0], value)


if __name__ == '__main__':
    unittest.main()
