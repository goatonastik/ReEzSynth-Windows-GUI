# Transparent FuouM footage checks — 2026-09-27

User-supplied inputs: `diagnostic_outputs/test-temp/test-s1`, `test-s6`,
and `test-s9`. Inputs were read only; results are in separate diagnostic folders.
No application code, presets, original frames or original drawings were changed.

## Input inventory

| Set | Source range/count | Dimensions | Transparent keys |
| --- | --- | --- | --- |
| s1 | 0–140 / 141 | 1440×1440 | 49, 73, 81, 99, 112, 121, 126 |
| s6 | 50–117 / 68 | 1900×1060 | 29, 53, 59, 61, 63, 66, 75, 78, 98 |
| s9 | 0–72 / 73 | 1536×1536 | 11, 20, 26, 29, 32, 54 |

All inspected keys are 8-bit RGBA with alpha ranging from 0 to 255 and
dimensions matching their respective sources. s6 key 29 has no corresponding
source frame in the supplied folder; it was excluded, not renamed or remapped.
s9 source images also have alpha; the existing renderer reads source RGB for
guidance. Source alpha preservation is not part of this feature.
These supplied drawings are filled colored artwork, not the owner's proposed
black-line-only artwork with sparse color accents.

## Completed checks

FuouM Standard, disk-backed storage, maximum width 512, no masks:

- s1: 121–126, 6 frames.
- s6: 59–61, 3 frames.
- s9: 26–29, 4 frames.

All 13 outputs were valid 8-bit RGBA PNGs. Each job published its completion
marker. SHA-256 checks confirmed every selected source/key input was unchanged.
No temporary frame-storage or render-cache directories remained in job outputs.
Job configurations, logs and summaries are retained in
`diagnostic_outputs/fuoum_alpha_footage_20260927_005838_756967`.

Native-resolution single-key checks then confirmed pixel-for-pixel RGBA equality
for s1 key 121, s6 key 59 and s9 key 26, including invisible RGB. These are
payload-preservation checks, not full-resolution propagation tests.
Retained results:
`diagnostic_outputs/fuoum_alpha_footage_20260927_010002_009704`.

## Visual observations, not production acceptance

Contact sheets show sources, transparent artwork over checkerboard, and a
review-only source composite. The third row is a visual aid, not a render job
using the mask-output toggle.

- s1 retains the cartoon appearance and transparent background in this short
  interval, but intermediate moving hands/food have visibly irregular edges and
  distortion.
- s6 looks coherent at contact-sheet scale across the three inspected frames.
- s9 retains the cartoon figure and transparency, but intermediate glove/hand
  contours are irregular compared with the endpoint drawings.

These observations do not isolate an alpha-specific cause. Rescaling, flow,
synthesis and source motion can all affect interpolation. No repair was made
based solely on these observations.

Contact sheets are `contact_sheet.jpg` in each set's reduced-resolution output
folder. Owner review is required before calling the visual result acceptable.
Long-running stability, full-resolution propagated footage, the supplied mask
variants, and sparse line-art-specific quality remain unaccepted.

## Original-resolution follow-up

The same intervals were subsequently rendered with no resolution cap, using
the same Standard synthesis settings and no masks:

| Set | Range | Output dimensions | Count |
| --- | --- | --- | --- |
| s1 | 121–126 | 1440×1440 RGBA | 6 |
| s6 | 59–61 | 1900×1060 RGBA | 3 |
| s9 | 26–29 | 1536×1536 RGBA | 4 |

All 13 full-resolution propagated outputs passed shape/type validation. Both
endpoint keyframes in each interval matched their original RGBA drawings
pixel-for-pixel. All selected input hashes remained unchanged; completion
markers and temporary-storage cleanup passed.
Retained jobs, PNGs, logs, contact sheets and summary:
`diagnostic_outputs/fuoum_alpha_footage_20260927_120601_459005`.

Review of the contact sheets still shows intermediate moving-hand irregularity
in s1 and s9. It was therefore not solely a consequence of the 512-pixel cap.
s6 remains visually coherent at sheet scale. The sheets are reduced-size review
layouts; the numbered PNG outputs retain the full dimensions listed above.
This check establishes full-resolution execution and payload preservation,
not owner approval of interpolation quality or long-running stability.

Reproducible opt-in diagnostic: `diagnose_reezsynth_fuoum_alpha_footage.py`.
Default invocation only inspects inputs; `--run` renders the shortest matched
key-to-key interval per set at width 512; `--native-keys` tests original-size
single-key payloads. It never overwrites existing output folders.
`--full-resolution` renders the same short intervals at original dimensions and
checks exact endpoint pixels as well as output sizes.

## Native masked feature matrix — 2026-09-28

A focused production follow-up rendered s9 frames 26–29 at 1536×1536 using
transparent keys 26 and 29, `s9m-medium`, Standard quality, 9-pixel feathering,
mask-guide weight 2 and disk-backed storage. Seven jobs covered source-composite
and transparent-artwork mask output, empty/warm/forced precomputation, PST
defaults and changed tuning, and RAFT versus NeuFlow.

Every job produced four valid RGBA PNGs and a completion marker. Selected source,
key and mask hashes were unchanged; temporary storage was removed. Forced
recomputation did not modify the shared cache. Endpoint keys matched across
warm/reused/forced runs; generated-frame RGB had small CUDA launch variation
(MAE 0.152–0.171/255; localized maximum 107/255) while alpha was unchanged. The
initial byte-equality assertion stopped on frame 27; the resumed diagnostic used
a documented mean-difference criterion after the variation was inspected.

Source-composite pixels matched source exactly in the conservative region outside
the feathered mask on every frame. Transparent artwork composited over source
closely matched direct source-composite output (mean frame MAE 0.116/255; maximum
frame MAE 0.231/255; localized maximum 104/255). PST tuning and NeuFlow both
visibly changed generated hand/arm boundaries, but this interval does not identify
a general quality winner.
Moving-hand irregularity remains on frames 27–28 and is visible under multiple
output/flow/detector choices; transparency is therefore not isolated as its cause.

Retained jobs, logs, metrics, review notes and before/after sheets:
`diagnostic_outputs/s9_feature_acceptance_20260928_0001`.
