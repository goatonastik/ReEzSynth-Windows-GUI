# Ezsynth frontend parity review

The original-engine compatibility review below remains scoped to
Trentonom0r3/Ezsynth. A second selectable FuouM/ReEzSynth adapter is now implemented;
its separate revision, capabilities and validation are recorded in DUAL_ENGINE.md
and PROJECT_STATUS.md. WORK_REMAINING.md is the current completion checklist.

Local review completed 2026-09-10 after approval-service access was restored.
The user-selected target is [Trentonom0r3/Ezsynth](https://github.com/Trentonom0r3/Ezsynth).
Its main branch resolved to commit
[`b198f2d7051eee542c4efc51c2d43dc442630bbf`](https://github.com/Trentonom0r3/Ezsynth/tree/b198f2d7051eee542c4efc51c2d43dc442630bbf).
This is the compatibility baseline, not a request to replace the local engine.

## Scope

Expose the upstream documented image and video workflows through graphical
inputs, settings and output controls, without requiring users to edit Python
scripts. The upstream examples are Python programs; no YAML-driven CLI was found
in the reviewed entry points. YAML import/export can represent the same frontend
configuration later. Building a new CLI is not a prerequisite for GUI parity.

Internal bookkeeping and arbitrary Python/ndarray programming are not UI settings.
Advanced public hooks must be inventoried separately instead of silently omitted
or presented as standalone controls when they require another input/workflow.

## Local compatibility and baseline

The actual checkout and GitHub remote match PROJECT_STATUS.md. Existing tracked
modifications and untracked implementation/test files were present before review
and were preserved. No AGENTS.md was found in the repository or checked parents.

An in-memory comparison against the pinned raw upstream source parsed both sides
with Python ast and compared syntax trees (ignoring formatting and comments):

- Eight engine modules match: main_ez.py, aux_classes.py, constants.py,
  aux_run.py, sequences.py, edge_detection.py, aux_computations.py and
  utils/flow_utils/OpticalFlow.py.
- Both example scripts, test_imgsynth.py and test_redux.py, also match.
- utils/_eb.py and utils/_ebsynth.py differ only by the existing backend argument
  and its forwarding to the native call. Preserve these fixes; upstream hardcodes
  automatic selection at that call. The frontend explicitly selects CUDA.

This is a comparison of twelve selected files, not the entire upstream tree or
native DLL. No engine imports, GPU initialization, downloads of weights, package
installation, Git fetch into the checkout, commits or pushes were performed.

The existing explicit lightweight suite passed again: **66 tests in 4.848 s**,
using E:/miniconda3/envs/reezsynth/python.exe. Offscreen Qt font/size-hint warnings
remain. These tests do not establish real GPU output or performance equivalence.

## Feature matrix

| Upstream surface | Current frontend | Required work |
| --- | --- | --- |
| Six synthesis parameters | Exposed, including Automatic pyramid depth (-1); bounds audited in NUMERIC_SETTINGS.md | Resolve documented policy caps; real output checks |
| Four guide weights | Exposed; bounds audited in NUMERIC_SETTINGS.md; GUI editors retain six decimal places | Resolve policy caps and arbitrary higher-precision round trips; preserve defaults |
| Masks, pre-mask, feather | Exposed | Validate real output in both independent and grouped video modes |
| Classic/PST/PAGE choice | Exposed | Real rendering checks; advanced detector tuning is a separate hook below |
| Multiple styled keyframes in one Ezsynth run | Implemented; mock validated | Real grouped render validation |
| Default blending / forward-only / reverse-only | Implemented; upstream sequence boundaries tested | Visual comparison against upstream |
| Histogram blending GPU option | Exposed with CuPy availability check | CuPy installation and GPU execution need approval |
| Poisson reconstruction options | Exposed, persisted and forwarded | Real CPU/GPU reconstruction validation |
| RAFT model selection | Sintel/Kitti exposed; weight preflight skips single-frame copies | Real Kitti output comparison; raft-small remains incompatible with this constructor |
| EF-RAFT and FlowDiffuser | Architecture/model selection, preflight and engine forwarding implemented; optional files are absent | Obtain compatible optional weights/dependencies and validate real output |
| Error/selection maps and flow visualization | Exported with a metadata manifest; mapping tested against upstream methods | Real GPU output validation; raw flow vectors are not exposed by the upstream full-results API |
| ImageSynth / ImageSynthBase | Implemented through Image Synthesis tab and dedicated job type | Real CUDA render comparison |
| Image guide pairs | Editable pairs/weights with dimension and channel validation | Real example validation |
| Image output and error output | image.png, numerical error.npy and metadata, required before COMPLETE | Real output validation |
| Presets and projects for new modes | Image preset group and optional image project data; legacy tests pass | Continue compatibility tests when adding further modes |
| Backend selection via the low-level wrapper | CUDA/Auto/CPU exposed and forwarded; CPU flow allowed without CUDA with compatible options | Real native CPU/auto availability and output tests; explicit backend forwarding preserved |

Core references: [rendering entry points](https://github.com/Trentonom0r3/Ezsynth/blob/b198f2d7051eee542c4efc51c2d43dc442630bbf/ezsynth/main_ez.py),
[RunConfig](https://github.com/Trentonom0r3/Ezsynth/blob/b198f2d7051eee542c4efc51c2d43dc442630bbf/ezsynth/aux_classes.py),
[video example](https://github.com/Trentonom0r3/Ezsynth/blob/b198f2d7051eee542c4efc51c2d43dc442630bbf/test_redux.py),
[image examples](https://github.com/Trentonom0r3/Ezsynth/blob/b198f2d7051eee542c4efc51c2d43dc442630bbf/test_imgsynth.py).

## Environment readiness

- Installed metadata: Python 3.11.16, PySide6 6.11.2, torch 2.11.0+cu128.
- RAFT files present: raft-sintel.pth, raft-kitti.pth, raft-small.pth. The supported
  RAFT constants only list sintel/kitti, and the model constructor sets small=False.
- EF-RAFT constants list 25000_ours-sintel, ours_sintel and ours-things; their
  configured weights directory currently contains no .pth files.
- FlowDiffuser's configured weights directory contains no .pth files. Its encoder
  imports timm and constructs pretrained backbones, which can require downloads.
- cupy and timm are not discoverable in the current interpreter. PyYAML 6.0.2 is
  installed for project/preset interchange. Metadata checks also found no cupy,
  cupy-cuda12x or timm distributions.
- Add availability checks without importing GPU models. Do not automatically
  install dependencies or download model/backbone weights. Those actions still
  require user approval. CPU blending can be implemented with existing libraries.

## Implementation traps found in the local source

1. **Job shape and progress:** reezsynth_jobs.py passes one style and checks exactly
   count-1 synthesis calls. Grouped blending needs multiple styles and can make
   two passes between them. A few extra controls cannot fix this assumption.
2. **Auxiliary outputs:** run_a_pass starts styled output with the supplied style,
   but adds errors/flows only for synthesized transitions. Blended run_scratch
   returns warped selection masks in the second output position. The outer runner
   also removes boundary entries. Do not zip every returned list with all source
   frame numbers or label all second outputs as raw error maps.
3. **Blending dependencies:** reconstruction enables use_poisson_cupy only when
   GPU blending is active. With that path active, LSQR selection does not control
   the CuPy solver. Explain or constrain these combinations in the frontend.
4. **Mode naming:** normal blending is selected with only_mode='none'. The literal
   'blend' is an internal sequence mode and should not be forwarded as if it were
   the normal override. The pass routine treats non-forward input as backward.
5. **Obsolete docs:** return_masked_only appears in documentation, but is absent
   from the actual RunConfig signature. Do not pass that keyword.
6. **Advanced edge hooks:** EdgeConfig and detector methods expose PST/PAGE tuning,
   while the standard precompute path calls defaults. do_compute_edge=False is
   only useful if replacement edge_guides are supplied before running. Add a
   deliberate custom-guide/tuning path if exposing these hooks.
7. **Image validation:** source guide dimensions match the style; target guide
   dimensions agree with other targets, but may differ from the style dimensions.
   Reusing the current video dimension rule would wrongly exclude retargeting.
8. **Layer separation:** validate_group('render') currently imports the Qt-bearing
   project-controls module for naming validation. Extract that pure validation
   before promising a GUI-independent configuration reader.
9. **Input flexibility:** upstream accepts an explicit styled-image list; the GUI
   currently scans a folder. Support selecting a subset in the grouped workflow.
   Review sequence-number rules carefully; accepting gaps without fixing the
   upstream index assumptions would not create reliable compatibility.

## Concrete implementation sequence

Steps 1–2 are implemented with mock computation coverage in
`test_reezsynth_grouped.py`; real grouped rendering and grouped mask output still
need validation. The remaining steps below describe the pending parity work.

Step 3 is also implemented: optional numerical maps and flow visualizations are
saved with explicit sequence/transition metadata. `test_reezsynth_artifacts.py`
checks flattened output indexing, lossless map values, export failure, persistence
and empty single-frame results. Full suite: 81 tests passed; GPU computation remains
unverified. Step 4 is now implemented: still-image inputs, weighted guide pairs,
image/error outputs, image presets and image-only projects. Tests execute the live
upstream ImageSynthBase.run method with native computation mocked. Full lightweight
suite at that stage: 100 tests passed. Step 5 now includes RAFT Sintel/Kitti,
EF-RAFT and FlowDiffuser architecture/model choices, selected-weight checks,
CPU-flow compatibility guards, optional-flow readiness and safe checkpoint import.
Custom edge-guide hooks and YAML project/preset interchange are also implemented.
The numeric limitations recorded in [NUMERIC_SETTINGS.md](NUMERIC_SETTINGS.md) and
upstream real-render comparisons remain. The user's GUI/direct-CLI benchmark
validates the shared frontend adapter path only.

1. Add an explicit grouped-video job type and Qt-free planning/configuration
   validation. Keep independent keyframe jobs and current defaults working.
   Grouped mode gets its own range/keyframe selection; do not reinterpret saved
   independent per-keyframe ranges without a visible workflow change.
2. Connect grouped jobs to EzsynthBase and the Blend/Flow tab. Add normal,
   forward-only and reverse-only modes, CPU blending controls and mode-aware
   progress. Test nonzero numbering, adjacent keys, outer tails, masks, cancellation
   and boundary output mapping with mocked computation.
3. Preserve optional auxiliary artifacts with explicit metadata and formats.
   Extend job.json/COMPLETE handling so requested artifacts must be saved before
   success is reported.
4. Implement Image Synthesis with weighted guide pairs, validation, presets and
   saved projects. Reuse the worker/queue lifecycle; guard against the upstream
   mutable default guide list by always passing a fresh list.
5. Add compatible flow/model and backend choices plus availability diagnostics.
   Add advanced edge/custom-guide controls using a defined adapter path.
6. Add YAML import/export of the same versioned settings when the parser dependency
   is approved. Reuse validation; reject unknown keys instead of silently changing
   the requested behavior. Add round-trip and legacy-project tests.
7. With approval, compare actual image/video examples against the pinned upstream
   API, including blending modes, flow choices, saved artifacts and memory cleanup.

Definition of done: each listed capability has an effective GUI path, persisted
configuration, validated engine forwarding, appropriate outputs and a regression
test. Real-render results and mock-test results must remain distinguished.
