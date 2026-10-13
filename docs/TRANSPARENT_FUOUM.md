# Transparent FuouM keyframes

Transparent 8-bit RGBA styles now work in FuouM video and Image Synthesis.
No source-image flattening is needed to render a transparent keyframe. RGB-only
jobs retain their existing path; opaque RGBA styles retain RGB normalization.
A group containing both RGB and transparent styles promotes its styles/outputs
to RGBA. Source frames, flow inputs and correspondence guides remain RGB.

## Mask output toggle

Enable Masks, then choose **Transparent mask output [FuouM only]** in Rendering:

- **Transparent artwork** (default): the mask clips artwork color and opacity
  together. Black makes the artwork transparent; white retains its opacity.
- **Composite onto source**: the masked artwork is composited over its opaque
  source frame. Output remains a four-channel PNG with alpha 255.

The choice is saved in rendering presets and GUI projects. It is enabled only
for FuouM video with masks enabled and has no effect on RGB-only renders or
Image Synthesis. Feathering changes mask coverage in either mode. Pre-mask is
still a separate operation before synthesis: it can alter the synthesized
appearance/opacity in addition to the final mask operation.

Without masks, transparent video outputs stay transparent. Unmasked keyframes
at original processing dimensions retain their exact input RGBA pixels, including
antialiased edges, low-alpha pixels, color accents and invisible RGB. If processing
dimensions change, resized keys use alpha-aware filtering rather than an exact
original-pixel guarantee. No transparency is inferred from opaque black artwork.

## Alpha handling

The frontend uses associated (premultiplied) color plus alpha for native
four-channel synthesis. Invisible RGB cannot contaminate filtering or generated
strokes. Resizing works in associated color. Outputs are converted back to
ordinary straight-alpha PNGs; generated pixels with zero alpha have RGB zero.
Original unmasked keyframes are kept separately for exact output.

Opacity travels through synthesis and flow warping. It is not treated as a Lab
color component, histogram matched or Poisson reconstructed. Grouped blending
selects alpha from the same forward/backward pass as its error-selected color.
Color reconstruction sees RGB only, including seamless cloning. Associated
color is bounded by opacity when converting to straight output.

The byte-based synthesis representation can quantize colors at very low alpha;
it cannot losslessly encode arbitrary straight RGB there. Exact original
keyframe restoration does not imply exact generated-frame geometry, stroke
width or color. Those remain synthesis-quality questions, not guaranteed by
alpha support. Transparent 16-bit styles are rejected rather than truncated.

## Preview, output and compatibility

Live previews show alpha on a checkerboard and use alpha-aware thumbnail resizing.
Transparent video jobs write `alpha_manifest.json` describing representation,
keyframe policy, alpha selection and mask mode. The ordinary queue, completion
markers, progress, cancellation, recovery and disk-backed storage remain in use.
No engine checkout, native library, dependency or model is replaced.

MP4 cannot retain alpha. A transparent FuouM video job with MP4 enabled is rejected
unless masks explicitly use Composite onto source, which makes every output
opaque. Use PNG sequences for transparent outputs. Native FuouM YAML export
rejects transparent styles: the pinned upstream CLI discards their alpha and does
not include this frontend representation/reconstruction path. GUI projects and
presets retain the full settings.

Legacy rendering and its existing source-over mask behavior are unchanged.
This feature does not implement the planned AI Keyframe Generator.

The maintained regression suite includes transparent FuouM coverage alongside
existing Legacy tests; the latest result is recorded in WORK_REMAINING.md.
No commit, push, runtime installation or native engine-source edit was performed.

## Validation and remaining acceptance

`test_reezsynth_fuoum_alpha.py` covers associated/straight color, hidden RGB,
black strokes and white/red accents, opacity, resizing, mask clipping/source
compositing, alpha selection, RGB-only reconstruction inputs, GUI persistence,
exact output pixels, disk cleanup, inactive pre-mask and transparent MP4 rejection.
Adapter regressions also check alpha-aware processing-size reduction, unchanged
input bytes, resized-keyframe metadata and rejection of nonopaque 16-bit keys
without publishing a completion marker.
Existing Legacy alpha tests remain in the maintained suite.

`diagnose_reezsynth_fuoum_alpha.py` passed 16 real backend probes (CUDA and
experimental torch; weighted/plain voting; SSD/NCC; line art and half-alpha
styles; final 3x3 pass). Retained diagnostic:
`diagnostic_outputs/fuoum_alpha_probe_20260926_143204_459903`.

`diagnose_reezsynth_fuoum_alpha_video.py` passed 16 small real job cases at 128x128:
LSQR/LSMR/CG/AMG/seamless/disabled reconstruction, forward/reverse mode,
bidirectional flow with disk-backed storage, both mask modes, pre-mask, mixed
RGB/RGBA keys, experimental torch, single-frame and Image Synthesis. Keyframes
were compared pixel-for-pixel and temporary storage/cache cleanup was checked.
Retained diagnostic: `diagnostic_outputs/fuoum_alpha_video_20260926_143853_919183`.

A repeat of all 16 job cases additionally verified SHA-256 hashes of every input
frame, mask and keyframe before and after rendering. Retained diagnostic:
`diagnostic_outputs/fuoum_alpha_video_20260926_155225_700950`.
The offscreen preview sheet demonstrates the checkerboard and compositing, but
caption glyphs were not readable in that capture; normal interactive Windows
preview appearance has not yet been accepted.
Follow-up font diagnostics mapped every letter to the same placeholder glyph
with Qt's offscreen backend (including outside the sandbox). Qt's normal Windows
backend resolved distinct Segoe UI glyphs correctly without opening a window.
This isolates the observed caption limitation to the offscreen font environment;
it is not evidence of a defect in the preview caption code.

Additional regressions verify checkerboard pixels and opaque preview coverage,
native export rejection for transparent keys under both selected mask policies,
and continued native export compatibility for fully opaque RGBA keys.

Further regressions exercise alpha-aware live-thumbnail publication without
input mutation or leftover partial PNGs. Opaque-composite MP4 adapter tests verify
that completion is published only after encoding succeeds, and encoder failure
leaves no completion marker or disk-backed frame storage. A real FFmpeg encode
and OpenCV decode check confirmed three 128x128 opaque-composite frames at 24 FPS;
retained artifact: `diagnostic_outputs/fuoum_alpha_mp4_acceptance_20260926/render.mp4`.
That check does not certify transparent video (MP4 remains intentionally opaque).

These are contract checks, not production-resolution visual certification.
User-supplied footage checks on 2026-09-27 completed 13 reduced-resolution
propagated frames across s1/s6/s9 and three exact native-resolution single-key
payload checks. Input hashes and temporary-storage cleanup passed. Intermediate
hand distortion in s1/s9 means successful completion is not visual acceptance.
See FUOUM_FOOTAGE_ACCEPTANCE.md for ranges, retained outputs and observations.
The same 13 propagated frames subsequently completed at original resolutions;
all six endpoint keys matched exactly, selected input hashes were unchanged,
and temporary storage was cleaned. Moving-hand irregularity in s1/s9 remained
visible in review sheets. This does not constitute owner quality acceptance.
Review the owner's actual line-art footage, subtle low-alpha/color behavior,
long-running stability and normal interactive Windows use before treating the
feature as fully production-accepted. Torch remains experimental.

Native masked follow-up on 2026-09-28 rendered s9 frames 26–29 at 1536×1536 with
transparent keys and `s9m-medium`. Both transparent-artwork and source-composite
policies completed. Alpha spanned 0–255; source-composite output matched source
exactly in the conservative region outside the feathered mask. Transparent output
composited over source closely matched direct source-composite output (mean frame
MAE 0.116/255; maximum frame MAE 0.231/255; localized maximum 104/255).
Intermediate moving-hand irregularity remained under both policies and multiple
flow/edge choices, so the test did not identify alpha handling as its cause.
Retained evidence: `diagnostic_outputs/s9_feature_acceptance_20260928_0001`.
