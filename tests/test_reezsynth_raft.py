"""CPU numerical comparison; no pretrained models, CUDA or rendering."""
from contextlib import nullcontext
import sys
import types
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


class ExtensionReadinessTests(unittest.TestCase):
    def test_custom_architecture_is_accepted_when_kernel_works(self):
        cuda = types.SimpleNamespace(is_available=lambda: True, current_device=lambda: 2,
                                     get_device_capability=lambda *args: (9, 0))
        extension = types.ModuleType('alt_cuda_corr')
        extension.reezsynth_build = '0.2.0'
        with patch.dict(sys.modules, {'torch': types.SimpleNamespace(cuda=cuda), 'alt_cuda_corr': extension}), \
                patch('reezsynth_raft._verify_corr_kernel') as probe:
            self.assertIs(require_alt_cuda_corr(), extension)
        probe.assert_called_once_with(extension, 2)

    def test_supported_architecture_with_unusable_binary_is_rejected(self):
        cuda = types.SimpleNamespace(is_available=lambda: True, current_device=lambda: 0,
                                     get_device_capability=lambda *args: (12, 0))
        extension = types.ModuleType('alt_cuda_corr')
        extension.reezsynth_build = '0.2.0'
        with patch.dict(sys.modules, {'torch': types.SimpleNamespace(cuda=cuda), 'alt_cuda_corr': extension}), \
                patch('reezsynth_raft._verify_corr_kernel', side_effect=RuntimeError('no kernel image')):
            with self.assertRaisesRegex(RuntimeError, '12.0.*no kernel image'):
                require_alt_cuda_corr()

    def test_probe_is_cached_per_module_and_device(self):
        from reezsynth_raft import _verify_corr_kernel
        _verify_corr_kernel.cache_clear()
        self.addCleanup(_verify_corr_kernel.cache_clear)
        calls = []
        extension = types.ModuleType('alt_cuda_corr')
        result = types.SimpleNamespace(numel=lambda: 1, item=lambda: 32.0)
        extension.forward = lambda *args: (calls.append(args) or result,)
        fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(device=lambda *args: nullcontext()),
            no_grad=nullcontext, float32='float32', ones=lambda *args, **kwargs: 'features',
            zeros=lambda *args, **kwargs: 'coords')
        with patch.dict(sys.modules, {'torch': fake_torch}):
            _verify_corr_kernel(extension, 0)
            _verify_corr_kernel(extension, 0)
            _verify_corr_kernel(extension, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], ('features', 'features', 'coords', 0))

    def test_windows_build_environment_merges_path_case_insensitively(self):
        from build_reezsynth_corr import build_environment
        result = build_environment({'PATH': 'old', 'Path': 'duplicate', 'Keep': 'value'},
            'Path=C:\\compiler;C:\\tools\nINCLUDE=a=b\n', '9.0;12.0+PTX', 'C:\\CUDA')
        self.assertEqual(result['PATH'], 'C:\\compiler;C:\\tools')
        self.assertEqual(sum(key.lower() == 'path' for key in result), 1)
        self.assertEqual(result['KEEP'], 'value')
        self.assertEqual(result['INCLUDE'], 'a=b')
        self.assertEqual(result['TORCH_CUDA_ARCH_LIST'], '9.0;12.0+PTX')


if __name__ == '__main__':
    unittest.main()
