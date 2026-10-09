# AI-assisted Keyframe Generator

Status: user-requested feature. The first UI/connection/candidate-intake slice
is implemented locally on 2026-10-08; inference, approval, key assignment,
protected-contour processing, backend installation and model downloads are not.
The standalone deterministic protection/compositing and native-padding module
was added on 2026-10-09; UI mask controls and inference integration are pending.
The specification was recorded 2026-09-26 from the user's supplied cross-chat
discussion. See COMFYUI_KEYFRAMES.md for the current implementation boundary.

## Purpose and governing requirements

Integrate AI-assisted keyframe editing into the existing ReEzSynth desktop app,
without making normal users operate ComfyUI or exchange files manually.

Priority order:

1. Geometry and occlusion accuracy.
2. Style consistency across approved keyframes.
3. Controlled modification of hand-drawn strokes and appearance.
4. Aesthetic improvement.

In Modify Existing Keyframe mode, the existing drawing is the geometry authority.
In Generate New Keyframe mode, the source frame is the structural reference;
there is no pre-existing drawing to restore. Preserve original canvas
dimensions, aspect ratio, framing, and placement. Resizing an AI result alone
does not correct local geometric drift.

### Product purpose versus the owner's implementation priority

The broader product purpose is **Generate New Keyframe**: create a complete styled
keyframe from a source frame, using structural conditioning and style references.
The owner expects this to be the common use for other users; that expectation
is not yet validated user research. This is a required first-class mode, not an
optional afterthought or merely a way to prepare inputs for drawing refinement.
Results still require geometry QC and may need manual correction.

**Modify Existing Keyframe** is the owner's personal priority: refine existing
drawings while protecting their geometry, using masks, structural conditioning,
and low denoise where supported. It is a specialized subset to develop in depth
for the owner, not the defining purpose of the whole generator.

Implementation may exercise this refinement path first to meet the owner's
immediate needs, but architecture, naming, and shared UI must support both modes
from the outset. Delivery order does not imply product importance.

### Specialized refinement profile: transparent line art

On 2026-10-08 the owner requested all three Modify edit choices: refine existing
strokes while preserving sparse color accents; add detail or shading only inside
selected regions; and a custom edit prompt with explicitly protected regions.
These are planned choices, not implemented inference controls. They share native
canvas preservation, explicit protection/edit masks, and candidate review.

The owner clarified their personal input on 2026-09-26: simple black line drawings
on a transparent background, sometimes with small intentional color accents,
such as white eyes/teeth or dark red inside the mouth.

Treat this as a specialized profile within Modify Existing Keyframe, not a
restriction on that mode. General refinement should also accommodate other
artwork, such as opaque drawings, colored illustrations, or painted keyframes,
using appropriate masks and preservation policies. The conceptual hierarchy is
the general Keyframe Generator, its create/refine modes, and specialized profiles
within refinement. Refinement is not literally dependent on first generating a
new keyframe; users may supply their own artwork directly.

For the transparent line-art profile:

- Preserve black strokes, antialiased edges, transparency, and intentional color
  accents according to explicitly selected protection/edit masks.
- Do not assume every non-black pixel is expendable, or mistake transparent
  black RGB values for visible black linework. Mask extraction must account for
  alpha as well as color.
- Distinguish unchanged transparent regions from regions where the user permits
  new strokes, fills, or shading. Do not automatically fill the canvas, flatten
  onto an opaque background, or convert the drawing into a painted image.
- Let the user choose which accents/regions are protected versus editable. Define
  desired changes before selecting model/workflow settings; the exact default
  refinement effect is still to be agreed with the owner.
- Preview on a checkerboard and selectable light/dark backgrounds, with an
  alpha-only view. Any opaque image used internally for inference is an explicit
  intermediate; final alpha reconstruction/compositing belongs to the engine.
- Test partially transparent stroke edges, white details, red accents, hidden
  RGB beneath zero alpha, and PNG round trips. Exact preservation guarantees
  apply to protected RGBA samples, not only their appearance on one background.

This profile defines generator requirements only. It does not authorize the
separate transparent-keyframe implementation in the FuouM synthesis engine.

Both modes share semantic controls, model-family adapters, style references,
backend lifecycle, candidate review, and QC. ControlNet-style guidance uses the
source frame's structure for new generation and the drawing's structure for
refinement. Source appearance/depth can supplement drawing guidance without
overriding its authority. Protected original-drawing pixel restoration belongs
to refinement; applying it indiscriminately to new generation would preserve
photographic pixels rather than generate a fully styled keyframe.

## Product placement and current-project fit

- Add a **Keyframe Generator** tab to the existing application.
- Add Generate / Modify Keyframe from an appropriate frame-selection action.
- Populate project, frame number, corresponding source image, drawing, dimensions,
  paths, and available approved style references from project context.
- Allow previous approved, selected approved, or custom image style references.
- Generate candidates non-destructively; review, rejection, approval, and
  assignment to the synthesis keyframe set are explicit user actions.
- Normal users do not see backend node IDs or need YAML/command-line operations.

This is distinct from the existing Image Synthesis workflow, which transfers
style using the synthesis engines rather than a diffusion backend.

The supplied Project / Keyframes / Generator / Export tab arrangement is a
concept, not a decision to replace all current tabs. The application does not
currently supply every requested context concept as first-class metadata:
shot identity, approval history, and generator frame selection need deliberate
integration rather than assumptions about existing state.

Use existing extracted frame folders initially. This feature does not reverse
the earlier exclusion of direct video import/frame extraction or synchronized
source/output video comparison. Single-frame blink/overlay QC is in scope.

## Three-system architecture

### Desktop frontend

Owns project context, frame/keyframe selection, user settings, previews,
approval/rejection, assignment, and integration with existing synthesis jobs.
It exchanges semantic requests with the Keyframe Engine, not ComfyUI node IDs.

### Reusable Keyframe Engine

Owns line-mask handling, protection bands, editable masks, control selection,
model-family adapters, workflow assembly, deterministic compositing, exact
dimensions, alpha policy, geometry QC, overlays, naming, and candidate records.
Keep it independent of tab widgets so other frontends could reuse it later.

### ComfyUI backend

Executes inference, model/control loading, preprocessors, samplers, VAEs, LoRAs,
and supported reference-image conditioning. Separate workflow templates and
capability adapters support different model families.

Pipeline: frontend request -> engine masks/controls/workflow -> ComfyUI inference
-> engine enforcement/QC -> frontend candidate review -> approved keyframe.

## Deterministic geometry protection: Method C

1. Receive a user-provided line mask or extract a proposed mask from the drawing.
2. Preview and allow correction of the mask; automatic extraction is not assumed
   to identify every important contour correctly.
3. Build a protection band using dilation/distance transforms. The supplied
   example is approximately 3–8 pixels around contours; width must account for
   resolution and line thickness, not become a universal fixed default.
4. Invert the protection mask to define AI-editable regions.
5. Supply the editable mask to a verified masked-generation workflow.
6. Restore original pixels throughout the protected band, not just center lines.
7. Enforce the original canvas and the chosen alpha/compositing policy.
8. Validate and present QC before approval.

Protection targets include silhouettes, occlusion boundaries, face/jaw contours,
eyes/nose/mouth, hands, clothing boundaries/folds, and object edges. Named
protection options require actual masks or supported landmark/region detection;
they cannot merely change a prompt.

Guarantee boundary: deterministic restoration can preserve the supplied protected
pixels and canvas exactly. It cannot guarantee all unprotected geometry or
prevent every new interior contour/occlusion. Control conditioning and contour
metrics are assistance, not proof. Ambiguous masks or failed validation require
correction/review rather than an automatic acceptance claim. Registration tools
must not silently warp the authoritative drawing to fit a generated image.

## Semantic controls and supported workflows

Candidate controls: SoftEdge/Anyline, Lineart, Canny, Depth, Pose/OpenPose/DWPose,
Normals, Segmentation, Tile, Face landmarks, masked generation, and style
reference/IP-Adapter where supported. Scribble is lower priority.

Suggested hierarchy from the supplied specification: Lineart or SoftEdge plus
protected-band masking; Depth when useful; Segmentation/Normals as needed; Pose
selectively; approved keyframes for style reference. Anyline as a preferred
default is a proposal to evaluate, not an established project capability.

Each supported control exposes enablement, source, strength, and conditioning
start/end percentages where the chosen workflow supports them. Disable unsupported
choices with an explanation. Do not stack all controls by default.

Qwen, FLUX, SDXL, and other families are candidates, not confirmed integrations.
Select one verified family/workflow for the first inference milestone. Keep
family-specific templates instead of a universal node graph. Verify actual
nodes, model assets, masked generation, control compatibility, and runtime APIs
before claiming support. Example template names in the supplied discussion are
conceptual, not files already present here.

Generation UI may expose model, denoise, style/detail/shading strengths, and
prompt. Only expose settings with a defined, tested effect in the active adapter;
do not add decorative sliders with no backend mapping.

## Candidate review and synthesis integration

Views: Source, Drawing, Generated, Final, Overlay, Difference, and contour-error
heatmap. Include opacity/blink comparison of the same frame. Clearly distinguish
raw generation from the enforced final candidate.

Actions: Generate Candidate, Regenerate, Reject, Approve, Set as Keyframe, and
Advanced: Open Current Workflow in ComfyUI. Approval may offer direct assignment,
but generation alone must not replace a synthesis input.

QC includes exact dimensions, protected-pixel conservation, contour distances,
and strict checks for supplied occlusion masks. Region-specific metrics such as
eyes/hands require identified regions; do not invent semantic scores from an
unlabelled global edge map. Thresholds and limitations must be visible.

Store candidates outside folders scanned for numbered synthesis keys. On explicit
assignment, preserve original drawings and previous approved versions outside
the active scan folder, and publish the intended numbered key transactionally.
The existing source/key numbering and duplicate-number rules remain authoritative.
Do not replace inputs in use by an active render.

Capture request provenance: frame number, source/drawing identity and hashes,
dimensions, masks, settings, workflow/model versions, seed, and backend job ID.
Tie late results to their originating request, not whichever frame is currently
selected. Track approval explicitly; filename presence alone is not approval.

Use versioned generator project metadata and a separate semantic preset scope.
Existing rendering projects/presets must continue to load with unchanged behavior.
Missing/moved assets, unsupported presets, and incompatible models need clear
recovery choices rather than silent substitutions.

Alpha processing within candidate generation does **not** authorize transparent
FuouM synthesis. The separately listed transparent FuouM feature remains lower
priority and requires explicit user permission before investigation or work.

## Windows backend installation and lifecycle

Preferred production mode: optional, managed, tested/pinned ComfyUI installation
with isolated Python dependencies. On first use, offer Install Backend or Use
Existing ComfyUI. Keep software and large model assets separate; reuse shared
model paths where supported and explicitly selected.

The supplied `%LOCALAPPDATA%\EzSynth\AIBackend` location is illustrative. Choose
a consistent product namespace and installation/update policy during design.
Do not modify the synthesis Python environments or silently alter an existing
customized ComfyUI installation.

Support managed, existing local installation, and already-running server modes.
Validate reachability, workflow/node versions, preprocessors, and required models
before enabling generation. Existing ComfyUI may be used for development with
the user's selection; production defaults remain reproducible and pinned.

- No Windows autostart; no backend/model loading just because the desktop opens.
- Start an owned backend on demand, hidden, without opening a browser.
- Managed service binds to loopback; `127.0.0.1:8190` is a proposed dedicated
  endpoint, subject to collision checks. Do not silently attach to an unknown
  process occupying the port.
- Surface Starting, Ready, Generating, and Error, with detailed logs in Advanced.
- Track ownership: stop only application-owned processes on exit; never terminate
  an already-running external server merely because the frontend closes.
- Backend and custom-node updates are controlled, tested, and pinned, not blind
  automatic updates to latest.

Requests, progress/events, disconnections, cancellation, output retrieval, and
shutdown run without blocking the Qt UI. Correlate events to the submitted job.
Define cancellation behavior for owned versus shared/external servers; do not
interrupt unrelated external jobs. Retain actionable error context and clear
partial-candidate/temporary-file cleanup policies.

Expose optional keep-backend-running, keep-models-resident, and Release GPU Memory
controls only with verified backend behavior. Coordinate GPU-heavy generation
with existing synthesis jobs; initially serialize application-managed workloads.
Releasing memory on an external server must not disrupt unrelated work. The
supplied target is an RTX 5090, but capability/memory checks should use the actual
selected runtime rather than assume that hardware everywhere.

## Proposed incremental implementation and acceptance gates

These stages are a planning proposal, not a newly authorized priority over the
already selected edge panel or FuouM items.

1. **Deterministic protection and QC foundation.** Semantic request/result types,
   editable masks, band construction, full-resolution pixel restoration, candidate
   storage, and static QC. Test exact protected pixels/dimensions, mask boundaries,
   malformed inputs, and defined alpha behavior without requiring AI/GPU tests.
2. **One verified inference adapter.** Explicitly selected compatible ComfyUI,
   capability checks, one tested masked workflow, asynchronous submission/progress,
   cancellation/disconnection handling, and retained candidate provenance. Verify
   actual outputs on representative drawings before adding other families.
3. **Integrated review/assignment workflow.** Generator tab and frame action,
   context selection, mask inspection/correction, QC views, approval/versioning,
   safe key assignment, compatible projects/presets, stale-result handling, and
   GPU scheduling. Validate an end-to-end synthesis run using an approved key.
4. **Managed Windows backend.** Optional pinned installer, isolated environment,
   shared model library, readiness diagnostics, owned-process lifecycle, controlled
   updates, and clean-machine install/recovery testing. Normal operation must not
   require the ComfyUI browser or command line.
5. **Complete the general generation workflow and broaden capabilities.** Deliver
   the required first-class Generate New Keyframe mode using source-based structure
   and style references, with its own enforcement policy and QC. Refinement may
   receive the first implementation attention for the owner, but new generation
   is a core delivery milestone. Additional verified families/controls, semantic
   region thresholds, and advanced workflow access can follow independently.

Keep each stage usable and testable without assuming later stages are complete.
Reuse compatible deterministic edge/preview utilities where helpful, but keep
ComfyUI workflow dependencies out of the synthesis edge-tuning feature.

## Decisions still required

- Placement in the remaining feature queue. The previously selected edge-tuning
  panel/preview was implemented locally on 2026-09-26; generator priority relative
  to the additional FuouM items is still undecided.
- First model/workflow and whether a user-selected existing ComfyUI is available.
- Model licensing/download size and managed distribution/update policy.
- Mask correction UX, authority for occlusion/semantic regions, and QC thresholds.
- Exact shot/approval metadata and compatibility strategy for current projects.
- Alpha policy for generated candidates independently of synthesis-engine support.
- Default refinement effect and editable/protected-region policy for the owner's
  transparent line-art profile, including preservation of sparse color accents.
- External server authentication, remote-path handling, and allowed server scope
  if non-local connections are offered beyond the loopback-first implementation.

Source: user-supplied feature discussion attached to this task. Architectural
requirements above reflect that discussion; acceptance gates and integration
boundaries are planning additions, not implementation findings.
