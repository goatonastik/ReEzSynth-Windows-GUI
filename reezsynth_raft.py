"""Inference-only RAFT correlation adapters.

Dot products commute with average pooling and bilinear sampling. Sample the
target feature pyramid first, then take dot products with the source features.
This computes RAFT's existing neighborhoods without retaining an all-pairs
volume. Floating-point operation order differs from upstream CorrBlock.
"""
from contextlib import contextmanager
from functools import lru_cache
import math


@lru_cache(maxsize=8)
def _verify_corr_kernel(extension, device):
    """Probe the loaded build once per worker/device, including custom and PTX builds."""
    import torch
    with torch.cuda.device(device), torch.no_grad():
        features = torch.ones((1, 1, 1, 32), device='cuda', dtype=torch.float32)
        coords = torch.zeros((1, 1, 1, 1, 2), device='cuda', dtype=torch.float32)
        result, = extension.forward(features, features, coords, 0)
        if result.numel() != 1 or result.item() != 32.0:
            raise RuntimeError('The correlation kernel returned an unexpected result.')


def require_alt_cuda_corr():
    try:
        import torch  # Load PyTorch's DLL dependencies before the extension.
        import alt_cuda_corr
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            'Memory-efficient RAFT requires the compiled alt_cuda_corr extension. '
            'Run build_reezsynth_corr.py --install in the ReEzSynth environment '
            '(see INSTALL_WINDOWS.md). No slow fallback was selected.'
        ) from exc
    if getattr(alt_cuda_corr, 'reezsynth_build', None) != '0.2.0':
        raise RuntimeError('Rebuild alt_cuda_corr using build_reezsynth_corr.py --install for the tested ReEzSynth interface.')
    if not torch.cuda.is_available():
        raise RuntimeError('Memory-efficient RAFT correlation requires CUDA.')
    device = torch.cuda.current_device()
    try:
        _verify_corr_kernel(alt_cuda_corr, device)
    except RuntimeError as exc:
        formatted = '.'.join(map(str, torch.cuda.get_device_capability(device)))
        raise RuntimeError(f'The installed memory-efficient RAFT kernel failed on CUDA architecture {formatted}. '
                           'Use normal RAFT, or rebuild with build_reezsynth_corr.py --install. '
                           f'Kernel check: {exc}') from exc
    return alt_cuda_corr


class CompiledCorrBlock:
    def __init__(self, fmap1, fmap2, num_levels=4, radius=4):
        import torch.nn.functional as F
        self.extension = require_alt_cuda_corr()
        self.radius = radius
        self.channels = fmap1.shape[1]
        self.source = fmap1.permute(0, 2, 3, 1).contiguous()
        self.targets = []
        # Cache the layouts once per frame pair rather than copying on every iteration.
        for level in range(num_levels):
            self.targets.append(fmap2.permute(0, 2, 3, 1).contiguous())
            if level + 1 < num_levels:
                fmap2 = F.avg_pool2d(fmap2, 2, stride=2)

    def __call__(self, coords):
        import torch
        xy = coords.permute(0, 2, 3, 1).unsqueeze(1)
        correlations = []
        for level, target in enumerate(self.targets):
            sample_at = (xy / (2 ** level)).contiguous()
            (corr,) = self.extension.forward(self.source, target, sample_at, self.radius)
            correlations.append(corr.squeeze(1))
        return torch.cat(correlations, dim=1) / math.sqrt(self.channels)


class MemoryEfficientCorrBlock:
    def __init__(self, fmap1, fmap2, num_levels=4, radius=4, chunk_size=256):
        import torch.nn.functional as F
        if chunk_size < 1:
            raise ValueError('Correlation chunk size must be positive.')
        self.source = fmap1.flatten(2)
        self.shape = fmap1.shape
        self.radius = radius
        self.chunk_size = chunk_size
        self.pyramid = [fmap2]
        for _ in range(num_levels - 1):
            self.pyramid.append(F.avg_pool2d(self.pyramid[-1], 2, stride=2))

    def __call__(self, coords):
        import torch
        import torch.nn.functional as F
        batch, channels, height, width = self.shape
        coordinates = coords.permute(0, 2, 3, 1).reshape(batch, -1, 2)
        axis = torch.arange(-self.radius, self.radius + 1, device=coords.device, dtype=coords.dtype)
        # Preserve upstream's channel ordering (including its meshgrid convention).
        offsets = torch.stack(torch.meshgrid(axis, axis, indexing='ij'), dim=-1).reshape(-1, 2)
        neighbors = offsets.shape[0]
        result = coords.new_empty(batch, height * width, len(self.pyramid) * neighbors)
        for level, target in enumerate(self.pyramid):
            th, tw = target.shape[-2:]
            if min(th, tw) <= 1:
                raise ValueError('RAFT correlation pyramid dimensions must exceed one.')
            for start in range(0, height * width, self.chunk_size):
                end = min(start + self.chunk_size, height * width)
                grid = coordinates[:, start:end, None, :] / (2 ** level) + offsets
                grid = torch.stack((2 * grid[..., 0] / (tw - 1) - 1,
                                    2 * grid[..., 1] / (th - 1) - 1), dim=-1)
                sampled = F.grid_sample(target, grid, align_corners=True, padding_mode='zeros')
                values = (sampled * self.source[:, :, start:end, None]).sum(dim=1)
                result[:, start:end, level * neighbors:(level + 1) * neighbors] = values / math.sqrt(channels)
        return result.reshape(batch, height, width, -1).permute(0, 3, 1, 2).contiguous().float()


@contextmanager
def correlation_mode(enabled):
    """Worker-local override, restored on success/failure before the next job.

Each worker renders one job at a time. Parallel jobs have separate processes.
Keep upstream files and the default correlation implementation untouched.
"""
    if not enabled:
        yield
        return
    from ezsynth.utils.flow_utils.core import raft
    original = raft.CorrBlock
    raft.CorrBlock = CompiledCorrBlock
    try:
        print('[RAFT] Compiled alt_cuda_corr selected; full-resolution correlation.', flush=True)
        yield
    finally:
        raft.CorrBlock = original
