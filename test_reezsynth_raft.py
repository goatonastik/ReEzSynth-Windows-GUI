"""CPU numerical comparison; no pretrained models, CUDA or rendering."""
import unittest
from unittest.mock import patch
from reezsynth_raft import CompiledCorrBlock, MemoryEfficientCorrBlock, correlation_mode, require_alt_cuda_corr
from reezsynth_errors import is_cuda_out_of_memory


class CorrelationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Do not import the engine while unittest collects GUI smoke tests.
        global torch, CorrBlock, raft
        import torch
        from ezsynth.utils.flow_utils.core.corr import CorrBlock
        from ezsynth.utils.flow_utils.core import raft

    def test_matches_all_pairs_at_subpixel_and_outside_coordinates(self):
        generator = torch.Generator().manual_seed(37)
        with torch.no_grad():
            a = torch.randn(2, 12, 16, 24, generator=generator)
            b = torch.randn(2, 12, 16, 24, generator=generator)
            xy = torch.randn(2, 2, 16, 24, generator=generator) * 12 + 5.3
            expected = CorrBlock(a, b, num_levels=4, radius=4)(xy)
            for chunk in (17, 256):
                block = MemoryEfficientCorrBlock(a, b, num_levels=4, radius=4, chunk_size=chunk)
                actual = block(xy)
                torch.testing.assert_close(actual, expected, rtol=2e-5, atol=2e-5)
                self.assertLess(sum(t.numel() for t in block.pyramid) + block.source.numel(),
                                (16 * 24) ** 2 * 2)

    def test_scope_restores_after_failure_and_disabled_job(self):
        original = raft.CorrBlock
        with self.assertRaisesRegex(RuntimeError, 'test failure'):
            with correlation_mode(True):
                self.assertIs(raft.CorrBlock, CompiledCorrBlock)
                raise RuntimeError('test failure')
        self.assertIs(raft.CorrBlock, original)
        with correlation_mode(False):
            self.assertIs(raft.CorrBlock, original)

    def test_raft_forward_uses_new_block(self):
        from argparse import Namespace
        with torch.random.fork_rng(), torch.no_grad():
            torch.manual_seed(7)
            model = raft.RAFT(Namespace(small=True, mixed_precision=False)).eval()
            a = torch.rand(1, 3, 128, 128) * 255
            b = torch.rand_like(a) * 255
            expected = model(a, b, iters=2, test_mode=True)[1]
            with patch.object(raft, 'CorrBlock', MemoryEfficientCorrBlock):
                actual = model(a, b, iters=2, test_mode=True)[1]
            torch.testing.assert_close(actual, expected, rtol=1e-4, atol=1e-4)

    def test_cuda_error_requires_explicit_exception(self):
        for line in ('torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 62.57 GiB.',
                     'RuntimeError: CUDA error: out of memory',
                     'torch.cuda.OutOfMemoryError: CUDA out of memory.'):
            self.assertTrue(is_cuda_out_of_memory(line))
        for line in ('MemoryError: out of memory', 'worker crashed',
                     'Try this if CUDA out of memory occurs', 'Cupy is not installed',
                     'torch.OutOfMemoryError: CPU allocator failure'):
            self.assertFalse(is_cuda_out_of_memory(line))

    def test_missing_extension_fails_without_slow_fallback(self):
        import sys
        with patch.dict(sys.modules, {'alt_cuda_corr': None}), self.assertRaisesRegex(RuntimeError, 'No slow fallback'):
            require_alt_cuda_corr()


if __name__ == '__main__':
    unittest.main()
