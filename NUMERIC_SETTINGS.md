# Numeric settings audit

Reviewed against the live local engine on 2026-09-11. This records the current
frontend domain, not a claim that every value accepted by the upstream Python API
has been exposed or tested with the native renderer.

| Control | Frontend values | Engine behavior / remaining limitation |
| --- | --- | --- |
| Diversity / uniformity | 0–100,000; default 3,500 | RunConfig describes 500–15,000 as a reasonable range, not hard limits. The frontend maximum is a policy cap. Passed to a native float. |
| Patch size | Odd integers 3–99; Standard default 7 | Wrapper requires odd values at least 3. Its pyramid calculation additionally requires every processed style/target dimension to be at least `2 * patchsize + 1`. The 99 maximum is a frontend cap. |
| Pyramid levels | Automatic (-1), or 1–32; Standard default 6 | Wrapper derives the usable maximum from image and patch dimensions and clamps explicit requests to it. Automatic selects that maximum. Requests yielding no usable level are now rejected before engine construction. |
| Search/vote iterations | 1–1,000; Standard default 12 | Wrapper repeats the scalar at every pyramid level in a C-int array. The 1,000 cap is frontend policy. Zero/negative/per-level-array workflows are not exposed. |
| Patch-match iterations | 1–1,000; Standard default 6 | Same scalar-to-per-level behavior and frontend policy cap. |
| Video edge/image/position/warp/mask-guide weights | 0–10,000 | Wrapper converts guide weights to per-channel native floats. Frontend caps remain a policy limit; editors preserve six decimal places. |
| Video key / image style weight | 0.001–10,000 | Frontend ratio control: guide weights are divided by this value; native style weight stays fixed. This is not a direct upstream RunConfig key weight. |
| Image primary/additional guide weights | 0–10,000 | Six-decimal editors and style-ratio normalization. Image validation checks the 24-channel native guide limit separately. |
| Mask feather | 0 or odd integers 1–999 | Zero disables feathering; nonzero values are Gaussian kernel sizes. The maximum is frontend policy. |
| LSMR iteration limit | Automatic (UI 0, saved null), or 1–2,147,483,647 | Passed as Poisson maxiter; applies to LSMR, not LSQR. GPU reconstruction has its separate solver path. |
| Custom processing size | Integer width/height 128–16,384 | Frontend bounds; not universal native limits. Multi-frame RAFT also requires at least 128 pixels per dimension. Original-size still images may be smaller if the patch constraint is satisfied. |
| Parallel limit | 0–64; default 2 when enabled | Application setting: zero means all queued jobs. Parallel rendering remains off by default. |
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
as per-level arrays and stop thresholds need a deliberate adapter/API design.
No render defaults were changed by this audit.

Local references: [RunConfig](ezsynth/aux_classes.py),
[native wrapper and pyramid calculation](ezsynth/utils/_eb.py),
[frontend validation](reezsynth_config.py),
[image adapter](reezsynth_image.py), and
[blending validation](reezsynth_video_plan.py).
