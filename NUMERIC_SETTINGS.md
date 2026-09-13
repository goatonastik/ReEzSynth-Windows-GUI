# Numeric settings audit

Reviewed against the live local engine on 2026-09-11. This records the current
frontend domain, not a claim that every value accepted by the upstream Python API
has been exposed or tested with the native renderer.

| Control | Frontend values | Engine behavior / remaining limitation |
| --- | --- | --- |
| Diversity / uniformity | 0–100,000; default 3,500 | RunConfig describes 500–15,000 as a reasonable range, not hard limits. The frontend maximum is a policy cap. Passed to a native float. |
| Patch size | Odd integers 3–99; Standard default 7 | Wrapper requires odd values at least 3. Its pyramid calculation additionally requires every processed style/target dimension to be at least `2 * patchsize + 1`. The 99 maximum is a frontend cap. |
| Pyramid levels | Automatic (-1), or 1–32; Standard default 6 | Wrapper derives the usable maximum from image and patch dimensions and clamps explicit requests to it. Automatic selects that maximum. Requests yielding no usable level are now rejected before engine construction. |
| Search/vote iterations | 1–1,000; Standard default 12 | Scalar fallback, or an optional coarse-to-fine schedule of 1–32 counts in the same range. Schedules align at the finest level as described below. |
| Patch-match iterations | 1–1,000; Standard default 6 | Same optional schedule and frontend policy cap. |
| Video edge/image/position/warp/mask-guide weights | 0–10,000 | Wrapper converts guide weights to per-channel native floats. Frontend caps remain a policy limit; editors preserve six decimal places. |
| Video key / image style weight | 0.001–10,000 | Frontend ratio control: guide weights are divided by this value; native style weight stays fixed. This is not a direct upstream RunConfig key weight. |
| Image primary/additional guide weights | 0–10,000 | Six-decimal editors and style-ratio normalization. Image validation checks the 24-channel native guide limit separately. |
| Mask feather | 0 or odd integers 1–999 | Zero disables feathering; nonzero values are Gaussian kernel sizes. The maximum is frontend policy. |
| Reconstruction iteration limit | Automatic (UI 0, saved null), or 1–2,147,483,647 | Legacy LSMR only; FuouM LSQR/LSMR/CG/AMG. FuouM AMG uses 100 for automatic. Disabled for seamless/disabled reconstruction. |
| Custom processing size | Integer width/height 128–16,384 | Frontend bounds; not universal native limits. Multi-frame RAFT also requires at least 128 pixels per dimension. Original-size still images may be smaller if the patch constraint is satisfied. |
| Parallel limit | 0–64; default 2 when enabled | Zero uses GPU-aware automatic admission; positive values are hard caps. Parallel rendering remains off by default. |
| Preview limit | 1–64; default 8 | Application setting. The editor and validator now agree; previously the editor allowed 0–10,000. |

## Corrections from this audit

- Video synthesis checks patch geometry before importing torch or constructing an
  engine. Single-frame keyframe copies skip this check because they do not invoke
  EbSynth. Image synthesis checks both processed style and target sizes before
  constructing ImageSynthBase. Neither path silently changes the patch or image size.
- The former image check only required a patch to fit. For example, patch 7 in a
  14-pixel dimension passed that check but produced zero usable pyramid levels;
  15 pixels is the actual minimum under the local wrapper's calculation.
- Regression tests execute the live wrapper's pure pyramid calculation without
  loading the DLL, exercise both sides of the boundary, and verify that invalid
  jobs cannot create COMPLETE.txt. Separate tests cover preview-limit persistence.

## Remaining numeric parity work

The policy caps above remain explicit limitations. Expanding them should include
native integer/float conversion checks, normalization checks and appropriate
render validation rather than only widening spin boxes. Numeric editors preserve
six decimal places; arbitrary higher-precision imported values are still not
guaranteed to survive a GUI round trip unchanged. Advanced low-level inputs such
as detector-internal tuning still need a deliberate adapter/API design.
No render defaults were changed by this audit.

## Advanced controls reviewed after the flow/storage work (2026-09-12)

Numerical flow export and opt-in bounded frame storage are now implemented. The
remaining low-level options keep their previous documented limits:

- Per-level iteration schedules are now supported for both engines. The optional
  JSON arrays `searchvote_schedule` and `patchmatch_schedule` contain at most 32
  integers from 1 to 1000; empty arrays use their scalar controls. Order is
  coarse-to-fine, aligned at the finest level. When the usable depth is shorter,
  drop entries from the coarse end; when longer, repeat the first entry for the
  additional coarse levels. Thus `[12, 8, 4]` resolves to `[8, 4]` at depth two
  and `[12, 12, 8, 4]` at depth four. This applies after geometry/depth clamping,
  including Automatic. Quality selection clears schedules; presets/projects
  preserve them. Legacy receives real C-int arrays through a scoped runner
  override. FuouM receives a scalar for each backend call, resets for every frame,
  and uses the finest counts for its extra 3x3 pass. Legacy's DLL retains its
  native polishing policy. Output `iteration_schedule.json` records the resolved
  arrays; overridden scalar controls are omitted from effective provenance.
- Six-decimal editors remain deliberate; native float conversion cannot provide
  arbitrary decimal precision. Higher-precision UI round trips need a separate
  representation policy before widening the editors.
- Modulation is supported by both CUDA engines. The frontend accepts one optional
  uint8 grayscale target-sized map per image guide, or a numbered video map folder
  applied to a selected guide group/all guides. A map repeats across the group's
  channels; unselected channels receive 255. Native matching costs are multiplied
  by `value / 255`. Legacy image guides are ordered additional-first/primary-last;
  FuouM uses primary-first. Video maps follow actual target identities, including
  reverse/grouped passes and active sparse/mask guides. Original dimensions,
  grayscale type, consecutive frame identities and the 24-channel cap are checked.
  Processing resizing uses INTER_AREA; pyramid resizing remains engine-native.
  Output `modulation_manifest.json` records actual channel layouts, processed map
  hashes and synthesis targets. Blank/off settings preserve the existing path.
  Real CUDA probes verified white/black/128 and independent guide weighting in
  both engines; the Legacy CPU probe proved that CPU silently ignores maps.
  Enabled modulation therefore rejects Legacy CPU and Auto, even on a CUDA host.
  Arbitrary separate per-channel maps and float modulation are not exposed.
- FuouM's PyTorch synthesis backend uses a separate patch-search implementation
  with two refinement paths. Dedicated constant-style/cost probes now show that
  it fails retargeting, gray/black modulation and high-cost weighted voting while
  CUDA passes the same nine cases. It remains unexposed pending substantive
  repairs and follow-up correctness/performance validation. Additional source
  concerns and the reproducible gate are in TORCH_BACKEND_AUDIT.md.

## Dual-engine decisions (2026-09-12)

- Keep scalar iteration defaults and existing six-decimal policy caps; optional
  schedules now have the explicit mapping above. Do not advertise arbitrary-precision/API-complete parity.
  Guides remain normalized by style/key weight, not a second native style-weight
  parameter. Existing finite/range/channel validation applies to both adapters.
- FuouM exposes early-stop (integer 0–100,000), search-pruning (0–100,000), voting,
  SSD/NCC cost, and sparse-anchor weight (0–10,000). These are FuouM-only settings;
  they are filtered out of the original engine configuration. A fixed pruning
  threshold is not equivalent across SSD and NCC cost scales.
- FuouM Poisson luminance/chroma weights are separate 0–10,000 controls. They and
  maxiter are greyed out for seamless/disabled reconstruction. Its solver choice
  is separate from the legacy LSQR/LSMR selector; old presets migrate explicitly.
- Keep consecutive source frames and the existing grouped keyframe/range
  checklist. Gaps are rejected rather than silently treating a multi-frame jump
  as one adjacent flow step. Arbitrary/gapped file lists need an explicit timing
  and interpolation design before implementation, not an unchecked file picker.

Local references: [RunConfig](ezsynth/aux_classes.py),
[native wrapper and pyramid calculation](ezsynth/utils/_eb.py),
[frontend validation](reezsynth_config.py),
[image adapter](reezsynth_image.py), and
[blending validation](reezsynth_video_plan.py).
