# Alternate FuouM backend readiness

Reviewed 2026-09-12 at pinned FuouM revision
`aaa8d06170e6cc59054410aa9c422edd789f7ab2` on this Windows/RTX 5090 host.
The original pinned `torch` backend fails the audit below. The frontend now
offers an **experimental repaired implementation**, `frontend-torch-v1`, through
Rendering > Synthesis backend > `torch`. The default remains `cuda`. No installed
engine files are changed. Both choices currently require CUDA; this is not a
CPU-only installation/fallback feature.

## Repaired implementation

The versioned [repair layer](reezsynth_torch_backend.py) replaces only an engine
instance's level function inside the existing compatibility wrapper. Original
methods are restored on completion/failure. The pinned pyramid construction,
resampling, flow, guide preparation and NNF transport remain in use. It repairs:

- Target-sized initial/recomputed/final errors, including retargeted images.
- Spatial, per-channel target-grid modulation in SSD and NCC guide costs.
- Weighted voting via overlap folding and ratio-preserving normalization; small
  valid inverse-error weights no longer darken constant colors.
- Active-mask and valid-source-center checks for candidate acceptance. Vertical
  propagation sees the completed horizontal update. Occupancy is rebuilt from
  the current NNF for each candidate batch, avoiding stale partial updates.
- Rank-preserving random search, including a single active target and pruning.
- Real alternating search/vote refinement with per-level counts, convergence
  masks, and final errors recomputed against the actual returned image.

Search is synchronous within each candidate batch and voting rounds to uint8.
These are explicit implementation choices, not a claim of bit-identical CUDA
results. The frontend exposes the iterative path only. The upstream flag's false
single-vote path is repaired/tested for completeness but remains unexposed as a
separate residual-transfer workflow.

Patches are retained as uint8; float cost temporaries are chunked. Full patch
storage and fold/unfold peaks still scale with source/target pixels, patch area
and channel count. Parallel reservations include a conservative workspace
estimate (video uses the 24-channel cap; images inspect guide headers), and every
CUDA level checks estimated workspace plus 512 MiB against current free memory.
Rejection recommends reducing processing/patch size or selecting native CUDA;
there is no silent fallback. Disk-backed frame storage does not bound this GPU
workspace. Estimates are safeguards, not allocation guarantees.

Presets/projects retain `fuoum_backend`; old documents resolve to `cuda`.
Engine manifests record implementation version, device and adapter hash, and
image manifests record the selected backend. The control is FuouM-only and locked
during work. The pinned CUDA extension remains required by standard setup/imports
even when the repaired PyTorch search is selected.

## Reproduction and acceptance gate

Run `python -B diagnose_reezsynth_torch_backend.py` from the configured Legacy
environment. The diagnostic starts separate workers in the installed FuouM
environment for `cuda` and `torch`. Use `--backend cuda` or `--backend torch`
to select one. Add `--repaired` to test the frontend repair layer; omit it to
reproduce the original upstream failures. Both run on the GPU on this host;
`torch` does not mean CPU here.

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

## Original source findings and repair scope

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

The user approved repairs after this audit. The versioned layer above and its
independent CPU tests now cover these algorithmic concerns; the original
upstream implementation remains unchanged and should not be enabled directly.

## Verification of the repaired layer

- `torch_backend_20260912_212429_874906`: all nine original gates pass with
  `--repaired`, for both PyTorch and unchanged CUDA.
- `release_fuoum_20260912_212621_248210`: 14 real Standard cases at 257x145,
  five frames, three differently sized multiguide images, every modulation mode,
  masks/custom edges/reverse passes, schedules, bounded storage and bidirectional
  flow. Three output images were inspected for gross corruption. This does not
  establish broad visual quality or parity.
- `gui_controller_20260912_212834_678710`: real nine-frame 512x288 Preview
  cancellation after synthesis began, followed by successful fresh-output restart
  with disk-backed storage. Device-wide GPU usage was 5,339 MiB before and
  5,342 MiB after; these are snapshots, not per-process leak or peak measurements.
- `release_fuoum_20260912_212938_505364`: nine more real scalar Standard cases
  cover the default temporal path, sparse/temporal toggles, plain NCC, feathered
  masks, NeuFlow, auxiliary exports and three multiguide images with verified
  `torch` image backend metadata.
- The canonical maintained suite passed 317 tests in 45.954 seconds, including
  scalar SSD/NCC/spatial-modulation oracles, brute-force occupancy and voting,
  active-mask/rank/iteration checks, low-memory rejection, instance restoration,
  GUI persistence and effective provenance. The selector layout was inspected.
- `gui_controller_20260912_213219_627804`: two real 512x288 Preview jobs passed
  automatic GPU-aware parallel admission/completion with bounded storage.

To repeat real frontend checks, use `--synthesis-backend torch` with
`diagnose_reezsynth_release.py --engine fuoum` or
`diagnose_reezsynth_gui.py --fuoum`. Release diagnostics accept `--only LABEL ...`
to select generated cases; other flags such as `--extended`/`--images` still
determine the available labels.

Production/overnight/other-hardware validation remains separate outstanding work.
