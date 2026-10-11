# ComfyUI / Keyframes: current milestone

The first tab is a non-destructive foundation for the planned Keyframe
Generator. It has two modes: Generate New Keyframe and Modify Existing
Keyframe. It can read the current project's numbered source frame and any
matching drawing. A connection check reads the status of an explicitly entered
ComfyUI server on this PC. It does not start a server, load models, submit jobs
or touch a customized ComfyUI installation.

Candidates can be imported from PNG files for review. The source, drawing (in
Modify mode) and candidate must have the same original pixel dimensions. A
mismatch is rejected with the native-size requirement; no import path resizes
or flattens the image. The preview may be scaled for display only. Each imported
candidate receives a unique PNG and JSON record under the selected project's
`.reezsynth-candidates` directory. The record includes source/drawing hashes,
candidate hash, frame number, dimensions and mode. Its status is *unreviewed*.
The active numbered keyframe directory is not changed. This candidate directory
is ignored by Git and belongs to project data, so uninstall should preserve it
when the project is outside the application installation.

The local address accepts only an HTTP loopback origin and makes an asynchronous,
five-second, read-only `/system_stats` request with redirects disabled. No
network request occurs when the application opens.

Next milestones are selection and verification of an actual ComfyUI model/workflow adapter;
asynchronous submission, progress, cancellation and output retrieval; then
explicit approval, versioning and safe numbered-key assignment. Managed backend
installation and additional model families follow separate validation gates.
Existing render projects and presets retain their behavior.

The first inference adapter must be chosen against installed ComfyUI nodes and
models. Generate New remains a first-class mode, even if refinement is the first
inference workflow exercised. The requested Modify choices are stroke refinement,
detail/shading within selected regions, and a custom edit prompt with protected
regions. These intentions are stored with a candidate; they do not change
compositing until a matching inference workflow is implemented. In the current
preview, only the supplied masks and transparency policy change pixels.

Images exceeding Pillow's default pixel limit (89,478,485 pixels) are rejected
with an explanation, without resizing or changing existing project images.

## Protected candidate previews

The reusable protection module accepts native-size RGBA drawings/candidates and
explicit grayscale edit/protection masks. Any nonzero protection sample wins
over editing. Zero edit coverage is unchanged; soft edit coverage blends.
Protected RGBA samples remain exact, including hidden RGB under transparency.
An empty edit mask is a no-op. Masks with different dimensions are rejected.

Two explicit alpha policies are available to the engine: preserve the drawing's
alpha, or allow alpha changes within the selected edit region. Preservation also
keeps fully transparent drawing pixels unchanged and uses candidate opacity to
weight color changes. Editable alpha uses premultiplied-alpha interpolation in
encoded RGB; full edit coverage adopts candidate RGBA exactly. No inference
adapter may infer useful transparency from an opaque model output automatically.
Preserve-alpha cannot add visible strokes to transparent areas; that requires
explicit editable alpha. Soft EDIT coverage can change hidden RGB even where
the blended alpha rounds to zero; protected pixels remain exact in all cases.

Dark-stroke extraction is only a proposed mask for inspection, not automatic
semantic protection. It ignores fully transparent pixels and may omit white or
colored details; users must include those in their protection masks. The optional
square protection band expands by an explicit radius in original pixels.
The proposed dark-stroke threshold is 48 or less in each RGB channel and can
be supplied explicitly by a caller; it is not a universal contour detector.

Static QC reports changed pixels, alpha changes and protected mismatches. It
does not certify unprotected geometry, facial identity or artistic quality.
A native-canvas helper pads only right/bottom edges to a caller-verified VAE stride and
crops back to the original rectangle without resizing. This has synthetic tests;
it does not establish compatibility or quality for an actual inference workflow.

The Modify Existing Keyframe tab now offers the three requested edit intentions,
explicit grayscale PNG masks for editable and protected areas, a native-pixel
protection radius, and the two transparency policies. The dark-stroke proposal
is a preview only. Inspect or correct both masks in an image editor and select
them explicitly; colored and white details are not inferred as protected.

**Preview protected result** runs on a CPU worker from a snapshot of the five
selected files. It rejects wrong-size or non-grayscale masks. The View menu
offers source, drawing, raw candidate, enforced result, both masks, and alpha;
transparent images can be checked over checkerboard, light, or dark backgrounds.
Changing an input invalidates the previous preview and its Save action. Full
resolution pixels are kept for processing and storage. Views are bounded
thumbnails for inspection, so fine contour accuracy is checked by the exact
protected-pixel counter as well as by visual review; approval needs further QC.

**Save enforced candidate** creates a new unreviewed RGBA PNG and JSON record
in its own subdirectory under the project's `.reezsynth-candidates` folder,
with source/drawing/raw/mask
hashes, edit intention, alpha policy, radius and static QC. It checks the input
hashes again before saving. A saved candidate is not approved or assigned as a
numbered synthesis key. The tab still does not run ComfyUI inference.

## Durable inference job foundation

The standalone job-record module can freeze an intended ComfyUI prompt and input
snapshots in a project-local candidate subfolder. It creates a unique prompt ID,
client ID and ownership marker. The caller must exclusively claim its one
submission attempt before sending the stored request bytes. If the connection
fails or the response is lost, recovery reports an uncertain attempt and never
submits the same job again automatically. A receipt is accepted only when its
prompt ID matches the frozen request. Changed inputs or request bytes prevent a
claim. These rules have CPU-only thread and separate-process race tests, plus
failure and ownership-field checks.
The two symlink redirect tests skip on Windows accounts that cannot create
symlinks; other record and integrity tests still run.

This module is not connected to the tab or to any network transport yet. It does
not start generation, monitor progress, cancel jobs, or reserve a GPU. Those
pieces require their own validation before the UI can offer live inference.

A separate read-only status helper can query a single job by its ID on the
configured loopback server. It rejects redirects and oversized responses. A
missing job remains unresolved, because the backend may have restarted or
discarded history. Pending and running statuses identify the requested ID;
terminal status also has to match the recorded client and ownership details.
Its fake-server tests do not contact the user's ComfyUI. This helper is not yet
wired into the tab, and it does not submit work or release a GPU reservation.
The route shape was checked in the installed ComfyUI source; a completed response
from the user's running server still needs validation before live use.

The project-local record assumes other software cannot rewrite its manifest or
delete the submission marker. A local writer with that access can undermine the
record's hashes and one-attempt rule; this is the trust boundary for recovery.
The exclusive attempt marker has been tested with two separate processes.

ReEzSynth now has an in-process GPU work gate. A render batch owns one token
until its workers finish; Edge Preview uses the same gate until its worker exits.
Only the matching token can release it, so an old callback cannot free another
task's slot. The tab has no generation action yet, and this gate does not reserve
the user's external ComfyUI process or persist an uncertain job across restart.
When live generation is added, its admission check must also respect component
maintenance in progress; those setup workers use a separate existing guard.

## Experimental native-reference workflow planner

The offline Qwen Edit 2511 planner builds a frozen graph and PNG input snapshots
for Generate and the three Modify intentions. It does not submit, load a model,
upload, download, or offer a generation button. Its recipe uses the installed
Qwen Edit 2511 FP8-mixed model, Qwen 2.5 VL 7B encoder, and Qwen image VAE;
filenames and node compatibility do not prove model contents or output quality.
Full model identities and actual backend behavior still need checking before use.

Images and masks retain their native pixels. The planner explicitly pads only
right/bottom edges to a 16-pixel grid (8-pixel VAE stride times 2-pixel transformer
patches), and records crop-back dimensions. Inputs exceeding the experimental
16-megapixel limit, including padding, are rejected without resizing.
The text/vision node receives no VAE, so it cannot silently resize the spatial
reference; a separate native VAE latent is attached to both conditioning branches.
Vision encoding still preprocesses an internal reference to approximately
147,456 pixels total (384 squared), keeping its aspect ratio, and planning
requires an explicit acknowledgement of that behavior. On 2026-10-10 the owner
accepted this preprocessing for the experiment, while keeping spatial references,
masks, working images, and output native. This is not a claim that every representation
inside an AI model has the dimensions of the source image.

Modify requires an explicit opaque background for the model intermediate,
an edit mask, protection mask/radius, and Preserve drawing alpha. Original RGBA
and masks remain separate snapshots. Protected and fully transparent pixels are
excluded from the sampler mask; soft edit coverage is retained. The sampler
internally maps this mask to its latent grid, so it cannot guarantee exact
protected pixels. Empty effective edit regions are rejected as unnecessary work.
Exact pixel enforcement belongs to the final compositing stage. This RGB model
cannot provide editable alpha or grow strokes outside existing alpha coverage.
The uploaded mask is an RGB PNG with identical channels, read through the red
channel, to avoid a grayscale decoder colorspace conversion. In Modify, the
source frame is recorded for provenance; only the drawing on its explicit
background is supplied to the model. Source-photo conditioning is not yet added.
A CPU check through the installed LoadImageMask node recovered all 256 coverage
values exactly from a 48x32 RGB PNG, including its non-32-aligned width.

**Do not treat its RGB output as a finished transparent candidate.** Simply
reattaching original alpha to an image generated against a background can create
matte-colored halos. A CPU-only reconstruction helper is now implemented below;
its real-model visual tests and integration must be completed before connecting
this recipe to candidate storage. Generate
uses an opaque source and full denoise; it does not restore photo pixels or
inherit Modify masks. Style references and ControlNet are not implemented here.

CPU checks against the installed nodes verified both graphs' inputs, link types,
and selected model-menu entries. An actual CPU-only Qwen VAE encode/decode took a
129x81 fixture padded to 144x96 through a 1x16x1x12x18 latent and back to 144x96;
the standard decode node flattens the singleton video dimension. Crop-back gives
129x81. The reference node retained the same latent tensor. This verifies shape
handling, not lossless VAE pixels, diffusion behavior, or artistic quality. No
diffusion/text model or live inference was run; no backend was launched.

Recipe references: [ComfyUI's Qwen Edit 2511 guide](https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit-2511)
and [official workflow template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_edit_2511.json).
Native-reference attachment, masking, and omission of the official workflow's
resolution bucketing are experimental departures requiring
controlled quality comparison; the reference template alone does not validate them.
The offline plan can now be bound once per project to a durable job record. A
claim file is created exclusively before preparing the job, so two controllers
cannot freeze the same plan simultaneously or reuse its upload names after an
interrupted preparation. A new intentional attempt requires a newly planned
workflow with fresh upload names. Upload receipts, backend identity, and
output/alpha validation must be completed before live submission. Reusing an
offline plan is not a supported retry mechanism.

The worker-side transport now uploads only frozen input PNGs over loopback,
refuses redirects, verifies that ComfyUI kept the expected input filename, and
reads the stored bytes back to compare against the frozen SHA-256. It checks
all inputs again immediately before claiming the single prompt submission.
If the prompt response is lost, the job remains attempted with no receipt and
must be reconciled; it is not submitted again. A cross-project filename clash
with different bytes produces a renamed upload and stops before submission.
The fake-server tests include both the one-image Generate and two-image Modify
paths, including recovery after an upload receipt is missing. A compatible
existing upload can be checked without re-uploading; if a receipt remains but
the server-side input has disappeared, create a new plan/job. These safeguards do not constitute
live model or visual-quality validation, and the transport is not yet wired to
the tab.

A read-only owned-output helper now requests only the frozen job's ID, verifies
terminal ownership, and accepts exactly one PNG from the frozen SaveImage node.
If the submission response was lost, an attempted job can still be read once
the backend reports completed status with the exact frozen ownership markers.
This does not create a receipt or allow a second submission. A missing or pending
server record remains uncertain and cannot be used as a result.
It requires the planned padded RGB dimensions, then removes only the recorded
right and bottom padding to return native pixels. A mismatched owner, file name,
image count, format, or size is rejected. The output remains an RGB intermediate;
it is not saved as an approved keyframe or inserted into candidate storage.

The owned candidate worker can now reconstruct an unreviewed RGBA preview from
the completed job and its frozen inputs. Saving that preview creates a new
candidate folder with the exact downloaded RGB PNG, native enforced RGBA PNG,
provenance, and QC record. The completion record is written last. Older job
records do not include an intended frame number, so these candidates remain
unassigned until a separate explicit frame choice and approval. This does not
change any numbered synthesis keyframe.
The tab can load an existing completed job folder from the selected project in
a background worker, show its raw and enforced previews, and save that unreviewed
candidate. Preview requires the same local ComfyUI server to remain reachable
for read-only job status and output requests. It does not start generation or
select a target frame for older jobs.

## Fixed-alpha reconstruction of model intermediates

The standalone matte helper uses the exact quantized opaque input as its baseline.
It converts the generated RGB difference into a foreground-color change using
the original alpha, clips colors to byte range, then applies edit coverage and
exact protection through the existing compositor. An unchanged model output
therefore returns the original RGBA exactly, including faint antialiased samples
and hidden RGB. Planner input preparation uses the same matte arithmetic.

Alpha remains fixed. Protected pixels and pixels outside edit coverage remain
byte-exact. Clipped-reconstruction pixels and eligible translucent pixels are
reported: faint samples amplify RGB changes, and some model edits cannot be
represented using the original alpha. Clipping is counted before the final soft
blend, not as a count of saturated final pixels. This assumes the model result
uses the recorded background; it cannot infer a new foreground mask, remove all
model-induced edge artifacts, or certify quality on other backgrounds.

CPU tests cover identity across all 256 alpha values and three backgrounds,
partial edits, clipping, protected/hidden colors, PNG round trips, and the actual
planner's saved input. This helper has no UI, network, output publication, or
approval action. The caller must supply the original snapshots, the effective
protection band, and a validated native crop of the owned job's output. Connecting
those boundaries and evaluating real generated artwork remain required.
