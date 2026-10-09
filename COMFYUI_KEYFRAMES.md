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

Next milestones are deterministic protection/edit masks and geometry QC;
selection and verification of one actual ComfyUI model/workflow adapter;
asynchronous submission, progress, cancellation and output retrieval; then
explicit approval, versioning and safe numbered-key assignment. Managed backend
installation and additional model families follow separate validation gates.
Existing render projects and presets retain their behavior.

The first inference adapter must be chosen against installed ComfyUI nodes and
models. The owner's transparent line-art refinement needs an agreed editable
region/default effect before a workflow can claim to preserve its alpha and
color accents. Generate New remains a first-class mode, even if refinement is
the first inference workflow exercised. The requested Modify choices are stroke
refinement, detail/shading within selected regions, and a custom edit prompt
with protected regions. These remain planned until inference is implemented.

Images exceeding Pillow's default pixel limit (89,478,485 pixels) are rejected
with an explanation, without resizing or changing existing project images.
