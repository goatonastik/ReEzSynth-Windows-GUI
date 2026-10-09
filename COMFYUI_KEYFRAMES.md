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
