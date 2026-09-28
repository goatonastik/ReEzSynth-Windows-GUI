# ReEzSynth project implementation, original plans, and recommendations

Prepared 2026-09-25. Repository baseline: `main`, commit
`8f16d76c030c06af21c542d863a1169f9e344f3b` (2026-09-24).

## 1. Main findings

The project now delivers most of the practical frontend you originally described:
numbered input folders, keyframe propagation ranges, reusable presets, configurable
outputs, optional automation, parallel rendering, notifications, and persistent
settings. It has also grown beyond that initial brief into a two-engine application
with grouped blending, still-image synthesis, previews, recovery journals, caches,
disk-backed frame storage, transparent Legacy keyframes, and Windows packaging.

The most defensible configuration-coverage figures are:

| Scope | Result | What that means |
| --- | --- | --- |
| Original Legacy `RunConfig` | **18 of 18 fields mapped** | Every original constructor setting has a frontend control/effective adapter path, subject to mode and numeric restrictions. |
| Additional Legacy low-level runner scalar settings | **7 of 8 mapped** | `stop_threshold` is still fixed rather than exposed for Legacy. This set overlaps RunConfig and must not be added to 18. |
| Legacy detector tuning | **0 of 16 algorithm-specific tuning slots exposed** | PST has 6 arguments and PAGE 10, excluding the input image. Detector selection and external custom edge images are supported separately. |
| Pinned FuouM YAML schema | **32 of 46 leaf fields have user-controlled functional mappings** | Inputs and frontend equivalents count, not just identically named spin boxes. This is approximately 69.6% of schema leaves, not a quality or overall completion score. |
| Other FuouM schema leaves | **5 managed/fixed, 2 recompute controls absent, 7 dormant fields** | These categories explain the other 14 fields; details and the complete inventory appear below. |
| Approved enhancement checklist | **9 of 10 groups documented complete** | The remaining group concerns broader quality/stability evidence, not nine tenths of all possible functionality. |

Neither engine is appropriately described as having unrestricted, exact API/CLI
parity. Numeric domains are bounded, some lower-level hooks are absent, and the
frontend's YAML files are its own project/preset format, not native FuouM YAML.

My assessment: the highest-value next work is making the existing functionality
easier to choose, inspect, and recover, followed by completing installation and
production validation. Adding every internal parameter would offer less value to
normal users than exposing the consequences of the settings already available.

## 2. Evidence and limits of this report

This report uses current source, adapters, tests, documentation, Git history, the
installed pinned FuouM source, and relevant project conversations available in the
app. In particular, I recovered your original prompt from the task
**“Continue ReEzSynth-Windows-GUI”** (`01a08d20-97bc-7a93-a139-3740cf23fc50`).
That provides direct evidence of your intent rather than reconstructing everything
from later code or comments.

Your later inclusion/exclusion decision was also found in **“List outstanding
items”** (`01a09488-cdfb-7782-af3c-e95e6796b646`): include FuouM in standard setup;
do not add direct video import or synchronized source/output playback.

This was a source/documentation review. No fresh GPU render, clean installation,
test-suite run, or live GUI usability session was performed. References to passing
tests and visual reviews identify previously recorded evidence. Appearance
recommendations are based on widget construction and painting code; they are not
claims that a new screen-by-screen visual inspection was performed.

There were existing/concurrent uncommitted changes in `INSTALL_WINDOWS.md`,
`README.md`, `install_reezsynth.ps1`, `installer/ReEzSynth.iss`, and
`test_reezsynth_packaging.py`. They concern installer prerequisite/download and
cleanup work. They were preserved. The committed baseline above remains the
reference for history; these live installer edits are not presented as a newly
validated release. This report is the only file created by this investigation.

## 3. Your original plans compared with the implementation

Your original central goal was to make the customization otherwise requiring YAML
or command-line arguments available through graphical controls. You also specified
independent preset groups, folder discovery, output naming, optional immediate
rendering, concurrency limits, sound notifications, and startup restoration.

| Original request | Current implementation | Assessment |
| --- | --- | --- |
| Editable rendering/configuration inputs in the GUI | Rendering, guide weights, Blend / Flow, Image Synthesis, and Settings controls; engine-specific adaptation | Broadly implemented; exact coverage boundaries are in section 5. |
| Folder drag/drop | Folder editors/history widgets accept folder input and dropping | Implemented. |
| Directory, weight, other-render, and application presets | Seven groups: directories, output, weights, render, grouped, application, image | Implemented and expanded. |
| Preset dropdown with plus/minus, named save, prefilled current name, overwrite warning | `Options.preset_bar`, `save_preset`, and `remove_preset` | Implemented. |
| Separate shareable preset storage | Versioned `presets.json`, with JSON/YAML import/export | Implemented. One shared library contains the groups; it is not one file per preset. |
| Find matching `keys...` and `video...` folders below a selected directory | Configurable prefixes; recursive matching by common suffix; selection dialog if several pairs match | Implemented. Discovery selects a pair; it is not a multi-shot batch scheduler. |
| Output name variables and suffix checkboxes | Batch/job templates, keyframe name, date/time, key/video folder suffixes, destination preview | Implemented. |
| Start when source/key folders are ready; optionally wait for masks | Debounced input-triggered automatic start with validation and repeated-input signature guard | Implemented; opt-in. Not a continuously watched render farm folder. |
| Limit simultaneous renders, initially `0 = no limit` | Parallel rendering is optional; saved default cap is 2, and `0` means GPU-aware automatic admission | Function implemented; original zero/default semantics changed. |
| Completion sound after each job and/or queue; custom file, default sound, disable option | Separate per-job/queue choices and file picker; sound enabled and queue sound selected by default | Implemented. |
| Per-group startup preset or restore last-used | Independent defaults/named-preset/last-used policies | Implemented. |
| Update last-used values whenever fields change | 150 ms debounced save plus close-time persistence; invalid groups retain prior valid saved values | Implemented in a debounced form. Queue range edits still require a saved project. |
| A Settings window/button | Settings is now a tab | Superseded by your later explicit request to use a tab and replace the button with Previews. |

The parallel-setting difference deserves an explicit product decision, but not an
automatic reversal: your later instructions retained sequential rendering by
default, and GPU-aware admission was subsequently approved. An automatic limit is
more consistent with predictable desktop use than treating zero as unrestricted
process creation. The UI already labels zero as automatic.

Later requests found in the project conversation are also implemented:

- Original-resolution default, exact square/landscape/portrait presets, and custom
  width/height; mismatched original-size video/key dimensions are rejected.
- Preview/Standard/Highest quality profiles; guide weights remain independent.
- Protected Default entries and Reset all settings to defaults.
- Key/video/mask weights beside folder inputs; Mapping, Deflicker, Diversity in
  the requested order; output naming beside the folder panel.
- Matching custom checkbox/spin-button appearance, and tabs beside the logo.
- A resizable preview window with key/direction tiles, outlined captions, queue
  pairs or responsive square grid, default cap eight, and capture only when open.
- Session-wide diagnostic log with queue separators and Save Log.
- Direct-job benchmark script to compare frontend and fresh-process timings.
- Optional-model readiness checks and installation controls.
- Memory-efficient Legacy RAFT correlation and specific GPU-memory error handling.

Evidence: `reezsynth_gui.py`, `reezsynth_options.py`,
`reezsynth_project_controls.py`, `reezsynth_preview.py`,
`reezsynth_cli_benchmark.py`, and the original task cited above.

## 4. What the application currently does

### Inputs, planning, and rendering modes

The normal input is a consecutive PNG/JPEG source sequence, plus styled keyframes
whose filename-ending numbers match source frames. The app builds independent
keyframe jobs with inclusive backward/forward ranges. Blend / Flow provides a
separate grouped range and keyframe selection; it does not reinterpret the
independent queue's custom ranges.

Image Synthesis uses style, source guide, target guide, and optional additional
guide pairs. Target dimensions may differ from style/source dimensions. Processing
size settings apply to the relevant workflow; video-only controls are disabled in
the image workflow.

| Capability | Legacy | FuouM |
| --- | --- | --- |
| Independent keyframe jobs | Yes | Yes |
| Grouped multi-keyframe video and directional modes | Yes | Yes |
| Still-image/multiple-guide synthesis | Yes | Yes |
| Classic/PST/PAGE and custom edge sequences | Yes | Yes |
| Masks, optional premasking, feathered source compositing, mask guide | Yes | Yes |
| RAFT Sintel/Kitti | Yes | Yes |
| EF-RAFT / FlowDiffuser | Optional Legacy paths | Not selected through this adapter |
| NeuFlow | No frontend path | Yes |
| Compiled memory-efficient RAFT correlation | Yes | No equivalent frontend toggle |
| CuPy grouped blending/reconstruction | Optional | Not through the Legacy CuPy controls |
| Additional reconstruction choices | LSQR/LSMR, optional CuPy | LSQR/LSMR/CG/AMG/seamless/disabled |
| Per-level iteration schedules | Yes | Yes |
| Guide modulation | CUDA only; CPU/Auto requests rejected | Native CUDA and repaired experimental torch |
| Meaningful transparent RGBA style/keyframes | Supported in PNG/image/video paths | Explicitly rejected |
| Keyframe preservation selector | Current behavior / Exact output / Transition-aware | Supplied keys are preserved; Legacy selector disabled |
| Independently measured forward/backward flow option | Not the FuouM option | Opt-in for RAFT/NeuFlow |
| Alternative synthesis backend | CUDA/Auto/CPU | CUDA or experimental repaired torch; both require CUDA |

Transparent style synthesis and mask compositing serve different purposes. A
transparent Legacy result can retain alpha in PNG; compositing it onto opaque
source footage with masks produces opaque output. The current MP4 export uses
H.264/yuv420p and does not preserve alpha. Nor does implemented RGBA support claim
pixel-identical behavior to the commercial EbSynth Beta application.

### Configuration and persistence

The GUI has seven preset groups, version-1 project documents, per-group startup
policies, and separately saved last-used settings. JSON is the default document
format; YAML is supported through safe parsing and the same schema validation.
Folder history remains in QSettings.

Recent persistence changes establish a dedicated owner for output settings,
isolate rejected entries within readable preset libraries, preserve their raw data,
and handle malformed YAML through normal user-facing errors. Projects preserve
custom queue rows; restoring last-used folders alone is not project recovery.

### Jobs, previews, logs, and outputs

- Shared worker reuse is the default, with per-job engine initialization. Isolated
  and optional parallel processes are also available.
- Qt `QProcess` carries stdin commands and stdout progress/lifecycle events.
  Each prepared job freezes its engine, revision, runtime, paths, and settings.
- Parallel admission uses GPU telemetry and per-job memory estimates; estimates
  are not promises that every allocation will fit.
- Stop/close/shutdown paths coordinate worker termination. The later F1–F3 work
  addressed journal-start failure, maintenance/close interactions, and successful
  output whose final shared-worker handshake is lost.
- `.reezsynth-queue.json` supports manual recovery, completed-job skipping,
  changed-input rejection, and fresh output folders for partial-job restarts.
- `COMPLETE.txt` represents completed required output stages. It is an application
  completion marker, not a power-loss durability guarantee.
- Live previews are demand-driven, capped at 960 pixels on their longest edge,
  and show synthesis before final grouped blending or mask compositing.
- Final products include PNGs, optional MP4/audio, error/selection arrays, flow
  visualizations/vectors, and manifests describing settings and runtime provenance.
- Verified project caches reuse edges/flow. Optional disk storage bounds retained
  decoded arrays to eight arrays/64 MiB; it does not cap GPU or whole-process RAM.

### Installation and distribution

The committed project includes source ZIP and per-user Inno Setup candidate
packaging, launcher shortcuts, dependency installation/recovery, and engine checks.
Normal setup targets Windows x64/Python 3.11, pinned PySide6/PyTorch CUDA packages,
and a separate FuouM environment. Both engines use a package called `ezsynth`, so
process/runtime separation remains intentional.

Fresh native builds need the matching CUDA toolkit and Visual Studio C++ tools.
The installer now has prerequisite installation choices; setup is still a visible,
substantial download/build step rather than an entirely self-contained executable.
Current uncommitted work adds alternative prerequisite download handling.

The latest documented candidate build is `0.1.0-preview.2` at `ff4dcbd`; that
artifact is older than current HEAD and should not be confused with a package of
all subsequent installer changes. Clean-machine installation/render/uninstall
validation remains a documented release gate.

## 5. Configuration and command-line coverage in detail

### Counting rules

The original target was Trentonom0r3/Ezsynth at `b198f2d...`. Its documented entry
points were Python examples, not an established YAML-driven command-line flag
catalog. Accordingly, Legacy is counted from its actual public constructor
settings. FuouM is counted separately at the installed pinned revision
`aaa8d06170e6cc59054410aa9c422edd789f7ab2`.

Counted fields exclude `self`, schema container objects, and duplicate aliases.
FuouM `final_pass.enabled` and `.strength` count as two leaves. A user-controlled
functional mapping may be a selected input, derived frame-index list, or frontend
equivalent; it need not forward the same literal YAML key. It does not imply the
complete upstream value domain is supported.

### Legacy: all 18 original RunConfig fields

| Field(s) | Count | Current control/path |
| --- | ---: | --- |
| `uniformity` | 1 | Diversity |
| `patchsize` | 1 | Patch size |
| `pyramidlevels` | 1 | Pyramid levels / Automatic |
| `searchvoteiters`, `patchmatchiters` | 2 | Scalar iteration controls; optional schedules override them |
| `extrapass3x3` | 1 | Extra 3x3 polishing pass |
| `edg_wgt`, `img_wgt`, `pos_wgt`, `wrp_wgt` | 4 | Edge, Video, Mapping, Deflicker guide weights |
| `use_gpu` | 1 | Grouped GPU blending |
| `use_lsqr` | 1 | Grouped LSQR/LSMR selection |
| `use_poisson_cupy` | 1 | Grouped CuPy reconstruction |
| `poisson_maxiter` | 1 | Applicable reconstruction iteration limit |
| `only_mode` | 1 | Grouped normal/forward/reverse mode |
| `do_mask`, `pre_mask`, `feather` | 3 | Mask enablement, premasking, feather |
| **Total** | **18** | **18 mapped; no missing original RunConfig field** |

`keyframe_preservation` is a later local addition, giving the current constructor
19 settings. It is not counted as an original upstream field. Key/style weight
and mask-guide weight are frontend extensions; key weight works by normalizing
guide weights rather than adding a native style-weight setting.

`reezsynth_jobs.py:468` builds the effective `RunConfig`, then constructs
`EzsynthBase` with edge, flow/model, masks, and input arrays. The constructor
input fields are also supplied: styles, style indices, source sequence, config,
edge method, model, mask flag/sequence, architecture, and whether to compute edges.
`do_compute_edge` follows the custom-edge/cache workflow rather than appearing as
an unexplained raw checkbox.

### Legacy coverage outside RunConfig

The original `EbsynthRunner.run` has eight scalar tuning/backend arguments after
style/guides. Seven are represented: patch size, pyramid depth, both iteration
counts, uniformity, polishing, and backend. `stop_threshold` remains fixed at 5
in the ordinary wrapper path; FuouM's stop-threshold control is not a Legacy
control. This is **7/8**, overlapping the core table rather than extending its
denominator.

PST exposes `S`, `W`, `sigma_LPF`, `thresh_min`, `thresh_max`, `morph_flag`.
PAGE exposes `mu_1`, `mu_2`, `sigma_1`, `sigma_2`, `S1`, `S2`, `sigma_LPF`,
`thresh_min`, `thresh_max`, `morph_flag`. None of these **16 algorithm-specific
slots** is directly editable in the GUI. The common morphology flag occupies a
slot in both algorithms; this is not a claim of 16 independent EdgeConfig
attributes. Standard computation uses the detector defaults. Supplying external
edge-guide images is an implemented alternative workflow, not detector-tuning
parity.

Further limits are explicit in `NUMERIC_SETTINGS.md`: six-decimal editors,
bounded patch/weight/iteration/size ranges, consecutive source numbering, fixed
image-file/channel conventions, and no arbitrary Python-array programming through
the GUI. Per-level iteration schedules and grayscale logical-guide modulation are
implemented; arbitrary separate per-channel/float modulation is not.

### FuouM: complete 46-leaf inventory

Legend: **U** = user-controlled functional mapping; **M** = frontend-managed or
fixed behavior; **X** = upstream control not exposed; **D** = declared schema
field without a consumer found in the pinned operational engine path. D fields
are not seven missing working features.

| Schema section | U | M | X | D | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Project | 6 | 3 | 2 | 0 | 11 |
| Precomputation | 3 | 0 | 0 | 0 | 3 |
| Pipeline, including final-pass leaves | 3 | 1 | 0 | 7 | 11 |
| Blending | 4 | 0 | 0 | 0 | 4 |
| Synthesis | 15 | 0 | 0 | 0 | 15 |
| Debug | 1 | 1 | 0 | 0 | 2 |
| **Total** | **32** | **5** | **2** | **7** | **46** |

The 32 user-controlled mappings are:

| Fields | Count | Frontend mapping/qualification |
| --- | ---: | --- |
| `project.content_dir`, `style_path`, `style_indices`, `output_dir` | 4 | Source/key selections, grouped subset/range planning, and destination controls. Arrays and local indices are prepared by the adapter, bypassing upstream directory loading. |
| `project.mask_dir`, `modulation_dir` | 2 | Frontend masks/modulation sequences; adapter equivalents rather than literal upstream directory-loader forwarding. |
| `precomputation.flow_engine`, `flow_model`, `edge_method` | 3 | RAFT/NeuFlow, corresponding model, and Classic/PST/PAGE selection. |
| `pipeline.pyramid_levels`, `use_temporal_nnf_propagation`, `use_sparse_feature_guide` | 3 | Pyramid depth, temporal NNF and sparse-feature controls. Automatic depth is translated for FuouM. |
| `blending.poisson_solver`, `poisson_maxiter`, `poisson_grad_weight_l`, `poisson_grad_weight_ab` | 4 | Solver, applicable iteration limit, luminance/chroma weights. |
| `ebsynth_params.uniformity`, `patch_size`, `vote_mode` | 3 | Diversity, patch size, weighted/plain voting. |
| `ebsynth_params.search_vote_iters`, `patch_match_iters` | 2 | Scalar/scheduled iterations. |
| `ebsynth_params.stop_threshold`, `search_pruning_threshold`, `cost_function` | 3 | Stop/pruning controls and SSD/NCC. |
| `ebsynth_params.backend`, `extra_pass_3x3` | 2 | CUDA/repaired experimental torch and polishing. |
| `ebsynth_params.edge_weight`, `image_weight`, `pos_weight`, `warp_weight`, `sparse_anchor_weight` | 5 | Guide/sparse weights, normalized by key weight. |
| `debug.save_flow_viz` | 1 | Frontend flow-visualization export equivalent, saved with frontend artifact metadata. |

The remaining 14 leaves are:

| Field | Class | Current treatment |
| --- | --- | --- |
| `project.name` | M | Upstream project name uses its default; frontend directory/output identity is separate. |
| `project.cache_dir` | M | Private adapter cache and separate project precomputation cache; no raw native cache-directory control. |
| `project.force_style_size` | M | Adapter validates/processes arrays before injecting them. The upstream true/false loading policy is not selectable. |
| `pipeline.use_residual_transfer` | M | Retains the default iterative path; no exposed false-path switch. Relevant to the alternate backend, not a universal residual-transfer feature. |
| `debug.flow_viz_dir` | M | Export locations follow frontend output organization rather than an arbitrary debug-folder picker. |
| `project.force_recompute_flow` | X | No user-facing force-recompute option; content-addressed cache controls reuse. |
| `project.force_recompute_edge` | X | Same limitation for edge maps. |
| `pipeline.final_pass.enabled`, `pipeline.final_pass.strength` | D | Declared/carried in config/API, but no operative consumer found in the pinned pipeline. These are not the implemented `extra_pass_3x3` switch. |
| `pipeline.alpha`, `max_iter`, `flip_aug`, `content_loss`, `colorize` | D | Declared fields without an operative consumer found in the pinned pipeline. Do not expose them as working sliders without implementing and validating behavior. |

Thus 37/46 fields have either a frontend mapping or a managed policy, but **37/46
must not be advertised as 80.4% exact native-config compatibility**. Several
managed policies deliberately remove choices, and the seven dormant leaves make a
raw percentage a poor measure of useful feature completeness.

Sources: `engine_sources/fuoum_reezsynth/ezsynth/config.py`, its `pipeline.py` and
`engines/backends/pytorch_backend.py`; `reezsynth_fuoum.py:12` (`build_configs`),
its `render_fuoum_job`, `reezsynth_fuoum_pipeline.py`, `reezsynth_modulation.py`,
and `reezsynth_artifacts.py`.

### Command-line arguments and YAML compatibility

The pinned FuouM checkout contains multiple distinct tools, not one large renderer
flag list. Excluding argparse's implicit help flag, these selected entry points
contain 24 named flags:

| Entry point | Flag count | Frontend relationship |
| --- | ---: | --- |
| `run.py` | 1: `--config` | GUI replaces configuration authoring/execution, but does not import its native MainConfig YAML directly. |
| `run_img_synth.py` | 3: `--backend`, `--full-params`, `--benchmark` | Backend has a GUI choice; quality/explicit parameters and diagnostic timings provide related workflows. The example's exact fast/full recipes and benchmark switch are not reproduced as identical controls. |
| `prepare_video.py` | 2: `--video`, `--output` | Input video extraction; deliberately excluded by your preference. |
| `fastblend_standalone.py` | 8 | Separate FastBlend tool, not integrated into the GUI. |
| `fastblend_standalone_interpolate.py` | 10 | Separate interpolation tool, not integrated into the GUI. |

The FastBlend flags are `content_dir`, `style_dir`, `output_dir`, `accuracy`,
`window_size`, `batch_size`, `prefix`, `backend`; the interpolation flags are
`frames_dir`, `keyframes_dir`, `output_dir`, `keyframe_interval`, `accuracy`,
`window_size`, `batch_size`, `minimum_patch_size`, `prefix`, `backend`.
The existing Blend / Flow tab is not a wrapper for these separate tools. Similar
folder inputs do not count as implemented FastBlend behavior.

These 24 flags are an inventory of the five named pinned tools, not all utilities
in every upstream subproject, and not an appropriate denominator for original
Legacy parity. There is no honest single “implemented X of all command-line
arguments” figure spanning these different engines and workflows.

Current frontend CLI execution exists through `reezsynth_jobs.py job.json`, the
shared-worker protocol, launcher arguments, and the saved-job benchmark helper.
Frontend JSON/YAML project and preset interchange is implemented. A native FuouM
YAML importer/exporter or general per-setting CLI is additional work if desired.

## 6. Development stages and remaining commitments

| Stage | Main work |
| --- | --- |
| September 10 | Imported existing GUI versions, consolidated entry point/launcher, expanded presets/outputs and grouped/image workflows. |
| September 11 | Reproducible Windows setup and compiled memory-efficient RAFT support. |
| September 12 | Dual runtimes, additional flow/blending paths, MP4/audio, journals, caches, GPU scheduling, maintenance UI, CI, diagnostics, disk storage, schedules, modulation, repaired experimental torch. |
| September 13–14 | Lifecycle fixes, RGBA handling, persistence/output ownership, invalid-preset isolation, YAML handling, image-mode control gating, resize warning, Legacy blend/error alignment. |
| September 15–21 | Native production-footage review, Legacy keyframe preservation modes, masked-alpha refinements, release provenance work. |
| September 22–24 | Source/Windows candidate packaging, security checks, runtime/dependency notices, prerequisite installer and recovery, uninstall cleanup. |

There are 63 commits at the inspected HEAD, 29 after the earlier `ecb1f95`
handoff baseline. Older handoff/status statements cannot be assumed current.

The current checklist marks nine of its ten approved enhancement groups complete.
Those completed groups include additional flow choices, GPU blending, video
export, durable recovery, cache/storage work, GPU scheduling, GUI engine
maintenance, advanced controls, and automated regression checks. The tenth group,
quality/stability evidence, remains open despite implementing its diagnostic
harnesses and measured backward-flow path.

Documented remaining work includes:

- Independent clean Windows/different-GPU installation and short renders.
- Longer stability testing with measurements that distinguish the application's
  resource use from other software on the desktop.
- Broader production-footage/style review at intended quality settings.
- Final release-candidate inventory/build/installation validation for the actual
  commit intended for distribution.
- Specific keyframe-coverage experiments identified in the s6 production review,
  including better endpoint anchoring rather than assuming another global render
  setting alone will resolve the shot.

Do not carry forward the old claim that all asset-notice questions remain open:
`PROJECT_STATUS.md` records closure of the current package design's dependency and
runtime notice gate on September 23. Clean-machine validation remains open.

The canonical runner now lists **29 maintained test modules**. The latest hosted
result explicitly recorded near the top of `PROJECT_STATUS.md` is **418 tests
passing on `ff4dcbd`**, plus its listed security checks. This review did not run the
current suite and does not certify the live uncommitted installer changes from
that older result. The previously recorded eight-hour attempt is inconclusive,
not a completed overnight validation or proof of a renderer memory leak.

## 7. Recommended improvements, ranked by practical impact

2026-09-26 follow-up: the selected advanced edge-tuning panel and Edge Preview
below are now implemented locally. See EDGE_TUNING.md and WORK_REMAINING.md for
current behavior and validation. The proposal discussion below records the
original selection; the Keyframe Generator and additional FuouM items remain
planned. This implementation update does not refresh the entire earlier review.

Further 2026-09-26 follow-up: the flow/edge recompute controls are now implemented
for FuouM video. They bypass shared-cache reads/writes for the current render,
not refresh existing shared entries. See PRECOMPUTE_RECOMPUTE.md. The remaining
FuouM proposals and Keyframe Generator are still planned.

These are proposals, not implemented changes. They prioritize your goal of normal
users doing routine work without YAML or command-line knowledge.

User-selected next feature: implement the advanced edge-tuning panel and Edge
Preview immediately after the current installer work. This user preference takes
precedence over the impact ranking below. Placement: a collapsible panel below
Edge method in Rendering, with controls appropriate to the selected detector.
The separate resizable preview window selects a source frame and shows source,
generated edges, optional overlay, and comparison with defaults. Start with an
Update Preview button and an outdated indicator; compute one frame in a separate
process using the actual rendering edge path and processing size. A reduced-size
preview must be labelled. Save tuning in projects/rendering presets, preserve
existing defaults, and bypass automatic tuning when custom edge guides are used.
Include Reset edge settings to defaults. This feature is approved for the list;
it has not been implemented by this report update.

The user subsequently selected these additional FuouM TODOs, after edge tuning:
force-recompute flow/edges, short selected-range comparisons, and native FuouM
YAML import/export. Transparent FuouM keyframes are a lower-priority item and
require the user's explicit permission before feature-specific investigation,
prototyping, or implementation. Listing transparency here is not authorization
to start it. WORK_REMAINING.md records their priority order and boundaries.

The user also supplied an AI-assisted Keyframe Generator specification on
2026-09-26. This is a separate planned feature, not existing Image Synthesis:
an integrated tab, deterministic protected-contour masks and QC, reusable
Keyframe Engine, and isolated ComfyUI inference backend. See
KEYFRAME_GENERATOR_PLAN.md for requirements and proposed implementation stages.
Its place among later features is not yet selected; edge tuning remains next.
No generator implementation or backend installation is claimed by this update.

| Priority | Proposal | User benefit and concrete scope | Relative effort |
| --- | --- | --- | --- |
| 1 | A clear pre-render summary/readiness panel | Before Run, show workflow, engine, source/key counts, processed resolution, mask/alpha mode, output path, approximate GPU/disk needs, and whether MP4 will lose alpha. Reuse existing validation and estimators. | Medium |
| 2 | Finish and exercise the installer on another machine | Use the existing clean-machine protocol and rebuild a candidate from the reviewed final installer commit. Installation is now a major part of the product. | Medium–high, needs external host |
| 3 | Visual keyframe/range coverage | A numbered strip with key markers, selected ranges, directions, and long unanchored tails. Clicking a row highlights its range; grouped and independent selections remain distinct. | Medium |
| 4 | Organize settings by task and relevance | Basic/Advanced sections, searchable settings, and a “show settings for other engine” option. Explain why unavailable settings are disabled and whether they are remembered. | Medium |
| 5 | Alpha-aware preview and final-output inspection | Checkerboard/solid/alpha-only views and a static final-output viewer or contact sheet. Label synthesis preview versus final saved image explicitly. | Low–medium |
| 6 | Preset scope and change visibility | Show what a preset affects, mark changed-from-preset values, and preview differences before applying it. Preserve independent groups and version compatibility. | Medium |
| 7 | Recovery/result dashboard | List recent batches with status, marker state, output location, settings, and recovery action. Explain changed/missing paths and allow deliberate validated relinking. | Medium–high |
| 8 | Resource/cache controls | Show cache size/location and estimated scratch use; provide validated idle-only cleanup and “recompute this job's flow/edges.” This also addresses the two absent FuouM recompute choices. | Medium |
| 9 | Small quality-comparison runs | Let users queue a short selected frame range with two or three named settings presets and produce a static contact sheet/manifests. Record comparisons instead of promising universal “best” values. | Medium |
| 10 | Other advanced parity | Consider Legacy stop threshold. Native FuouM YAML import belongs here if exchanging upstream configs is a real use case. Edge tuning/preview is now the user-selected next feature described above. | Medium–high |

### Suggested settings organization and wording

Keep the current familiar dark/teal appearance. The strongest improvement would be
clearer grouping and less technical material in the first view, rather than a new
theme or framework.

For Rendering, use Basic sections for Engine, Quality, Processing size, Style
guidance, Masks/Transparency, and Outputs. Put patch-search schedules, pruning,
solver details, modulation, optional flow models, and runtime paths in Advanced
sections. Preserve every saved value when a section is collapsed or hidden.

Consider these labels, keeping native names available in tooltips:

- **Independent keyframe passes** and **Blended sequence** make the two video
  workflows clearer than relying on users to infer the difference from tabs.
- **Flicker reduction (warped-style guide)** can explain Deflicker while retaining
  your familiar label. It should not promise equivalence to EbSynth Beta.
- **Draft / Standard / Automatic-depth** descriptions can clarify the existing
  Preview/Standard/Highest profiles. “Highest” currently differs from Standard by
  automatic pyramid depth; it is not guaranteed to be best for every shot.
- **Automatic based on available GPU memory** is clearer than a bare zero in the
  concurrency field. Keep manual maximum as a separate choice if redesigning it.
- **Preserve supplied keyframes exactly** should explain that optional compositing
  follows, while **Transition-aware** should explain the adjacent-frame handoff.
- A render preset summary should distinguish values it changes from processing
  size, output destination, and grouped/image settings it leaves alone.

Do not alter rendering defaults merely to make them appear more aggressive. Keep
Original resolution, Standard quality, optional parallel execution, and the current
engine default unless explicit comparisons justify a product change. Present
memory-efficient flow and disk storage as separate tools: one addresses flow GPU
cost; the other addresses retained clip arrays in RAM.

### Appearance and interaction details

The GUI currently opens at 1320×820, has six functional tabs, a dark palette, custom
spin/toggle painting, input and output panels, a queue, and status/progress areas.
Rendering and Settings are scrollable. Preserve the compact logo/tab row and the
control consistency you explicitly requested.

Useful incremental changes:

- A persistent compact job summary near the Run controls, so users do not have to
  revisit several tabs to confirm engine, size, workflow, and output.
- Equal label spacing and section hierarchy; warnings next to the affected
  setting, while retaining detailed logs for investigation.
- Keyboard shortcuts for project open/save, scan, preview, and starting a job;
  clear focus indication and accessible names for icon-only controls. Some
  accessible names already exist, so extend and test rather than assuming none.
- An optional larger-control/text density mode and checks at common Windows
  scaling levels. Qt 6 already supports per-monitor DPI scaling; test custom
  drawing and layout rather than adding ad hoc coordinate scaling.
- Checkerboard and selectable solid backgrounds in preview, because the current
  `PreviewTile.paintEvent` fills a fixed dark background, which can obscure the
  meaning of transparent output.

The accessibility/scaling suggestions are consistent with Qt's official
[QWidget accessibility guidance](https://doc.qt.io/qt-6/accessible-qwidget.html)
and [High DPI documentation](https://doc.qt.io/qt-6/highdpi.html). They are proposed
verification/improvement work, not a finding that the existing GUI fails those
standards.

### Workflow automation worth considering

The existing discovery/auto-start features handle one selected pair. A separate,
explicit batch-import action could collect several matching shots and let the user
review their keys/ranges/presets before running. That would extend the current
automation without silently rendering every discovered directory.

Other useful automation includes a source/key/mask contact sheet; warnings for
large gaps between styled anchors; a dry-run input/output check; opening the
specific completed job's output from its row; exporting a support bundle with
paths redacted on request; and rerunning a saved job with a new settings snapshot
into a fresh folder. A controlled path-relink dialog would make projects easier to
move between machines while preserving changed-input checks.

### Lower-priority or explicitly excluded additions

Direct video import/frame extraction and synchronized comparison playback remain
excluded by your documented preference. They are not recommended priorities here.
A static contact sheet is proposed as a distinct workflow, not as a disguised
playback implementation.

FastBlend or other upstream subprojects could be separate future features, but
they need an explicit workflow, dependency, memory, output, and validation plan.
They should not be represented as a few missing switches in the current grouped
renderer. Similarly, avoid exposing dormant FuouM fields or claiming a CPU FuouM
fallback merely because upstream names exist.

## 8. Suggested incremental sequence

1. Complete review and verification of the installer work already in progress;
   build/test the exact candidate on another Windows system.
2. Implement the user-selected advanced edge-tuning panel and Edge Preview
   described in section 7, immediately after the current installer work.
3. Add the read-only job summary and clearer preset scope/status indicators.
4. Add alpha-aware preview and static final-output inspection.
5. Add the keyframe/range coverage strip and warnings grounded in actual input
   identities, without changing propagation mathematics.
6. Add cache/resource management and reviewed multi-shot batch preparation.
7. Decide which remaining API features solve an observed need; implement one at a
   time with persistence, adapter mapping, and meaningful output verification.
8. Consolidate current capability documentation, keeping historical evidence but
   clearly dating/superseding old completion and test statements.

## 9. Source map and unresolved questions

Primary implementation references:

- `reezsynth_gui.py`: MainWindow, project I/O, job preparation, queue/process state.
- `reezsynth_options.py` and `reezsynth_config.py`: widget groups, defaults,
  validation, preset library, startup and last-used persistence.
- `reezsynth_project_controls.py`: folder history and output policy/templates.
- `reezsynth_jobs.py` and `ezsynth/aux_classes.py`: Legacy forwarding/RunConfig.
- `ezsynth/utils/_eb.py` and `ezsynth/edge_detection.py`: lower-level limits/hooks.
- `reezsynth_fuoum.py`, `reezsynth_fuoum_pipeline.py`, pinned
  `engine_sources/fuoum_reezsynth/ezsynth/config.py`: FuouM schema/adapter behavior.
- `reezsynth_grouped_controls.py`, `reezsynth_video_plan.py`,
  `reezsynth_image_controls.py`, `reezsynth_image.py`: the alternate workflows.
- `reezsynth_preview.py`, `reezsynth_preview_transport.py`,
  `reezsynth_alpha.py`, `reezsynth_video_export.py`: image/output behavior.
- `reezsynth_queue_recovery.py`, `reezsynth_precompute_cache.py`,
  `reezsynth_sequence.py`, `reezsynth_resources.py`: durable/reusable work and resources.
- `WORK_REMAINING.md`, `PROJECT_STATUS.md`, `EZSYNTH_PARITY.md`,
  `NUMERIC_SETTINGS.md`, `TRANSPARENT_KEYFRAMES.md`, `D3_OUTPUT_OWNERSHIP.md`,
  `D4_PRESET_ISOLATION.md`: plans, explicit policies, and recorded evidence.
- `PACKAGING.md`, `CLEAN_MACHINE_TEST.md`, `INSTALL_WINDOWS.md`,
  `RELEASE_AUDIT.md`: current distribution and validation boundaries.

Open product decisions, rather than prerequisites to reading this report:

- Does native FuouM YAML interchange matter in actual use, or is GUI-owned
  project/preset sharing sufficient?
- Is the next target primarily your established production workflow or new users
  with smaller GPUs and no developer tools installed?
- Would a keyframe coverage strip and static output comparison be more valuable
  to you than exposing additional low-level parameters?
- Should settings show all engines' controls, or default to the selected engine
  with an explicit option to reveal the rest?
- Which external Windows/GPU configuration will establish the next installation
  and stability baseline?

No application behavior was changed for this report. Recommendations remain
proposals, and recorded validation results retain their original scope.
