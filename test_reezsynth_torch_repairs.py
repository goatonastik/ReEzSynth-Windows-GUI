"""Independent CPU mathematical checks for the instance-local torch repair layer."""
import types
import unittest
from unittest.mock import patch

import numpy as np

import reezsynth_torch_backend as repaired


def backend(iterative=True, pruning=0):
    def resample(image, h, w):
        return F.interpolate(image.permute(2, 0, 1)[None].float(), (h, w),
                             mode='bilinear', align_corners=False)[0].permute(1, 2, 0).to(torch.uint8)
    return types.SimpleNamespace(pipeline_config=types.SimpleNamespace(use_residual_transfer=iterative),
        ebsynth_config=types.SimpleNamespace(search_pruning_threshold=pruning), _resample_tensor=resample)


class TorchRepairMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global torch, F
        import torch
        import torch.nn.functional as F
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        torch.manual_seed(7)
        self.style = torch.randint(0, 255, (7, 11, 3), dtype=torch.uint8)
        self.source = torch.randint(0, 255, (7, 11, 2), dtype=torch.uint8)
        self.target = torch.randint(0, 255, (5, 9, 2), dtype=torch.uint8)
        self.mod = torch.randint(0, 255, (5, 9, 2), dtype=torch.uint8)
        self.sw = torch.tensor([.2, .3, .5])
        self.gw = torch.tensor([.7, 1.3])
        self.nnf = torch.empty((5, 9, 2), dtype=torch.int32)
        self.nnf[..., 0] = torch.randint(1, 10, (5, 9))
        self.nnf[..., 1] = torch.randint(1, 6, (5, 9))

    def cost(self, mode=0, modulation=True):
        cost = repaired.PatchCost(self.style, self.source, self.target,
            self.mod if modulation else torch.empty(0, dtype=torch.uint8), self.sw, self.gw, 3, mode)
        target_style = backend()._resample_tensor(self.style, 5, 9)
        cost.set_target(target_style)
        return cost, target_style

    def brute_cost(self, target_style, mode):
        style, source, target, mod = [v.numpy().astype(float) for v in
                                     (self.style, self.source, self.target, self.mod)]
        target_style = target_style.numpy().astype(float)
        result = np.zeros((5, 9))
        for y in range(5):
            for x in range(9):
                sx, sy = self.nnf[y, x].tolist()
                style_pairs, guides = [], 0.
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ty, tx = np.clip(y + dy, 0, 4), np.clip(x + dx, 0, 8)
                        s, t = style[sy + dy, sx + dx], target_style[ty, tx]
                        style_pairs.append((s, t))
                        guides += np.sum((source[sy + dy, sx + dx] - target[ty, tx]) ** 2 *
                                         self.gw.numpy() * mod[ty, tx] / 255)
                a, b = np.array(style_pairs).transpose(1, 0, 2)
                if mode == 0:
                    style_error = np.sum((a - b) ** 2 * self.sw.numpy())
                else:
                    a, b = a.mean(1), b.mean(1)
                    a, b = a - a.mean(), b - b.mean()
                    denominator = np.sqrt(np.mean(a * a) * np.mean(b * b))
                    ncc = np.mean(a * b) / denominator if denominator > 1e-12 else 0
                    style_error = (1 - ncc) * float(self.sw[0]) * 9
                result[y, x] = style_error + guides
        return result

    def test_ssd_ncc_spatial_multichannel_modulation_matches_scalar_oracle(self):
        for mode in (0, 1):
            cost, target_style = self.cost(mode)
            np.testing.assert_allclose(cost(self.nnf).numpy(), self.brute_cost(target_style, mode), rtol=2e-6)
            # Force tiny chunks and a nonconsecutive target subset.
            indices = torch.tensor([0, 7, 39])
            with patch.object(repaired, 'CHUNK_ELEMENTS', 9):
                actual = cost(self.nnf.reshape(-1, 2)[indices], indices)
            torch.testing.assert_close(actual, cost(self.nnf).flatten()[indices])

    def test_occupancy_and_uniformity_scores_match_brute_counts(self):
        counts = np.zeros((7, 11))
        for sx, sy in self.nnf.reshape(-1, 2).tolist():
            counts[sy - 1:sy + 2, sx - 1:sx + 2] += 1
        actual, scores = repaired.occupancy(self.nnf, (7, 11), 3)
        np.testing.assert_array_equal(actual.numpy(), counts)
        expected = 45 / 77 * 9
        for sy, sx in ((1, 1), (3, 4), (5, 9)):
            self.assertAlmostEqual(float(scores[sy, sx]),
                counts[sy - 1:sy + 2, sx - 1:sx + 2].sum() / 9 / expected, places=5)

    def test_candidates_modify_only_active_valid_improvements(self):
        cost, _ = self.cost()
        before = self.nnf.clone()
        errors = torch.full((5, 9), float('inf'))
        candidate = torch.full_like(self.nnf, 2)
        candidate[0, 0] = 0  # Invalid source patch center.
        active = torch.zeros((5, 9), dtype=torch.bool)
        active[0, :2] = True
        repaired.accept_candidates(self.nnf, errors, candidate, active, cost, 3500)
        expected = before.clone()
        expected[0, 1] = 2
        torch.testing.assert_close(self.nnf, expected)
        self.assertTrue(torch.isfinite(errors[0, 1]))
        self.assertEqual(int(torch.isfinite(errors).sum()), 1)

    def test_propagation_respects_mask_and_rebuilds_current_occupancy(self):
        cost, _ = self.cost()
        before = self.nnf.clone()
        errors = torch.full((5, 9), float('inf'))
        active = torch.zeros((5, 9), dtype=torch.bool)
        active[2, 3] = True
        snapshots = []
        original = repaired.occupancy
        def observe(nnf, *args):
            snapshots.append(nnf.clone())
            return original(nnf, *args)
        with patch.object(repaired, 'occupancy', side_effect=observe):
            repaired.propagate(self.nnf, errors, active, cost, 3500, True)
        torch.testing.assert_close(self.nnf[~active], before[~active])
        self.assertEqual(len(snapshots), 2)
        self.assertFalse(torch.equal(snapshots[0], snapshots[1]))

    def test_random_search_single_target_and_pruning_keep_grid_rank(self):
        cost, _ = self.cost()
        before = self.nnf.clone()
        errors = torch.full((5, 9), float('inf'))
        active = torch.zeros((5, 9), dtype=torch.bool)
        active[2, 3] = True
        repaired.random_search(self.nnf, errors, active, cost, 3500, 0)
        torch.testing.assert_close(self.nnf[~active], before[~active])
        self.assertTrue(torch.isfinite(errors[2, 3]))
        before = self.nnf.clone()
        errors.zero_()
        repaired.random_search(self.nnf, errors, active, cost, 3500, 1)
        torch.testing.assert_close(self.nnf, before)

    def test_weighted_vote_preserves_constant_at_tiny_weights_and_matches_oracle(self):
        constant = repaired.patches(torch.full((7, 11, 3), 127, dtype=torch.uint8), 3)
        errors = torch.logspace(15, 25, 45).reshape(5, 9)
        actual = repaired.vote(constant, self.nnf, errors, 3, True)
        self.assertTrue(torch.all(actual == 127))
        values = repaired.patches(self.style, 3)
        for weighted in (True, False):
            actual = repaired.vote(values, self.nnf, errors, 3, weighted).numpy()
            numerator, denominator = np.zeros((5, 9, 3)), np.zeros((5, 9, 1))
            for y in range(5):
                for x in range(9):
                    sx, sy = self.nnf[y, x].tolist()
                    weight = 1 / (1 + float(errors[y, x])) if weighted else 1
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            if 0 <= y + dy < 5 and 0 <= x + dx < 9:
                                numerator[y + dy, x + dx] += self.style[sy + dy, sx + dx].numpy() * weight
                                denominator[y + dy, x + dx] += weight
            np.testing.assert_allclose(actual, np.round(numerator / denominator), atol=1)

    def test_retargeted_both_refinement_modes_and_final_errors(self):
        for iterative in (False, True):
            args = [backend(iterative), self.style, self.source, self.target, self.mod, self.nnf,
                    self.sw, self.gw, 3., 3, 2, 2, 2, 0, None, 0]
            image, error, nnf = repaired.run_level(*args)
            self.assertEqual(image.shape, (5, 9, 3))
            cost, _ = self.cost()
            cost.set_target(image)
            torch.testing.assert_close(error, cost(nnf))
            self.assertTrue(torch.isfinite(error).all())

    def test_iteration_counts_and_early_stop_are_effective(self):
        constant = torch.full_like(self.style, 127)
        args = [backend(), constant, self.source, self.target, self.mod, self.nnf,
                self.sw, self.gw, 0., 3, 2, 3, 2, 5, None, 0]
        active_masks = []
        original = repaired.propagate
        def observe(nnf, errors, active, *rest):
            active_masks.append(active.clone())
            return original(nnf, errors, active, *rest)
        with patch.object(repaired, 'propagate', side_effect=observe):
            repaired.run_level(*args)
        self.assertEqual(len(active_masks), 6)
        self.assertTrue(active_masks[0].all())
        self.assertFalse(active_masks[-1].any())

    def test_memory_estimate_accounts_for_both_grids_channels_and_patch_area(self):
        base = repaired.working_bytes((19, 17), (23, 21), 1, 3)
        for source, target, channels, patch_size in (((39, 37), (23, 21), 1, 3),
                ((19, 17), (43, 41), 1, 3), ((19, 17), (23, 21), 4, 3),
                ((19, 17), (23, 21), 1, 7)):
            self.assertGreater(repaired.working_bytes(source, target, channels, patch_size), base)

    def test_instance_adapter_restores_and_does_not_patch_upstream_class(self):
        from reezsynth_fuoum import install_final_pass_compatibility
        original = lambda *args, **kwargs: 'original'
        eb = types.SimpleNamespace(backend_type='torch', device='cuda', backend=types.SimpleNamespace(run_level=original),
            ebsynth_config=types.SimpleNamespace(vote_mode='weighted', cost_function='ssd'),
            vote_mode_map={'weighted': 2}, cost_function_map={'ssd': 0})
        calls = []
        with patch.object(repaired, 'run_level', side_effect=lambda *a, **kw: calls.append((a, kw))) as run:
            saved = install_final_pass_compatibility(eb)
            values = [None] * 16
            eb.backend.run_level(*values)
            self.assertIs(saved, original)
            self.assertIs(calls[0][0][0], eb.backend)
            self.assertEqual(calls[0][0][10], 2)
            self.assertEqual(calls[0][0][15], 0)
            eb.backend.run_level = saved
            self.assertEqual(eb.backend.run_level(), 'original')
        eb.device = 'cpu'
        with self.assertRaisesRegex(ValueError, 'requires CUDA'):
            install_final_pass_compatibility(eb)

    def test_memory_guard_rejects_before_patch_allocation(self):
        style = types.SimpleNamespace(shape=self.style.shape, is_cuda=True, device='cuda')
        args = [backend(), style, self.source, self.target, self.mod, self.nnf,
                self.sw, self.gw, 3., 3, 2, 2, 2, 0, None, 0]
        with patch('torch.cuda.mem_get_info', return_value=(1024, 2 ** 30)), \
             patch.object(repaired, 'PatchCost') as allocate, \
             self.assertRaisesRegex(RuntimeError, 'Insufficient free CUDA memory'):
            repaired.run_level(*args)
        allocate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
