"""Frontend extensions around the pinned FuouM synthesis passes.

Keep frame/error correspondence explicit; retain styled keyframes exactly.
Imported only by the FuouM worker, except for the engine-independent planner.
"""
from types import SimpleNamespace


def segments(count, indices):
    result = []
    if indices[0] > 0:
        result.append((0, indices[0], 'reverse', 0, 0))
    result.extend((a, b, 'blend', i, i + 1) for i, (a, b) in enumerate(zip(indices, indices[1:])))
    if indices[-1] < count - 1:
        result.append((indices[-1], count - 1, 'forward', len(indices) - 1, len(indices) - 1))
    return result


def work_count(count, indices, mode='none'):
    return sum((b - a) * (2 if kind == 'blend' and mode == 'none' else 1)
               for a, b, kind, _, _ in segments(count, indices))


def run_sequences(pipeline, frames, styles, indices, mode, blend_frames, on_pass):
    """Pass errors omit their origin keyframe; intersect by target frame number."""
    output = [None] * len(frames)
    for number, (start, end, kind, left, right) in enumerate(segments(len(frames), indices)):
        seq = SimpleNamespace(start_frame=start, end_frame=end)
        def run(forward):
            result = pipeline._run_a_pass(seq=seq, style_img=styles[left if forward else right],
                                          is_forward=forward, content_frames=frames)
            if len(result[0]) != end - start + 1 or len(result[1]) != end - start:
                raise RuntimeError('FuouM pass returned inconsistent frame/error counts.')
            on_pass(number, start, end, forward, result)
            return result
        if kind == 'blend' and mode == 'none':
            fwd, rev = run(True), run(False)
            # fwd errors target start+1..end; reverse errors target start..end-1.
            middle = blend_frames(fwd[0][1:-1], rev[0][1:-1], fwd[1][:-1], rev[1][1:],
                                  pipeline._fwd_flows[start + 1:end - 1])
            rendered = [styles[left], *middle, styles[right]]
        else:
            forward = (mode == 'forward') if kind == 'blend' else kind == 'forward'
            rendered = run(forward)[0]
        output[start:end + 1] = rendered
    for index, style in zip(indices, styles):
        output[index] = style
    if any(frame is None for frame in output):
        raise RuntimeError('FuouM sequence plan left an output frame unassigned.')
    return output


def poisson_matrices(h, w, weights):
    """Differences match flattened gx/gy, with zero bottom/right boundaries."""
    import numpy as np
    from scipy import sparse
    grid = np.arange(h * w).reshape(h, w)
    def difference(origin, offset):
        origin = origin.ravel()
        return sparse.coo_matrix((np.tile([1., -1.], len(origin)),
            (np.repeat(origin, 2), np.column_stack((origin, origin + offset)).ravel())),
            shape=(h * w, h * w)).tocsc()
    gx, gy = difference(grid[:-1], w), difference(grid[:, :-1], 1)
    identity = sparse.eye(h * w, format='csc')
    return [sparse.vstack((gx * weight, gy * weight, identity), format='csc') for weight in weights]


def blend_aligned(fwd, rev, fwd_errors, rev_errors, flows, config):
    import cv2
    import numpy as np
    from ezsynth.utils.blend_logic import Reconstructor
    from ezsynth.utils.warp_utils import Warp
    if not fwd:
        return []
    h, w = fwd[0].shape[:2]
    warp = Warp(h, w)
    masks, hist = [], []
    previous = None
    for i, (a, b, ea, eb) in enumerate(zip(fwd, rev, fwd_errors, rev_errors)):
        mask = (np.asarray(ea) >= np.asarray(eb)).astype(np.uint8)
        if previous is not None:
            mask = np.maximum(mask, (warp.run_warping(previous.astype(np.float32),
                                                     -flows[i - 1]) > .5).astype(np.uint8))
        masks.append(mask)
        previous = mask
        # Upstream histogram normalization divides by zero on flat-color styles.
        al = cv2.cvtColor(a, cv2.COLOR_BGR2LAB).astype(np.float32)
        bl = cv2.cvtColor(b, cv2.COLOR_BGR2LAB).astype(np.float32)
        selected = np.where(mask[..., None] == 0, al, bl)
        normalized = []
        for value in (al, bl):
            normalized.append((value - value.mean((0, 1))) * (256 / 36) /
                              np.maximum(value.std((0, 1)), 1e-6) + 128)
        combined = normalized[0] + normalized[1] - 128
        result = ((combined - combined.mean((0, 1))) * selected.std((0, 1)) /
                  np.maximum(combined.std((0, 1)), 1e-6) + selected.mean((0, 1)))
        hist.append(cv2.cvtColor(np.clip(np.round(result), 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR))
    settings = config.model_dump()
    # PyAMG requires an integer, unlike SciPy's None = automatic convention.
    maximum = settings['poisson_maxiter']
    if settings['poisson_solver'] == 'amg' and maximum is None:
        maximum = 100
    class AlignedReconstructor(Reconstructor):
        def _prepare_cache_for_size(self, h, w):
            if (h, w) not in self._cache:
                cache = {}
                if self.solver in ('lsqr', 'lsmr', 'cg', 'amg'):
                    cache['As'] = poisson_matrices(h, w, self.grad_weights)
                    if self.solver in ('cg', 'amg'):
                        cache['AtAs'] = [a.T @ a for a in cache['As']]
                    if self.solver == 'amg':
                        import pyamg
                        cache['MLs'] = [pyamg.ruge_stuben_solver(a) for a in cache['AtAs']]
                self._cache[h, w] = cache
            return self._cache[h, w]
    reconstructor = AlignedReconstructor(solver=settings['poisson_solver'], poisson_maxiter=maximum,
        grad_weights=[settings['poisson_grad_weight_l'], settings['poisson_grad_weight_ab'],
                      settings['poisson_grad_weight_ab']])
    return reconstructor.run(hist, fwd, rev, masks)


def extend_pipeline(config, data, masks, edges, mask_weight, mode, on_pass):
    from ezsynth.pipeline import SynthesisPipeline
    class FrontendPipeline(SynthesisPipeline):
        def _compute_edge_maps(self, frames):
            if edges:
                self._edge_maps = edges
            else:
                super()._compute_edge_maps(frames)

        def _prepare_guides_for_frame(self, *args, **kwargs):
            guides = super()._prepare_guides_for_frame(*args, **kwargs)
            if masks and mask_weight:
                guides.append((masks[kwargs['keyframe_idx']], masks[kwargs['target_idx']], mask_weight))
            return guides

        def _compute_optical_flow(self, frames):
            if self.config.precomputation.flow_engine != 'NeuFlow':
                return super()._compute_optical_flow(frames)
            # NeuFlow v2 initializes fixed 1/16-resolution grids: pad, then unpad.
            import cv2
            import torch
            from ezsynth.engines.flow_engine import NeuFlowEngine
            h, w = frames[0].shape[:2]
            padded = [cv2.copyMakeBorder(f, 0, (-h) % 16, 0, (-w) % 16,
                                        cv2.BORDER_REPLICATE) for f in frames]
            engine = NeuFlowEngine(model_name=self.config.precomputation.flow_model)
            try:
                self._fwd_flows = [f[:h, :w].copy() for f in engine.compute(padded)]
            finally:
                del engine
                torch.cuda.empty_cache()

        def _run_synthesis(self, content_frames, style_frames):
            return run_sequences(self, content_frames, style_frames, config.project.style_indices, mode,
                                 lambda *a: blend_aligned(*a, config.blending), on_pass)
    return FrontendPipeline(config, data)
