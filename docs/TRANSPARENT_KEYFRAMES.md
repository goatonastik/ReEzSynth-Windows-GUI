# Transparent keyframes: Legacy implementation and compatibility limits

## Contract

A video job uses BGRA style/output synthesis if **any selected keyframe has at
least one alpha value below the opaque maximum**, detected at original resolution
before resizing. Source-frame alpha alone does not select this path. RGB and
entirely opaque RGBA keyframes keep the pre-existing three-channel behavior.
In mixed groups, RGB/opaque styles acquire alpha 255; source guides remain BGR.

Transparent styles must be 8-bit RGBA PNGs. Higher-bit-depth transparent input is
rejected explicitly, not truncated to fit the byte-based native interface.
Existing grayscale/RGB normalization is unchanged.

The loader retains straight BGRA bytes, including RGB under alpha zero. Resize
uses the existing INTER_AREA operation on all four independent channels, without
premultiplication, flattening, hidden-color cleanup, or implicit masking. Disk
sequences retain four channels and frame identities using their existing NPY
storage. PNG encoding writes all four channels.

## Native layout and execution

The Legacy native API already separates `numStyleChannels` and
`numGuideChannels`. No ABI or native implementation change is needed:

- Style and synthesized output: four BGRA channels, default native equal channel
  weights (1/4 per channel).
- Standard guides: one edge + three source + three position + three warped-style
  **RGB** channels. Existing group weights/channel normalization remain intact.
- Explicit masks, custom edges and modulation remain explicit, existing features.
  Style alpha does not become one of these guides.

RGBA pass starts run native synthesis using identity-target guides instead of
copying their style. Single-frame jobs take the same native route without loading
an optical-flow model. Propagation still uses the original full-BGRA style and
warps the synthesized previous result; only its RGB goes into the warp guide.
RGB jobs retain the old keyframe-copy shortcut.

Output checks require the source's exact spatial dimensions and the explicit
job output channel count (three or four), rather than requiring source and
output channel counts to be equal. Image-synthesis jobs and preview PNG transport
also retain meaningful style alpha.

## Reconstruction

RGB histogram/Lab/Poisson processing receives only the color channels. Alpha is
carried from the synthesized forward/backward result selected by the existing
error mask and reattached after color reconstruction. It is not a Lab component,
histogram-normalized value or implicit mask. Identical RGBA passes bypass needless
reconstruction; identical color avoids histogram division by zero for flat styles.
The existing RGB-only reconstruction branch is unchanged.

This is an explicit local opacity-carrying policy, **not a claim that the desktop
beta's undocumented multi-keyframe reconstruction has been replicated**. Its
multi-keyframe reconstruction was not established by the six reference cases.

## FuouM

Transparent styles are refused with an actionable Legacy compatibility message
before activating FuouM or loading flow models. Opaque styles continue normally.

FuouM's low-level synthesis engine uses a variable style-channel count; the native
API itself is not the reason for refusing support. The pinned full pipeline still
copies starting keys, includes the entire style in warp guides, reads/writes via
RGB conversions (`ezsynth/utils/io_utils.py`), and its reconstruction plus this
frontend's `reezsynth_fuoum_pipeline.py` histogram path produce RGB. Supporting and
certifying both CUDA and alternate tensor synthesis through that pipeline requires
additional adapter/pipeline changes. A loader-only BGRA change would silently lose
alpha again. No FuouM parity or mask-semantics change is included here.

## Windows beta differential

Reference assets and the previous investigation/report are local diagnostic
evidence under `diagnostic_outputs/beta_alpha_847bae6e2489`. That directory is
gitignored: the Windows-beta PNGs, the `.ebs` project, executable identity and
analysis outputs are deliberately **not committed repository assets**. A reviewer
must retain or regenerate them locally to reproduce this differential; neither
the beta executable nor its rendered output is versioned here.

`diagnose_reezsynth_alpha.py` runs six actual frontend Legacy one-frame jobs on
CPU with one OpenMP thread, patch 3, one pyramid level, four search/vote and
PatchMatch iterations, zero uniformity, source-guide weight 6 and other guide
weights zero. It writes a new `frontend_rgba` directory and refuses to overwrite
an existing result directory. It does not invoke flow or launch the beta GUI.

Measured keyframe differences against the preserved beta PNGs (8-bit units):

| Case | Output channels | RGB MAE | Alpha MAE | Gray-127 composite MAE |
|---|---:|---:|---:|---:|
| RGB | 3 | 11.951070 | 0 | 11.951070 |
| Opaque RGBA | 3 | 11.955973 | 0 | 11.955973 |
| Constant alpha 0 | 4 | 0 | 0 | 0 |
| Constant alpha 128 | 4 | 0 | 0 | 0 |
| Hidden black | 4 | 37.834290 | 84.761902 | 10.496988 |
| Hidden white | 4 | 74.200277 | 101.526672 | 13.138043 |

Constant cases match all 16,384 pixels, including hidden RGB. The table's RGB row
is deliberately **not** an optimizer baseline: production RGB uses its historical
copy shortcut, while the beta synthesizes the nonconstant key. Its 11.951070 RGB
MAE therefore measures policy-versus-synthesis, not just solver divergence.

A separate direct Legacy RGB identity-synthesis diagnostic bypassed that shortcut
without changing production RGB behavior. It used the same synthetic RGB style,
CPU/one-thread, identity guides and synthesis parameters: beta RGB MAE was
**14.855265**, maximum **109**, with **7,362 / 16,384** equal pixels; versus its
input style it measured RGB MAE **24.233948**. This is the appropriate cheap
Legacy-synthesis reference for interpreting the transparent nonconstant rows,
although it is still not a claim of beta/DLL algorithmic parity.

Both nonconstant transparent outputs differ from their input: they were actually
synthesized. Changing only hidden input RGB changes output alpha (MAE 7.271606)
and visible gray composite (MAE 1.682461), rather than being discarded as a mask.
The full report preserves raw RGB, alpha, maximum differences and pixel equality,
not just visible-composite metrics.

**The nonconstant differences are substantial, not rounding noise.** This repair
provides four-channel synthesis and prevents frontend alpha loss; it does not
reproduce the beta's exact filtering, solver/guide policy, or propagation. A beta
resized-resolution differential and a real GPU propagation comparison remain
unmeasured. MP4 export is not an alpha-preserving output format; PNGs are the
alpha-preserving output addressed here.

## Regression coverage and validation status

`test_reezsynth_alpha.py` covers RGB/opaque/transparent/partial/hostile hidden-color
inputs; Original and resized processing; detection before resize rounding; memory
and disk sequences; mixed grouped modes; exact-key synthesis versus copy; explicit
output channels/dimensions; grayscale image guides; FuouM refusal; native CPU
alpha 0/128/255; RGB/Lab reconstruction plus constant-style preservation; and the
live four-channel propagation operation (`/255`, `Warp.run_warping`/`cv2.remap`,
then `cv2.resize`). The latter asserts partial alpha, hostile hidden RGB, channel
count and resizing, and gives an explicit failure when the low-level warp returns
`None`.

Recorded pre-change relevant RGB baseline: 70 tests passed in 8.526 seconds.
Current file-independent subset: 5 tests passed in 0.861 seconds, including the
native four-channel test, reconstruction checks, exhaustive small RGBA sequence
boundaries/work counts, and existing RGB sequence boundaries. The six real
frontend beta differential jobs completed successfully.

Final validation was completed by the user locally with
`E:\miniconda3\envs\reezsynth\python.exe`, after sandbox temporary-directory
permissions prevented a usable agent-run full suite. The user supplied these
successful results:

- Focused RGBA suite: **14 tests passed in 4.418 seconds**.
- Existing render-adapter and image modules: **31 tests passed in 6.296 seconds**.
- Complete maintained suite: **357 tests passed in 62.411 seconds**. This includes
  grouped rendering, memory/disk sequences, iteration schedules and engine tests;
  those modules were split off the user's first command, but were covered here.
- `git diff --check`: no whitespace errors; only LF-to-CRLF normalization warnings.

The earlier sandbox attempts are not counted as successful validation. Qt font/
offscreen-plugin, optional CuPy fallback and deprecated Torch API warnings did not
fail the local suite. These test results do not remove the beta numerical and GPU
comparison limitations described above. Reproduction commands:

```
python -B -m unittest test_reezsynth_alpha
python -B -m unittest test_reezsynth_render_adapter test_reezsynth_image test_reezsynth_grouped test_reezsynth_sequence test_reezsynth_iterations test_reezsynth_engines
python -B run_maintained_tests.py
git diff --check
```

The separate uncommitted persistence/state repair and `CLAUDE_HANDOFF.md` are not
part of this work. Nothing is staged or committed.
