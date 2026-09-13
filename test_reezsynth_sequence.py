"""Bounded storage, frame identities, sequence equivalence and cleanup contracts."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from reezsynth_sequence import (ArrayStorage, DiskSequence, array_sequence,
                                frame_storage, number_lookup, number_of, storage_enabled, completion_path)
from test_reezsynth_grouped import upstream_engine
import test_reezsynth_render_adapter as adapter


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='reezsynth sequence ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.job = dict(output=str(self.root), render_options={'stream_frames': True})

    def test_read_cache_is_bounded_and_slices_share_immutable_storage(self):
        store = ArrayStorage(self.root, cache_bytes=300, cache_items=3)
        values = DiskSequence(store, (np.full((8, 8), i, np.uint8) for i in range(100)),
                              numbers=list(range(1000, 1100)))
        self.assertEqual(store.files, 100)
        sliced = values[10:20][::-1]
        combined = sliced + values[30:40]
        self.assertEqual(store.files, 100)
        for i, value in enumerate(values):
            self.assertEqual(number_of(value, {}), 1000 + i)
            self.assertEqual(int(value[0, 0]), i)
            self.assertLessEqual(store.cached_bytes, 300)
            self.assertLessEqual(len(store.cached), 3)
        self.assertEqual([int(v[0, 0]) for v in combined], list(range(19, 9, -1)) + list(range(30, 40)))
        self.assertEqual(number_lookup(values, range(100)), {})
        with self.assertRaises(ValueError):
            values[0][0, 0] = 250
        large = store.read(store.write(np.ones((20, 20), np.float64)))
        self.assertEqual(large.dtype, np.float64)
        self.assertEqual(store.cached_bytes, 0)

    def test_slices_reversal_and_boundary_replacement_match_list_semantics(self):
        with frame_storage(self.job):
            sequence = array_sequence(np.full((2, 2), i) for i in range(6))
            sequence[1:3] = sequence[3:5]
            sequence.pop(0)
            sequence.reverse()
            sequence.extend(sequence[:2])
            self.assertEqual([int(v[0, 0]) for v in sequence], [5, 4, 3, 4, 3, 5, 4])
        self.assertFalse(list(self.root.glob('.frame-storage-*')))
        self.assertFalse(storage_enabled())

    def test_failure_cleans_storage_and_does_not_leak_into_next_job(self):
        with self.assertRaisesRegex(RuntimeError, 'render failed'):
            with frame_storage(self.job):
                array_sequence([np.zeros((2, 2))])
                raise RuntimeError('render failed')
        self.assertFalse(list(self.root.glob('.frame-storage-*')))
        self.assertIsInstance(array_sequence(), list)
        self.assertFalse((self.root / 'COMPLETE.txt').exists())

    def test_completion_is_deferred_until_temporary_storage_cleanup(self):
        original = tempfile.TemporaryDirectory.cleanup
        def cleanup(temporary):
            self.assertFalse((self.root / 'COMPLETE.txt').exists())
            return original(temporary)
        with patch('reezsynth_sequence.tempfile.TemporaryDirectory.cleanup', cleanup):
            with frame_storage(self.job):
                array_sequence([np.zeros((2, 2))])
                completion_path(self.root).write_text('done')
                self.assertFalse((self.root / 'COMPLETE.txt').exists())
        self.assertTrue((self.root / 'COMPLETE.txt').is_file())
        self.assertFalse((self.root / '.COMPLETE.storage-pending').exists())

    def test_legacy_live_sequence_order_and_boundaries_match_in_memory_path(self):
        engine = upstream_engine({})
        frames = [np.full((3, 4, 3), i, np.uint8) for i in range(7)]
        with contextlib.redirect_stdout(io.StringIO()):
            for keys in ([0], [3], [0, 6], [1, 3, 5]):
                for mode in ('none', 'forward', 'reverse'):
                    def run():
                        cfg = types.SimpleNamespace(only_mode=mode, do_mask=False,
                            edg_wgt=1, img_wgt=1, pos_wgt=1, wrp_wgt=1)
                        runner = engine(cfg=cfg, img_frs_seq=array_sequence(frames),
                            style_frs=array_sequence(frames[i] + 100 for i in keys), style_idxes=keys)
                        return runner.run_sequences()[0]
                    expected = run()
                    with frame_storage(self.job):
                        actual = run()
                        self.assertIsInstance(actual, DiskSequence)
                        self.assertEqual(len(actual), len(expected))
                        for a, b in zip(actual, expected):
                            np.testing.assert_array_equal(a, b)

    def test_cleanup_failure_leaves_no_success_marker(self):
        original = tempfile.TemporaryDirectory.cleanup
        def cleanup(temporary):
            original(temporary)
            raise OSError('cleanup failed')
        with patch('reezsynth_sequence.tempfile.TemporaryDirectory.cleanup', cleanup), \
             self.assertRaisesRegex(OSError, 'cleanup failed'):
            with frame_storage(self.job):
                completion_path(self.root).write_text('done')
        self.assertFalse((self.root / 'COMPLETE.txt').exists())
        self.assertTrue((self.root / '.COMPLETE.storage-pending').is_file())
        self.assertFalse(storage_enabled())


class StreamingAdapterTests(unittest.TestCase):
    setUp = adapter.RenderAdapterTests.setUp
    run_job = adapter.RenderAdapterTests.run_job
    fake_engine = adapter.RenderAdapterTests.fake_engine

    def test_actual_adapter_resolves_frame_identities_after_eviction(self):
        captured = self.fake_engine()
        self.job['frames'] = [[i, self.frames[0][1]] for i in range(20)]
        self.job['render_options'] = {'stream_frames': True}
        self.job['exports'] = {'flow_vectors': True}
        self.run_job()
        self.assertIsInstance(captured['runner'].frames, DiskSequence)
        manifest = json.loads((self.output / 'flow_vectors/manifest.json').read_text())
        self.assertEqual([(a['flow_from'], a['flow_to']) for a in manifest['artifacts']],
                         list(zip(range(19), range(1, 20))))
        stats = json.loads((self.output / 'frame_storage.json').read_text())
        self.assertLessEqual(stats['peak_cached_bytes'], stats['cache_limit_bytes'])
        self.assertFalse(list(self.output.glob('.frame-storage-*')))
        self.assertTrue((self.output / 'COMPLETE.txt').is_file())


if __name__ == '__main__':
    unittest.main()
