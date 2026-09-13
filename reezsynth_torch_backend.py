"""Versioned, instance-local repairs for FuouM's PyTorch PatchMatch backend.

Retains the pinned engine's pyramids and NNF transport. Search is synchronous
within each candidate batch, not bit-equivalent to the native CUDA kernel.
No upstream modules or installed files are patched. Torch imports stay lazy.
"""
VERSION = 'frontend-torch-v1'
CHUNK_ELEMENTS = 2 ** 20


def working_bytes(source_size, target_size, channels, patch):
    """Conservative extra workspace, including unfold/cast and voting peaks."""
    pixels = source_size[0] * source_size[1] + target_size[0] * target_size[1]
    return 64 * 2 ** 20 + pixels * (8 * patch * patch * (3 + channels) + 128)


def patches(image, patch):
    import torch.nn.functional as F
    h, w, c = image.shape
    data = image.permute(2, 0, 1).unsqueeze(0).float()
    data = F.pad(data, (patch // 2,) * 4, mode='replicate')
    data = F.unfold(data, patch).squeeze(0).T
    return data.to(image.dtype).reshape(h, w, c, patch * patch).contiguous()


class PatchCost:
    def __init__(self, style, source, target, modulation, style_weights, guide_weights, patch, mode):
        self.style = patches(style, patch)
        self.source = patches(source, patch)
        self.target = patches(target, patch).flatten(0, 1)
        self.modulation = (patches(modulation, patch).flatten(0, 1)
                           if modulation.numel() else None)
        self.style_weights, self.guide_weights = style_weights, guide_weights
        self.patch, self.mode = patch, mode
        self.shape = target.shape[:2]
        self.target_style = None

    def set_target(self, image):
        self.target_style = patches(image, self.patch).flatten(0, 1)

    def __call__(self, coords, indices=None):
        import torch
        original_shape = coords.shape[:-1]
        coords = coords.reshape(-1, 2).long()
        channels = max(self.style.shape[2], self.source.shape[2])
        chunk = max(1, CHUNK_ELEMENTS // (channels * self.patch ** 2))
        errors = torch.empty(len(coords), device=coords.device, dtype=torch.float32)
        for start in range(0, len(coords), chunk):
            end = min(len(coords), start + chunk)
            index = slice(start, end) if indices is None else indices[start:end]
            x = coords[start:end, 0].clamp(0, self.style.shape[1] - 1)
            y = coords[start:end, 1].clamp(0, self.style.shape[0] - 1)
            source, target = self.style[y, x].float(), self.target_style[index].float()
            if self.mode == 1:  # NCC of channel-mean style; SSD of guide channels.
                source, target = source.mean(1), target.mean(1)
                source = source - source.mean(1, keepdim=True)
                target = target - target.mean(1, keepdim=True)
                denominator = (source.square().mean(1) * target.square().mean(1)).sqrt()
                ncc = torch.where(denominator > 1e-12,
                    (source * target).mean(1) / denominator.clamp_min(1e-12), 0).clamp(-1, 1)
                error = (1 - ncc) * self.style_weights[0] * self.patch ** 2
            else:
                error = ((source - target).square() * self.style_weights[None, :, None]).sum((1, 2))
            difference = (self.source[y, x].float() - self.target[index].float()).square()
            if self.modulation is not None:
                difference *= self.modulation[index].float() / 255
            errors[start:end] = error + (difference * self.guide_weights[None, :, None]).sum((1, 2))
        return errors.reshape(original_shape)


def occupancy(nnf, source_shape, patch):
    """Exact occupancy from the current valid NNF, with no stale update cache."""
    import torch
    import torch.nn.functional as F
    h, w = source_shape
    centers = torch.bincount((nnf[..., 1].long() * w + nnf[..., 0].long()).flatten(),
                            minlength=h * w).reshape(1, 1, h, w).float()
    kernel = torch.ones((1, 1, patch, patch), device=nnf.device)
    counts = F.conv2d(centers, kernel, padding=patch // 2)
    # CUDA's patch sum / area / expected per-source-pixel occupancy.
    expected = max(nnf.shape[0] * nnf.shape[1] / (h * w) * patch ** 2, 1e-6)
    scores = F.conv2d(counts, kernel, padding=patch // 2)[0, 0] / (patch ** 2 * expected)
    return counts[0, 0], scores


def accept_candidates(nnf, errors, candidates, active, cost, uniformity):
    """Apply only valid active improvements, using current occupancy for both sides."""
    h, w = cost.style.shape[:2]
    r = cost.patch // 2
    valid = (active & (candidates[..., 0] >= r) & (candidates[..., 0] < w - r) &
             (candidates[..., 1] >= r) & (candidates[..., 1] < h - r))
    indices = valid.flatten().nonzero(as_tuple=True)[0]
    if indices.numel() == 0:
        return
    current = nnf.reshape(-1, 2)[indices].long()
    candidate = candidates.reshape(-1, 2)[indices].long()
    proposed = cost(candidate, indices)
    difference = proposed - errors.flatten()[indices]
    if uniformity:
        _, scores = occupancy(nnf, (h, w), cost.patch)
        difference += uniformity * (scores[candidate[:, 1], candidate[:, 0]] -
                                     scores[current[:, 1], current[:, 0]])
    chosen = difference < 0
    indices = indices[chosen]
    nnf.reshape(-1, 2)[indices] = candidate[chosen].to(nnf.dtype)
    errors.flatten()[indices] = proposed[chosen]


def propagate(nnf, errors, active, cost, uniformity, forward):
    import torch
    step = 1 if forward else -1
    for dimension, component in ((1, 0), (0, 1)):
        candidates = torch.roll(nnf, step, dimension)
        candidates[..., component] += step
        allowed = active.clone()
        if dimension == 1:
            allowed[:, 0 if forward else -1] = False
        else:
            allowed[0 if forward else -1, :] = False
        # Vertical candidates see the completed horizontal update and occupancy.
        accept_candidates(nnf, errors, candidates, allowed, cost, uniformity)


def random_search(nnf, errors, active, cost, uniformity, pruning, generator=None):
    import torch
    radius = max(cost.style.shape[:2]) // 2
    while radius >= 1:
        # Keep the grid rank even when exactly one target remains active.
        allowed = active & (errors >= pruning) if pruning > 0 else active
        offsets = torch.randint(-radius, radius + 1, nnf.shape, device=nnf.device,
                                dtype=nnf.dtype, generator=generator)
        accept_candidates(nnf, errors, nnf + offsets, allowed, cost, uniformity)
        radius //= 2


def vote(style_patches, nnf, errors, patch, weighted):
    import torch
    import torch.nn.functional as F
    h, w = nnf.shape[:2]
    values = style_patches[nnf[..., 1].long(), nnf[..., 0].long()].float()
    weights = 1 / (1 + errors.clamp_min(0)) if weighted else torch.ones_like(errors)
    # Normalize globally; a common factor cancels from numerator/denominator.
    weights = weights / weights.max().clamp_min(torch.finfo(weights.dtype).tiny)
    numerator = (values * weights[..., None, None]).reshape(h * w, -1).T.unsqueeze(0)
    numerator = F.fold(numerator, (h, w), patch, padding=patch // 2)
    denominator = weights.flatten()[None, None, :].expand(1, patch ** 2, h * w)
    denominator = F.fold(denominator, (h, w), patch, padding=patch // 2)
    image = numerator / denominator.clamp_min(torch.finfo(denominator.dtype).tiny)
    return image[0].permute(1, 2, 0).round().clamp(0, 255).to(torch.uint8).contiguous()


def run_level(self, style_tensor, source_guide_tensor, target_guide_tensor, modulation_tensor,
              nnf, style_weights, guide_weights, uniformity_weight, patch_size, vote_mode,
              search_vote_iters, patch_match_iters, stop_threshold, rand_states,
              cost_function_mode, benchmark=False):
    """Repaired iterative refinement; false upstream flag retains single-vote mode."""
    import torch
    import torch.nn.functional as F
    from time import perf_counter
    started = perf_counter()
    h, w = target_guide_tensor.shape[:2]
    sh, sw = style_tensor.shape[:2]
    r = patch_size // 2
    if nnf.shape != (h, w, 2) or min(sh, sw) <= 2 * r:
        raise ValueError('PyTorch synthesis requires a target-grid NNF and valid source patches.')
    if modulation_tensor.numel() and (modulation_tensor.shape != target_guide_tensor.shape or
                                     modulation_tensor.dtype != torch.uint8):
        raise ValueError('PyTorch modulation must be uint8 on the concatenated target guide grid.')
    if cost_function_mode not in (0, 1) or vote_mode not in (0x0001, 0x0002):
        raise ValueError('Unsupported PyTorch cost or voting mode.')
    if search_vote_iters < 1 or patch_match_iters < 1:
        raise ValueError('PyTorch iteration counts must be positive.')
    if style_tensor.is_cuda:
        required = working_bytes((sw, sh), (w, h), target_guide_tensor.shape[2], patch_size)
        free, _ = torch.cuda.mem_get_info(style_tensor.device)
        if required + 512 * 2 ** 20 > free:
            raise RuntimeError('Insufficient free CUDA memory for PyTorch patch buffers. '
                               'Reduce processing size/patch size or select the CUDA backend.')
    nnf = nnf.clone().contiguous()
    nnf[..., 0].clamp_(r, sw - r - 1)
    nnf[..., 1].clamp_(r, sh - r - 1)
    cost = PatchCost(style_tensor, source_guide_tensor, target_guide_tensor, modulation_tensor,
                     style_weights, guide_weights, patch_size, cost_function_mode)
    target = self._resample_tensor(style_tensor, h, w)
    cost.set_target(target)
    errors = cost(nnf)  # Errors always use the target grid, never the occupancy grid.
    active = torch.ones((h, w), device=nnf.device, dtype=torch.bool)
    weighted = vote_mode == 0x0002
    if self.pipeline_config.use_residual_transfer:
        target = vote(cost.style, nnf, errors, patch_size, weighted)
        for _ in range(search_vote_iters):
            cost.set_target(target)
            errors = cost(nnf)
            for iteration in range(patch_match_iters):
                propagate(nnf, errors, active, cost, uniformity_weight, bool(iteration % 2))
            random_search(nnf, errors, active, cost, uniformity_weight,
                          self.ebsynth_config.search_pruning_threshold)
            output = vote(cost.style, nnf, errors, patch_size, weighted)
            if stop_threshold > 0:
                changed = (output.int() - target.int()).abs().amax(2) >= stop_threshold
                active = F.max_pool2d(changed[None, None].float(), patch_size,
                                     stride=1, padding=r)[0, 0].bool()
            target = output
    else:
        for iteration in range(patch_match_iters):
            propagate(nnf, errors, active, cost, uniformity_weight, bool(iteration % 2))
            random_search(nnf, errors, active, cost, uniformity_weight,
                          self.ebsynth_config.search_pruning_threshold)
        for _ in range(search_vote_iters):
            random_search(nnf, errors, active, cost, uniformity_weight,
                          self.ebsynth_config.search_pruning_threshold)
        target = vote(cost.style, nnf, errors, patch_size, weighted)
    cost.set_target(target)
    errors = cost(nnf)
    if not torch.isfinite(errors).all():
        raise RuntimeError('Nonfinite PyTorch synthesis errors.')
    if benchmark:
        if style_tensor.is_cuda:
            torch.cuda.synchronize(style_tensor.device)
        print(f'[Torch] {VERSION} level: {perf_counter() - started:.3f}s', flush=True)
    return target, errors, nnf
