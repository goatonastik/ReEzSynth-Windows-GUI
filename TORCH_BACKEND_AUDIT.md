# Alternate FuouM backend readiness

Reviewed 2026-09-12 at pinned FuouM revision
`aaa8d06170e6cc59054410aa9c422edd789f7ab2` on this Windows/RTX 5090 host.
The alternate `torch` backend remains **disabled in the frontend**. No installed
engine files, render defaults or backend selections were changed by this audit.

## Reproduction and acceptance gate

Run `python -B diagnose_reezsynth_torch_backend.py` from the configured Legacy
environment. The diagnostic starts separate workers in the installed FuouM
environment for `cuda` and `torch`. Use `--backend cuda` or `--backend torch`
to select one. Both run on the GPU on this host; `torch` does not mean CPU here.

The nine tiny cases use a constant 127 style, a zero-valued source guide and a
255-valued target guide. Any patch assignment should preserve the constant style
(one quantization unit is tolerated). Independent expected guide costs are
`patch_area * 255^2 * guide_weight * modulation / 255`; flat-style NCC adds the
pinned implementation's `patch_area / 3` style term. Tests also require finite,
target-sized errors and valid source patch centers in the target-grid NNF.
Random seeds are fixed; native exceptions are recorded without skipping later
cases. A failed invariant, child failure or timeout yields a nonzero exit status.

Logs and incremental JSON reports are retained under `diagnostic_outputs/`.
Reports contain source/native-extension hashes, diagnostic hash, image hashes,
device, individual timings and PyTorch allocator peaks. Tiny-image timings are
not production performance measurements; allocator peaks are not device-wide
VRAM peaks or scheduler reservation estimates. This gate is necessary but not
sufficient for general quality or readiness.

## Observed failures

Initial retained report: `torch_backend_20260912_211602_747745`.
The final hash-recorded run, `torch_backend_20260912_211813_699042`, reproduced
the same results after adding CPU-only tests for the diagnostic oracle.
CUDA passed all nine cases; PyTorch passed five and failed four:

| Case | Required result | Observed alternate-backend result |
| --- | --- | --- |
| Retarget 19x17 style to 23x21 target | Target-sized output/errors | Tensor width mismatch, 19 versus 23 |
| Gray modulation 128 | Mean guide error 293,760 | 585,225 (unchanged) |
| Black modulation 0 | Zero guide error | 585,225 (unchanged) |
| Weighted voting, patch 7, guide weight 100 | Constant style 127 | Values 6-19, maximum deviation 121 |

The basic SSD, NCC, noniterative constant case, white modulation and plain-voting
high-cost case passed. Passing constant cases does not verify general matching.
Guide weight 100 is within the supported frontend domain, not a malformed input.

## Source findings and repair scope

The failures correspond to the pinned implementation:

- Its iterative branch allocates recomputed error buffers with
  `full_like(omega_map)`. Omega is source-sized; errors/NNFs must be target-sized.
- `modulation_tensor` is accepted by both backend paths but is not used in guide
  cost calculation. Wiring the parameter into the outer wrapper is insufficient.
- Weighted voting clamps the accumulated weight denominator to `1e-6`. When
  valid inverse-error weights sum below that threshold, constant colors darken.
  A repair must preserve the normalization ratio without unstable division.

Further source-review concerns need their own numerical regressions before a
selector is offered; they have not yet been established by the nine render cases:

- Noniterative initialization discards `try_patch_batch`'s returned errors. Its
  search/vote count drives additional random searches followed by one vote,
  unlike the iterative branch's alternating refinement.
- Propagation applies returned NNF changes outside the active convergence mask
  while filtering occupancy updates by that mask. Horizontal occupancy updates
  reference the NNF after vertical propagation, not the intermediate NNF.
- Random search uses a bare `squeeze()` on occupancy scores; a single active
  target may become a scalar and break subsequent indexing. Cached occupancy
  scores also need validation after updates.
- Full patch unfolding has different memory requirements from the CUDA kernel.
  GPU admission must account for patch area, guide channels, and both grids;
  disk-backed clip storage does not bound these per-frame allocations.

The upstream `use_residual_transfer` flag selects the two search-loop variants;
its name alone is not evidence of an independently validated residual-transfer
workflow. Do not expose it as a harmless on/off equivalent.

Safe integration needs a deliberate, versioned repair layer (or a separately
approved upstream revision), low-level cost/occupancy/mask/voting tests and real
image/video/grouped runs with retargeting, schedules, temporal NNFs, masks,
modulation, SSD/NCC, processing sizes and cancellation. Preserve the currently
working CUDA path and record any repaired implementation's identity in output
provenance. This is outstanding high-reasoning implementation work, not routine
campaign execution. The repair-versus-deferral decision is pending.
