"""Opt-in GPU validation/benchmark of correlation; no footage or model weights."""
import argparse
import gc
import json
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', action='store_true', help='Compare correlation lookup timings at 960-width equivalent.')
    parser.add_argument('--four-k', action='store_true', help='Measure compiled correlation only at 3840x2160-equivalent feature size.')
    args = parser.parse_args()
    import torch
    from argparse import Namespace
    from ezsynth.utils.flow_utils.core.corr import CorrBlock
    from ezsynth.utils.flow_utils.core.raft import RAFT
    from reezsynth_raft import CompiledCorrBlock, MemoryEfficientCorrBlock, correlation_mode, require_alt_cuda_corr
    extension = require_alt_cuda_corr()
    print(f'Extension: {extension.__file__}', flush=True)
    print(f'GPU: {torch.cuda.get_device_name(0)}; PyTorch {torch.__version__}', flush=True)
    torch.manual_seed(31)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    def coordinates(batch, height, width):
        y, x = torch.meshgrid(torch.arange(height, device='cuda'), torch.arange(width, device='cuda'), indexing='ij')
        return torch.stack((x, y)).float()[None].repeat(batch, 1, 1, 1) + torch.randn(batch, 2, height, width, device='cuda') * 3.1
    with torch.no_grad():
        # Odd source dimensions exercise partial CUDA thread blocks. A custom
        # stream catches extensions that incorrectly launch on the default stream.
        stream = torch.cuda.Stream()
        with torch.cuda.stream(stream):
            for channels, height, width in ((128, 16, 24), (256, 17, 25)):
                a = torch.randn(2, channels, height, width, device='cuda')
                b = torch.randn(2, channels, height, width, device='cuda')
                xy = coordinates(2, height, width)
                expected = CorrBlock(a, b)(xy)
                actual = CompiledCorrBlock(a, b)(xy)
                torch.testing.assert_close(actual, expected, atol=3e-5, rtol=3e-5)
            # Validate errors rather than letting invalid dtypes/channels corrupt memory.
            for wrong in (a.permute(0, 2, 3, 1).contiguous().half(),
                          a[:, :33].permute(0, 2, 3, 1).contiguous()):
                try:
                    extension.forward(wrong, wrong, xy.permute(0, 2, 3, 1).unsqueeze(1).contiguous(), 4)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Invalid native inputs were accepted')
        stream.synchronize()
        print('[OK] Native correlations agree with all-pairs; borders, subpixels, batch, channels and custom CUDA stream checked.', flush=True)
        del a, b, xy, expected, actual, wrong
        model = RAFT(Namespace(small=False, mixed_precision=False)).cuda().eval()
        a = torch.rand(1, 3, 128, 128, device='cuda') * 255
        b = torch.rand_like(a) * 255
        expected = model(a, b, iters=3, test_mode=True)[1]
        with correlation_mode(True):
            actual = model(a, b, iters=3, test_mode=True)[1]
        torch.testing.assert_close(actual, expected, atol=2e-4, rtol=2e-4)
        print('[OK] Standard-size RAFT architecture, random weights, three iterations: flow agrees within tolerance.', flush=True)
        del model, a, b, expected, actual
        gc.collect()
        torch.cuda.empty_cache()

        def measure(label, factory, h, w, repeat):
            a = torch.randn(1, 256, h, w, device='cuda')
            b = torch.randn_like(a)
            xy = coordinates(1, h, w)
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
            before = time.perf_counter()
            block = factory(a, b)
            torch.cuda.synchronize()
            setup = time.perf_counter() - before
            output = block(xy)
            torch.cuda.synchronize()
            before = time.perf_counter()
            for _ in range(repeat):
                output = block(xy)
            torch.cuda.synchronize()
            elapsed = (time.perf_counter() - before) / repeat
            if not torch.isfinite(output).all():
                raise AssertionError('Non-finite benchmark result')
            print(json.dumps(dict(mode=label, feature_size=[w, h], setup_seconds=round(setup, 4),
                lookup_seconds=round(elapsed, 4), peak_allocated_MiB=round(torch.cuda.max_memory_allocated() / 2**20, 1))), flush=True)

        if args.benchmark:
            for label, factory in (('all-pairs', CorrBlock), ('pytorch-reference', MemoryEfficientCorrBlock), ('alt_cuda_corr', CompiledCorrBlock)):
                measure(label, factory, 68, 120, 2)
                gc.collect()
                torch.cuda.empty_cache()
        if args.four_k:
            if args.benchmark:
                measure('pytorch-reference-4K', MemoryEfficientCorrBlock, 270, 480, 2)
                gc.collect()
                torch.cuda.empty_cache()
            measure('alt_cuda_corr-4K', CompiledCorrBlock, 270, 480, 2)
    print('No pretrained models loaded and no synthesis performed.', flush=True)


if __name__ == '__main__':
    main()
