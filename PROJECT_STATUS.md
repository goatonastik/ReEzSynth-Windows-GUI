# Project status

Updated 2026-09-12. Live files are authoritative. Usage and settings are described
in [README.md](README.md).

## Local review fixes verified (2026-09-12)

- Durable queue recovery now writes an atomic journal before shared, isolated or
  parallel workers start and records each job transition. Recovery is explicit,
  skips completion markers, blocks changed job/input records, and preserves any
  partial output by restarting into a fresh sibling directory. An interrupted
  two-job lifecycle regression passed without overwriting its partial PNG. A real
  two-job parallel FuouM GUI render also completed on the RTX 5090; its audited
  journal reported two complete jobs and no input changes. Retained batch:
  `gui_controller_20260912_145553_068664`.
- Rendered-video export is implemented for both engines. Rendering settings and
  projects retain an enable switch, 0.1-240 FPS value and optional separate audio
  path. Workers encode an atomic H.264/AAC `render.mp4` after PNG/auxiliary saving
  and before `COMPLETE.txt`; metadata records frame range, count, FPS and audio.
  Exact frame limiting plus audio pad/trim prevents short audio from dropping the
  last video frame or long audio extending the container. Real three-frame legacy
  and FuouM frontend queues passed with 12 FPS audio, and FFprobe found three H.264
  frames, AAC audio and a 0.250-second container in both outputs. Retained reports:
  `engines_legacy_20260912_143716_372482` and
  `engines_fuoum_20260912_143745_358434`.
- Optional GPU blending is now validated on this RTX 5090. A quarantined CuPy
  14.2.0 environment using pinned CUDA 13.4 components passed the application's
  readiness kernel, histogram path, sparse construction and three-channel CuPy
  Poisson solve. A full frontend image/video/grouped queue then passed in 6.069
  seconds with clean worker exit; its grouped manifest records both GPU blending
  switches and `cupy-cuda13x 14.2.0`. Retained report:
  `engines_legacy_cupy_poisson_20260912_142956_596878`. The normal environment
  remains unchanged; `requirements-cupy-cuda13.txt` is an opt-in host-specific
  compatibility set, not part of default installation.
- Optional legacy flow validation is complete on this host. All three official
  EF-RAFT checkpoints from upstream revision `9ad323b` passed direct finite-flow
  checks and full Preview image/video/grouped jobs. FlowDiffuser's official 58.1 MB
  checkpoint (`a653fa…`) and exact Twin-SVT Large (`a8d1d6…`, 397.2 MB) and Small
  (`719c6f…`, 96.3 MB) backbones were validated. Upstream-required `timm 0.6.12`
  failed on Python 3.11; the tested set is `timm 1.0.29`, `huggingface_hub 1.31.0`
  and `safetensors 0.8.0`. A final normal-environment frontend run passed in
  10.480 seconds, followed by a forced-offline/empty-cache pass in 9.855 seconds
  (`engines_legacy_flow_diff_20260912_141903_774431`). Rendering now loads pinned
  local backbones and cannot trigger their former implicit network downloads.
- Legacy CPU and Auto were validated through real frontend jobs in separate
  CUDA-hidden workers. Each completed 256x144 image synthesis and a two-frame
  video; video logs confirmed CPU optical flow. Finite output/error data, exact
  shapes, completion, requested backend provenance and clean worker exits passed.
  CPU took 4.761 seconds and Auto 4.724 seconds for their two-job workers. Results:
  `diagnostic_outputs/backend_20260912_140820_787666`. Different output hashes are
  acceptable because the native patch search is not asserted deterministic.
  This does not replace a CPU-only installation/portability test.
- Implementation committed as `d66ad6a`. The requested ChatGPT review handoff
  was refreshed at `Z:\temp\reezsynth_frontend_handoff_d66ad6a`: 48 copied files
  plus a manifest, all source copies hash-verified. The older snapshot is intact.
- FuouM CLI benchmarks now recognize FuouM timing lines. Completion requires a
  zero process exit and `COMPLETE.txt`; missing timing lines no longer imply failure.
  FuouM call times are explicitly distinguished from end-to-end wall time.
- Legacy memory-efficient RAFT probes the loaded extension with a tiny real
  kernel instead of rejecting all custom builds outside the bundled GPU list.
  The Windows builder merges environment names case-insensitively and verifies
  the kernel after installation. Synthetic/custom-architecture regressions and
  the real RTX 5090 correlation/numerical checks passed. No rebuild was needed.
- Output manifests now include version 2 effective frontend settings, normalized
  guide weights, selected EF-RAFT/FlowDiffuser/RAFT/NeuFlow checkpoint hashes,
  relevant loaded native extensions, and expanded adapter/package provenance.
  Requested settings remain available separately. Native Auto backend decisions
  and geometry-dependent pyramid clamping are not introspected.
- Full maintained suite: **243 tests passed in 31.923 seconds**. This includes
  default dual-engine setup, queue recovery, optional-flow readiness and
  provenance, timing/completion tests, custom-kernel readiness, and metadata
  regressions. Expected upstream deprecation/offscreen Qt warnings remain; no
  maintained test failed. The two upstream root demo scripts are not unittest
  modules and retain hard-coded paths outside this checkout.
- New bounded 256x144 GPU smoke checks passed for image, three-frame video and
  grouped jobs, including previews, error arrays, frame numbering, completion and
  shared-worker exit. Legacy used compiled RAFT. Retained reports:
  `engines_legacy_20260912_130741_668680` (6.287 seconds) and
  `engines_fuoum_20260912_130759_922655` (5.799 seconds), under ignored
  `diagnostic_outputs/`. All six version-2 manifests were independently checked
  against the actual checkpoint/extension hashes. FuouM's real log now produces
  a successful timing summary. These are Preview smoke checks, not visual parity
  or isolated performance benchmarks; video auxiliary exports were not enabled.
- Six dependency-free developer snapshots were untracked and given exact ignore
  rules. Their local copies and Git history remain intact. Active application
  code, maintained tests/diagnostics, runtime assets and examples remain tracked.
- Corrected the older 1080p note: it did not test video auxiliary exports, and
  sampled GPU usage was device-wide, not a process-specific peak. The parity
  review now clearly separates its historical snapshot from current evidence.

## Default installation of both engines (2026-09-12)

- Standard `setup_reezsynth.ps1` now installs both Trentonom0r3/Ezsynth and
  FuouM/ReEzSynth. FuouM remains in its separate runtime; the standard command
  invokes its installer with verified RAFT copies and all three pinned NeuFlow
  checkpoint downloads. Engine selection and saved project defaults are unchanged.
- Setup checks Git/CUDA 12.8/C++ build prerequisites before large package
  downloads, checks both engines in `-CheckOnly`, and records launcher settings
  only after both components succeed. Existing environments are preserved.
  Compilers/toolkit must be installed before a fresh FuouM native build.
- All 26 setup regressions passed, including ten new checks for default component
  orchestration, failure/no-overwrite behavior and compiler preflight. Conda/package
  installation is simulated in the orchestration tests. The real combined
  `-CheckOnly` passed against this host's existing engines, and a fresh-build
  prerequisite probe found Git, CUDA 12.8 and VS 2022 without creating its target.
  A new combined clean-machine installation has not been performed in this pass.
- The user selected the remaining enhancements listed in WORK_REMAINING.md,
  excluding direct video import and synchronized comparison playback. Those
  enhancements remain planned; default inclusion of FuouM is implemented.

## High-reasoning follow-through (2026-09-12)

Current checklist: [WORK_REMAINING.md](WORK_REMAINING.md). This section supersedes
older limitations/results below without deleting the historical record.

- Added FuouM masks/custom guides/exports/directional modes/NeuFlow and independent
  engine checkpoint controls. Saved disabled settings stay saved but are normalized
  out of effective jobs. Older LSMR presets retain LSMR rather than silently moving
  to LSQR. Effective solver/guide options and pyamg/einops versions enter manifests.
- Fixed two numerical/indexing bugs: forward/reverse synthesis errors must refer
  to the same output frame, and horizontal Poisson differences must not wrap rows.
  Supplied styled keyframes are retained before optional mask compositing; flat
  style histogram normalization is guarded against zero standard deviation.
- Fixed `git apply --unidiff-zero` and case-insensitive Windows Path/PATH handling
  in the build helper. A new upstream sparse checkout plus new worker venv at
  `diagnostic_outputs/install_verify_20260912/` passed dependency installation,
  pinned checkpoint downloads/checksums, full native compilation and import checks.
  This was a same-host install, not a clean-machine certification.
- Final full suite: **198 tests passed in 27.073 seconds**. Includes installer no-write
  plan/no-overwrite/checksum/patch tests, engine state/preset checks, and mathematical
  frame/gradient regressions. Original setup tests are preserved in their own file.
- Real FuouM settings run: `release_fuoum_20260912_112014_540827`, **42 jobs x 33
  frames** across three repeats. Includes every Poisson solver, SSD/NCC, masks,
  exports, directions and three NeuFlow checkpoints. Process-tree RSS settled
  around 1,753–1,790 MiB after warm-up; aggregate GPU memory before/after worker
  exit was 2,456/2,397 MiB. This is bounded plateau evidence, not proof of no leak.
- Painted comparison: `release_legacy_20260912_112513_463272` (18 video jobs x 33
  frames plus three retargeted images) and `release_fuoum_20260912_112731_611609`
  (six video jobs x 33 frames plus three retargeted images), at 384x216 video.
  All passed. Sampled aggregate GPU peaks: 3,276 MiB legacy / 3,140 MiB FuouM;
  before/after: 2,476/2,523 and 2,524/2,441 MiB respectively. Other desktop GPU
  users are included; these are not comparable isolated allocation benchmarks.
- Original versus compiled RAFT output mean absolute difference averaged 0.364
  byte levels (maximum per-frame mean 0.525) over the first 33-frame painted video
  pair. Native synthesis is nondeterministic: this is a descriptive output
  comparison, not a flow ground-truth accuracy test.
- Inspected `comparison.png` in the painted FuouM run at frames 105,106,107,110,111.
  Both retained the intended painted appearance in these samples; no obvious
  boundary break was seen. Temporal playback/user footage still needs artistic
  acceptance; adjacent-frame differences include real motion and are not flicker scores.
- Flat-color FuouM matrix: `release_fuoum_20260912_113146_066804`, 14 jobs x 11
  frames, all finite/valid across the solver and flow-model paths.
- Odd-sized FuouM matrix: `release_fuoum_20260912_113537_625894`, **19 jobs x 11
  frames at 257x145**. Also covers NeuFlow padding/cropping, PST/PAGE, RAFT Kitti,
  disabled temporal/sparse guides, and feathered masks without premasking. All passed.
- Higher-resolution FuouM check: `release_fuoum_20260912_113855_626280`, independent
  and grouped five-frame jobs at **1280x720**. Both passed; sampled aggregate GPU
  peak 5,198 MiB, before/after worker exit 2,477/2,477 MiB.
- Fresh-install render validation: `engines_fuoum_20260912_113708_726873` used the
  new source and new Python interpreter under `install_verify_20260912`, not the
  default installed engine. Image/video/grouped outputs, numbering, live previews,
  provenance and orderly shared-worker exit passed in 5.983 seconds.
- FuouM real GUI checks: three 60-frame parallel cycles, then three cancel/restart
  and three close cycles. Cancellation/close checks were strengthened and repeated
  to wait for a completed native synthesis call, not merely a stage label. Final
  runs begin at `gui_controller_20260912_113256_757423` through the close cycle at
  `gui_controller_20260912_113429_848927`. No stopped-job completion marker or
  retained controller worker; completed restart/parallel jobs produced outputs.
- Original-engine GUI validation also passed two 60-frame cycles each of parallel,
  cancel/restart and close, from `gui_controller_20260912_113748_717075` through
  `gui_controller_20260912_113850_256013`. Cancellation waited for a native result.
- Deleted only the redundant `.engine_envs/fuoum_install_check` environment created
  during installer debugging. It can be recreated; working engines and the final
  fresh-install evidence remain untouched and ignored.
- Optional legacy acceleration check: installed `cupy-cuda12x 14.2.0` only in the
  ignored `.engine_envs/cupy-validation` environment. Dependency consistency passed,
  but the first actual histogram-blending `repeat` kernel failed on RTX 5090 with
  `CUDA_ERROR_NO_BINARY_FOR_GPU`. No CuPy package was installed into the normal GUI
  environment. `check_blend_dependencies` now executes that minimal kernel before
  queue creation and turns the failure into a clear disable/update message. Focused
  grouped/CPU-Auto adapter regressions passed. Revisit when a compatible CuPy build
  is available; this is not a successful GPU-blending validation.
- Qt Multimedia loaded the bundled `assets/complete.wav` with `Ready` status. That
  verifies decoding and the notification routing tests pass, but audible output
  remains an interactive Windows check.
- Interactive Windows check: the user heard the completion sound on queue finish,
  confirming audible playback of the configured notification path.
- Runtime environments, checkpoints downloaded for diagnostics, generated renders
  and logs remain ignored. `.gitattributes` archive exclusions were tested in
  memory with `git archive --worktree-attributes`: developer snapshot/backup absent,
  frontend source and base license retained. No public release was made.

See [RELEASE_AUDIT.md](RELEASE_AUDIT.md) for asset/license findings, the optional
engine installation architecture, and the unresolved external release gates.

## Dual-engine integration and highest-risk validation (2026-09-12)

The current completion checklist is [WORK_REMAINING.md](WORK_REMAINING.md).
Sections following this update contain historical checkpoints; their pending
claims should be read against this update and the current checklist.

- Added the Rendering engine selector: Trentonom0r3/Ezsynth remains the default;
  FuouM/ReEzSynth uses a separate Python worker runtime and a pinned upstream
  checkout at aaa8d06170e6cc59054410aa9c422edd789f7ab2. Both package namespaces
  are isolated; attempting to reuse a worker across engines is rejected.
- Added FuouM image, independent video and normal grouped blending adapters,
  native setting mappings, temporal NNF/sparse-feature controls, preview delivery,
  original output numbering, and early rejection of unsupported video controls.
  Projects/presets/jobs record engine identity and revision; output manifests
  include source/native/checkpoint hashes, adapter hashes and package versions.
  Both queue modes and CLI benchmarks launch the selected Python executable.
- Built and imported FuouM's native CUDA extension on RTX 5090 using the existing
  PyTorch 2.11.0+cu128, CUDA 12.8 and VS 2022 toolchain. A tracked compatibility
  patch changes three CUDA-facing includes to torch/types.h. NumPy 1.26.4,
  OpenCV 4.11.0.86 and FuouM-specific packages live in .engine_envs/fuoum; the
  existing environment still has NumPy 2.4.6 and OpenCV 5.0.0.93. The FuouM
  environment passed pip check. Its venv shares the parent PyTorch installation.
- Removed conflict markers and duplicate identical branches from the older
  ezsynth/utils/flow_utils/alt_cuda_corr sources. The supported RAFT build already
  used clean third_party sources. No RAFT algorithm change was made.
- Final full explicit regression suite: **187 tests passed in 25.213 seconds**.
  Includes engine/revision persistence, capability failures, namespace isolation,
  strict parameter mapping, grayscale guides, shared/parallel routing and the
  existing frontend, lifecycle, artifact, serialization and CPU RAFT tests.
- Real FuouM image/video/grouped jobs passed through one persistent worker in
  9.790 seconds, including previews, error-map validation and orderly exit.
  Aggregate GPU memory was 2180 MiB before and 2174 MiB after. Evidence:
  diagnostic_outputs/engines_fuoum_20260912_020034_577481/.
- Matching original-engine image/video/grouped jobs passed in 6.196 seconds,
  with aggregate GPU memory 2082 MiB before and after. Evidence:
  diagnostic_outputs/engines_legacy_20260912_020233_020178/.
- Real offscreen FuouM GUI cancellation/restart and two-job parallel rendering
  passed using copied bundled inputs and temporary QSettings. No matching worker
  processes remained after the diagnostics. Small video/image outputs and the
  Rendering layout were inspected; this is not general visual-quality parity.
- Three-frame **3840x2160** original-engine rendering with compiled memory-efficient
  RAFT and Preview settings passed in **10.171 seconds**. Sampled aggregate GPU
  memory peaked at **10747 MiB**, returning from **2142 MiB to 2142 MiB** after
  worker exit. Output shape/content, frame numbering and previews passed. Evidence:
  diagnostic_outputs/engines_legacy_20260912_020414_528713/.
  These short measurements include other GPU users and are not production
  benchmarks, exact process-allocation peaks, or long-duration leak tests.
- FuouM masks, custom edge sequences, video auxiliary exports, grouped directional
  modes, CuPy blending and additional flow architectures remain unmapped and are
  rejected explicitly. Native audible notification playback remains a manual check.
  Setup, capabilities and build reproduction are documented in DUAL_ENGINE.md.
- The source checkout, worker venv, native build and diagnostic outputs are local
  ignored artifacts. Existing user changes were preserved. No commit or push.

## Numeric audit follow-up

- [NUMERIC_SETTINGS.md](NUMERIC_SETTINGS.md) inventories the frontend ranges,
  engine constraints and remaining policy/precision limits. Defaults are unchanged.
- Fixed a patch-size validation gap: the live wrapper needs processed style and
  target dimensions of at least `2 * patchsize + 1` for one usable pyramid level.
  Video and image adapters now reject zero-level combinations before constructing
  an engine; single-frame keyframe copies still bypass synthesis restrictions.
- Fixed the preview-limit editor to offer only the accepted 1–64 range. Previously
  it could produce values the application validator rejected. Regression coverage
  includes persistence and stepping at both bounds.
- Video and Image Synthesis floating-point editors now retain six decimal places.
  Last-used settings regression coverage confirms guide-weight and diversity values
  survive a GUI restart at that precision. Frontend range caps and advanced
  per-level engine inputs remain documented policy/API limitations.
- Latest full isolated suite: **173 tests passed in 26.387 seconds**. It includes
  the new six-decimal round-trip regression, boundary checks
  against the live wrapper calculation, image/video adapter tests, GUI/worker
  lifecycle, preview transport, presets and CPU RAFT comparisons. No GPU render,
  dependency installation, engine-source edit, commit or push was performed.
- The user's completed CLI benchmark used identical job data apart from output
  location (verified directly). CLI synthesis: 216.235s versus GUI 223.338s; CLI
  process wall time: 239.706s versus GUI 246.763s. Both processed 155 synthesis
  transitions. Preview capture was 0.011s versus 2.901s. This one pair shows a
  small measured difference; it does not establish the earlier slowdown's cause
  or prove the remaining difference is normal timing variation. Both paths use
  the same frontend renderer adapter; this is not a pristine-upstream comparison.

## Live-preview repair and performance investigation

- Earlier preview attempts only emitted images during final saving and the
  parallel worker reader dropped preview payloads. The adapter now publishes a
  bounded thumbnail immediately after each native synthesis call, identified by
  the style and video-guide array identities. Shared, isolated, grouped, masked,
  single-frame and image paths are covered without modifying engine sources.
- Capture uses a short request lease refreshed only while the window is open.
  Hidden windows do no image capture/decoding; closed/crashed windows stop renewing
  the lease. Fixed latest-frame paths are loaded from fresh bytes, avoiding Qt's
  filename cache. Old widgets are disposed between queues; hidden pixmaps are freed.
  Active later jobs replace earlier completed tiles when the preview cap is reached.
- These are synthesis previews before final masking/blending, not final output
  frames. Final PNG content and resolution are unchanged. No real GPU render was
  run for this fix. CPU mocks exercise the live upstream sequence/pass methods.
- The user's recent job files (12:28–13:31 on 2026-09-11) have matching effective
  synthesis settings at 1920x1080 Standard. Current application preferences enable
  two parallel workers, but there is no comparable earlier timing evidence proving
  the cause of the reported increase in seconds per frame. Settings were not altered.
  Effective settings, per-frame native EbSynth/between-call times and preview-capture
  totals are now logged for comparison.
- Reviewed the user's saved session log from the 13:50 run: one keyframe job,
  155 synthesis calls, 1920x1080 Standard, CUDA EbSynth, dense RAFT correlation.
  It completed successfully in 246.763 seconds including startup/output/exit.
  The synthesis loop took 223.338 seconds (1.441 seconds per synthesized frame):
  native EbSynth 174.324 seconds, between-call work about 46.071 seconds, and
  preview capture 2.901 seconds (18.7 ms/frame, 1.3% of the loop). This measures
  worker capture, not GUI image decoding. Parallel mode was enabled but this queue
  had only one job. No earlier timing baseline establishes the reported regression.
- The live-preview note now shares the Layout dropdown row, aligned right and
  wrapping when the window narrows. Nine existing GUI-construction/preview-window
  tests passed; offscreen headers were reviewed at widths 900 and 480, including
  the longer preview-cap notice. This layout change does not alter the renderer.
- `benchmark_current_gui_settings.bat` now provides an apples-to-apples direct
  CLI timing comparison without overwriting a GUI output. It finds the last
  completed job in the saved `reezsynth-session.log` (or accepts a job JSON path),
  clones its exact job data to a unique sibling `*_cli_benchmark_###` directory,
  and launches `reezsynth_jobs.py job.json` in a fresh process. Its
  `cli-benchmark.log` retains the same per-frame timing lines, an automatic timing
  summary, and direct CLI wall time. Unit coverage verifies final-log selection,
  lossless job cloning apart from output destination, collision handling, and
  dry-run behavior. The user has completed a GPU benchmark through this tool;
  measured results are recorded above.
- Validation: **148 tests passed in 21.230 seconds**, including 12 new preview
  tests. They check emission before sequence saving, pixel-identical mock final
  outputs with capture on/off, masked array identities, hidden/expired capture,
  same-path image refresh, cap rotation/widget disposal, and real QProcess routing
  in shared/isolated/parallel modes with cancellation/restart. Offscreen layout
  images were reviewed using the installed Segoe UI font. Real GPU performance
  recovery is not established by these tests.

## Pending local changes: processing sizes, live previews, and supported model/backend choices

- Processing size now offers Original resolution (default), 512/1024 square,
  720p/1080p landscape or portrait, and Custom width/height. Preset dimensions
  are locked and Custom is editable. Exact selected dimensions reach both video
  and Image Synthesis jobs. Legacy width-limited projects, presets and QSettings
  retain their max_width semantics through a compatibility-only dropdown entry;
  they no longer migrate to square sizes. Image source/target aspect ratios are
  preserved independently. Original shows header dimensions, Custom is editable,
  and fixed size fields remain locked after completion/cancellation.
- Rendering controls now expose the locally supported RAFT Sintel (default) and
  Kitti weights, plus CUDA (default), Auto and CPU native EbSynth backends.
  The backend choice is forwarded to both video and Image Synthesis. CPU EbSynth
  does not disable PyTorch CUDA optical flow in video jobs. Without CUDA, CPU/Auto
  jobs can use CPU flow with Classic edges and GPU-only features disabled. This
  removes an unconditional CUDA rejection; native CPU/Auto execution is unverified.
  Automatic pyramid depth (-1) is now available, persisted and forwarded.
- Rendering contains Preview, Standard (default), and Highest quality profiles.
  These change only the synthesis controls in that tab; Highest is Standard with
  automatic pyramid depth. Processing size, output naming, and Blend / Flow are
  retained. The Previews window now shows frames during synthesis (see repair above),
  with queue-pair or shape-aware grid layout and a default cap of eight images.
- Preset dropdowns now cover Directories, Output naming, Guide weights,
  Rendering, Blend / Flow, Application, and Image Synthesis. Each contains an
  always-available built-in Default profile. Settings has a confirmed reset-all
  action that restores those values without deleting projects or custom presets.
- No `ezsynth/` source, model weight, runtime dependency or GPU render changed.
  Full explicit lightweight suite: **148 tests passed in 21.230 seconds**. New focused
  regressions cover the header, busy-state log export, sequential run boundaries,
  width-limit compatibility, Original dimensions, automatic pyramid depth and CPU
  adapter forwarding. GUI construction/tab display also passed in the separate
  reezsynth-setup-check environment with temporary settings. Current changes
  remain uncommitted pending review.
- The Processing size popup presents the resolution at left and aspect ratio at
  right. Queue-style arrow columns now cover standard integer and decimal spin
  controls throughout the interface, and the shared checkmark painter covers
  regular checkboxes. Diagnostics retains the entire open-session log, marks each
  queue's start and end with 96-character separators, and can save the visible
  session text to a log file.
- Logo and tabs now share the top header. Save Log is at the right and stays
  enabled during renders; saving does not replace render progress/status. Queue
  numbers increase once per run and parallel timing is labeled correctly.
  Dropdown arrows use shared SVG geometry and state colors through the global
  stylesheet (Qt stylesheets bypass the proxy's combobox painter). All tabs and
  the size popup were inspected offscreen at 1320x820 using temporary inputs.
- Selected Sintel/Kitti RAFT weights are checked before a multi-frame video queue
  creates outputs or starts a worker. Single-frame copies skip this check in both
  GUI and worker. Both tracked weight hashes are included in the
  runtime asset manifest and therefore checked by the installation diagnostic.

Remaining priorities: address the documented numeric-domain/precision limitations;
obtain and validate optional EF-RAFT/FlowDiffuser assets; validate real GPU/CPU
rendering, output quality and memory cleanup; review repository distribution and
publish with approval.
Automatic pyramid depth is implemented, but the remaining frontend numeric bounds
are inventoried in NUMERIC_SETTINGS.md and are not full arbitrary-parameter parity.

## YAML interchange

- Projects and preset libraries now support safe YAML import/export alongside the
  existing JSON default. Both formats use the same versioned schema and validation;
  render job files and worker messages remain JSON. PyYAML 6.0.2 is pinned for the
  reproducible Windows setup and installed in the working environment.

## Optional flow readiness

- `check_reezsynth.py --flow-extras` now checks EF-RAFT and FlowDiffuser
  requirements without importing their models, loading weights or initializing CUDA.
  It reports each missing EF-RAFT weight and the FlowDiffuser `timm` dependency and
  weight separately. The normal setup check deliberately does not enable this flag:
  these optional assets are not bundled and their absence must not fail a standard
  RAFT installation.
- Tests use temporary placeholder files and a mocked dependency lookup. EF-RAFT and
  FlowDiffuser remain unavailable in the working environment; no download, install,
  engine edit or render has been performed for them.

## Optional flow architecture selection

- Rendering now persists a video-only flow architecture (`RAFT`, `EF_RAFT`, or
  `FLOW_DIFF`) and presents only models supported by that selection. RAFT/Sintel
  remains the Default preset. The job adapter forwards both fields to the existing
  `EzsynthBase` API; it does not alter `ezsynth/` source.
- Every multi-frame queue performs a no-GPU preflight for the selected checkpoint;
  FlowDiffuser also checks for `timm`. This happens before a batch/output directory
  is created. Memory-efficient correlation is intentionally restricted to standard
  RAFT, where the compiled correlation extension is compatible.
- Settings has an Optional flow components panel with current readiness, safe
  checkpoint import buttons, and an explicit-confirmation installer for `timm`.
  Selecting an unavailable optional architecture immediately returns to RAFT and
  explains the missing setup rather than allowing an invalid option to persist.
- Focused GUI, setup and renderer-adapter regression suite: **77 passed in 8.649
  seconds**. Optional models remain uninstalled and no real render was run.

## Adapter constructor compatibility

- The video adapter excludes all frontend-only controls, including custom edge
  guides, before constructing the live `RunConfig`. A strict mock matching the
  live constructor signature now guards this boundary; the custom-guide path
  cannot silently pass an unsupported keyword to real rendering.
- Optional model/package installer buttons are part of the normal locked-control
  set and are disabled throughout an active queue, preventing environment changes
  while rendering.

## Distribution audit follow-up

- Generated diagnostic image paths and `diagnostic_outputs/` are now ignored.
  Existing tracked `output_synth/` images and example assets were preserved for a
  later provenance/release decision; ignore rules do not remove tracked files.
- The non-render setup check passed in the working environment: dependency
  consistency, four pinned runtime hashes, RTX 5090 CUDA availability, the
  EbSynth DLL entry point, the bundled correlation extension, and isolated Qt GUI
  construction. It did not load a model or perform synthesis.
- `diagnose_reezsynth_adapter.py` provides an opt-in small real-render check for
  the frontend adapter, including masks and custom edge guides. It uses bundled
  examples at 512×288 and writes only ignored diagnostic output.
- Real local checks on 2026-09-11 passed: direct three-frame CUDA video synthesis
  (1.847 seconds including initialization); frontend adapter video with masks and
  custom edge guides (three 512×288 PNGs and `COMPLETE.txt`); frontend Image
  Synthesis (image, error map, manifest and `COMPLETE.txt`); and grouped normal
  blending with two keyframes (three 512×288 PNGs and `COMPLETE.txt`). The native
  EbSynth CPU and Auto diagnostics also completed in 0.167 and 0.277 seconds.
- The same masked/custom-edge video job also passed through the real persistent
  worker: it emitted the expected `job_done` event, accepted `quit`, completed
  Python cleanup, and exited normally in 9.683 seconds. The opt-in diagnostic's
  `--shared-worker` mode now verifies that protocol path without opening the GUI.
- The real shared-worker diagnostic also verified live preview transport using a
  renewable GUI-equivalent request lease. It emitted two synthesis-stage preview
  events and produced the latest thumbnail before final output saving; capture
  took 0.025 seconds across the two calls. This validates renderer/worker preview
  delivery, while an interactive GUI-window render remains a separate manual check.
- The `--reuse-worker` diagnostic sent two independent 512Ã—288 video jobs to one
  persistent worker and verified both outputs and completion events before one
  orderly shutdown. Each job still constructed its own engine; on this small run,
  engine initialization was 0.178 seconds for the first job and 0.070 seconds for
  the second. This is a protocol/cache observation, not a production benchmark.
- The `--cancel-worker` diagnostic used 24 consecutive small frames, force-killed
  the real worker immediately after its synthesis-start event, and verified no
  `COMPLETE.txt` marker was written. It returned in 4.029 seconds. A forced stop
  may skip Python cleanup by design; process exit is the final resource boundary.
- The `--parallel-workers` diagnostic ran two independent 512Ã—288 masked/custom
  edge jobs concurrently through `reezsynth_jobs.py`, the same isolated-job entry
  point used by the parallel queue. Both wrote valid output and `COMPLETE.txt` in
  5.395 seconds. The GUI's QProcess coordination still has its separate mock
  lifecycle coverage; this verifies the two real renderer processes together.
- `diagnose_reezsynth_gui.py` passed a real offscreen MainWindow run with copied
  bundled inputs and temporary QSettings. It opened the Preview window, received
  a synthesis-stage tile through the GUI's QProcess output handling, found the
  completed output marker, and verified that the worker and UI both finalized.
- Its `--parallel` mode also passed with two real 512Ã—288 jobs and a two-worker
  limit. It verified the controller selected `ParallelQueue`, both completion
  markers were written, a preview tile arrived, and the UI unlocked after both
  QProcesses finalized.
- Its `--cancel` mode passed a real GUI Stop Queue path: it waited until a longer
  small shared-worker job entered synthesis, force-killed the worker, verified
  asynchronous UI/process finalization, and found no `COMPLETE.txt` marker.
- Its `--close` mode passed the real close-during-render confirmation path. The
  window stayed alive while its worker was stopped, then closed after asynchronous
  finalization; no `COMPLETE.txt` marker was written.
- Its `--cancel-restart` mode passed a real cancellation followed by queue rebuild
  and successful restart in the same GUI window. The stopped run had no completion
  marker; the fresh run created one after the previous worker finalized.
- GPU memory cleanup remains unmeasured. ComfyUI was using most of the RTX 5090
  during the checks (about 1.3 GiB free), so post-render memory readings cannot be
  attributed to ReEzSynth. Real GUI preview, parallel-worker,
  cancellation and restart checks remain pending with the GPU otherwise idle.

## Custom edge-guide sequences

- Video / Keyframes now includes an optional Custom edge guides directory and
  Rendering includes a matching checkbox. Enabled jobs require one numbered,
  same-size edge image per selected source frame, skip automatic edge computation,
  and assign the validated grayscale sequence through the engine's `edge_guides`
  hook. The setting is saved in render presets; the directory is saved in directory
  presets and projects. Automatic edge generation remains the default.
- Validation: **164 tests passed in 29.518 seconds**. The custom edge tests use
  a fake engine and synthetic numbered files; no GPU render was run.

Earlier real-render report: 3840x2160 video on RTX 5090 failed in RAFT CorrBlock
with a 62.57 GiB allocation request against 31.82 GiB total VRAM. This is a
per-frame-pair correlation allocation, not evidence of a worker-cache leak.
The adapter now logs actionable resolution guidance on CUDA OOM while preserving
the exception and failed-job behavior. Original remains the default; no automatic
resizing, engine changes or real GPU reruns were performed for this diagnostic fix.

## Memory-efficient correlation and OOM popup

- Added opt-in `memory_efficient_raft` rendering setting, saved through existing
  presets/projects. Old projects default off. Video only; no output downscaling.
- Following the user's slow-render report, the setting now selects compiled
  `alt_cuda_corr`. The former PyTorch chunk implementation is reference/test code
  only; missing extensions fail explicitly rather than silently falling back.
  Worker-scoped CorrBlock override restores the original implementation even on
  failure; upstream engine files and native backend forwarding remain untouched.
- Pinned upstream source/license in third_party/raft_alt_cuda_corr, with tensor
  validation, current CUDA stream/device support and Windows compilation fixes.
  `build_reezsynth_corr.py --install` built and installed version 0.2.0 into the
  test and working environments. CUDA 12.8.93, MSVC 14.43, Python 3.11,
  PyTorch 2.11.0+cu128, RTX 5090/sm_120. No other packages were changed.
- Version 0.2.0 is bundled in `wheels/` with cubins for 7.5, 8.0, 8.6, 8.9 and
  12.0. `setup_reezsynth.ps1` installs its hash-pinned wheel after PyTorch and
  validates loading before reporting setup complete. Fresh Windows users do not
  need CUDA Toolkit or Visual Studio for these supported configurations.
- CPU comparisons cover fractional/outside coordinates, batch size 2, four levels,
  radius 4, chunk boundaries, and a small random-weight RAFT forward pass. Tests
  establish numerical agreement within tolerance, not real-video quality parity.
- Conservative exception-line classification triggers a nonblocking GPU OOM popup
  once per queue. Mock subprocess tests exercise shared/isolated/parallel failures,
  cleanup with popup open, duplicate suppression and successful restart.
- GPU checks passed in both environments: native correlation vs all-pairs at
  subpixel/outside coordinates and partial thread blocks, batches/channels,
  nondefault CUDA stream, invalid input rejection and a random-weight full-size
  RAFT architecture forward comparison (128x128, 3 iterations).
- Synthetic 4K-equivalent (480x270 feature map, 256 channels, 4 levels/radius 4)
  lookup: former PyTorch 0.3679s, compiled 0.0453s (~8.1x). Peak allocated memory
  797.8 vs 1207.4 MiB. Compiled mode avoids the 62.57 GiB all-pairs table; these
  timings/memory figures exclude the rest of the render. Check script records
  setup and lookup separately; measured after one warmup, average of two calls.
- Full explicit suite: **115 tests passed in 14.345 seconds**. The added setup
  regression verifies the bundled wheel's installer hash and runtime manifest.
  No real GPU render,
  pretrained model loading, commits or pushes for this feature.
  Next manual check: short 4K video with the option on, parallel off; measure peak
  VRAM, completion and speed, then compare feasible-resolution output with the
  default mode. Memory needs in other render stages remain unverified.

## Consistent control styling and launcher warning

- `reezsynth_widget_style.py` shares the queue arrow/checkmark painters. Weight
  editors retain QDoubleSpinBox typing/signals but use full-height queue arrows.
  Standard checkbox and item-view indicators use the same teal tick at 14px;
  queue toggles retain their larger size. Main application and test fixture install
  QueueStyle over Fusion. Image-synthesis weight editors use the same arrows.
- 67 relevant GUI/options/destination/image tests passed, plus manual offscreen
  stepping, min-bound, busy/unbusy and 1320x820 visual checks.
- With user approval, base Conda chardet was changed from 7.6.0 to 5.2.0 to satisfy
  Requests 2.31.0. Importing Requests with warnings treated as errors and launching
  the working environment through Conda now pass. ReEzSynth packages were unchanged.

## Reproducible Windows setup

- `INSTALL_WINDOWS.md` and `setup_reezsynth.ps1` provide a dedicated Python 3.11
  environment with pinned direct packages, explicit CUDA 12.8 PyTorch wheels and
  working-snapshot constraints. Setup refuses existing environment names and
  supports preview/check-only modes. It never downloads models or renders.
- Successful setup saves ignored local Conda path/environment files for the
  launcher; active environments use their exact Python executable.
- `check_reezsynth.py` checks imports, dependency consistency, runtime hashes,
  CUDA availability, DLL entry point and isolated offscreen GUI construction.
  Asset hashes identify this checkout, not upstream provenance.
- Clean installation into `reezsynth-setup-check` succeeded, including all
  diagnostics, the existing 102-test suite and five new setup tests (asset checks,
  launcher environment selection/argument forwarding and non-mutating preview).
  The separate test environment is
  retained for validation; the working `reezsynth` environment remains intact.
- Compatibility with other GPUs and real rendering from a clean installation
  still require manual checks. Engine files were not changed.

Latest default/validation change: Original resolution (max_width=0) is now the
default in the GUI, startup defaults, missing render-preset size and naming preview.
Explicit saved sizes remain respected. `validate_video_dimensions` reads headers
for selected source frames and keyframes before output creation/worker startup
when Original resolution is selected. Errors include the mismatched filename,
actual size and expected source size. Applies to independent and grouped video;
the existing worker-side validation remains in place at every processing size.
Image Synthesis continues to permit different source and target dimensions.
Validation: full lightweight suite passed, **102 tests in 8.844 seconds**, including
mismatched key/video rejection before startup in both video modes and saved-size
restoration. No GPU renders or engine-file changes.

## Image Synthesis implementation

- The tab now supports style/source/target image selection and file drag/drop,
  additional weighted guide pairs, independent style/primary weights, an output
  subfolder, Synthesize Image, Stop, project controls and Open outputs.
- `reezsynth_image.py` owns Qt-free validation and the image adapter;
  `reezsynth_image_controls.py` owns its controls. render_job(job_path) dispatches
  the new image_synthesis job type. Engine files remain unchanged.
- Source/style dimensions must match; target dimensions may differ but must agree
  across all pairs. Pair channel counts must match, total guide channels <=24.
  Only 8-bit inputs are accepted. Style grayscale is expanded to BGR and alpha is
  discarded; guide channels are preserved. Width limits resize source and target
  groups independently. Image output uses target dimensions and three channels.
- ImageSynthBase uses shared synthesis/quality settings and CUDA EbSynth, with a
  fresh guide list on every call to avoid upstream's mutable default. Image jobs
  do not use video masks, flow or generated guides. Numerical error data is stored
  losslessly in error.npy; image.png and image_manifest.json must also save before
  COMPLETE is written. The image adapter does not initialize RAFT models.
- Image presets and startup restore use the existing separate preset storage.
  Projects optionally save image_synthesis data. Image-only saves set project_mode
  to image and permit empty video folders/rows; older projects retain video behavior.
- Image runs share queue startup, process management and cancellation with video.
  Output destinations use the style/target folders for input-relative locations.
- Full suite: **100 tests passed in 8.090 seconds**. After adding the tab's Stop
  button, all 12 image-specific tests passed again. Tests cover real upstream run
  orchestration with native computation mocked, image dimensions/channels, weight
  forwarding, outputs, save failure, presets, project compatibility, all worker
  modes, failure/cancellation/restart and closing. Layout checked at 1320x820.
- No GPU renders, dependency installations, commits or pushes. Real CUDA output
  quality, memory and speed remain unverified. Next parity work: model/backend
  selection and remaining advanced controls, then YAML configuration support.

## Input weights and output destinations

Latest adjustment: visible guide controls are Mapping, Deflicker, Diversity in
that order. Default quality is now Standard. The user requested restoring Ezsynth
weights after temporarily choosing video weight 4: video 6, Mapping 2 and
Deflicker .5 come directly from local Ezsynth RunConfig defaults
(img_wgt, pos_wgt, wrp_wgt), not EbSynth Beta defaults. Explicit saved values remain
unchanged. The video adapter still requires CUDA and selects the CUDA EbSynth
backend; disabling GPU blending is not a CPU-only render switch. Detail controls
are Preview/Standard and individual patch/pyramid/iteration/polishing settings,
not an implementation of Beta's named synthesis-detail levels.

Layout follow-up: key/video/mask weights now share their directory rows, in a
90-pixel column immediately before Select. The Masks checkbox replaces the old
optional label. Remaining Guide weights and their preset selector sit underneath
the directories. Removed the inclusive-stop and independent-job explanation block.
The 53 GUI/options/destination tests passed; layout visually checked at 1320x820.

Further layout update: the four naming suffix checkboxes occupy one line.
Diversity and Edge guide swapped visible locations: Diversity is below the
directories, Edge guide is in Rendering. Preset/schema membership is unchanged.
Custom output (label, field and Select) is visibly gray and disabled unless Custom
folder is selected; it remains locked while rendering. 53 relevant tests passed
again (3.322 s), plus manual offscreen enable/disable and 1320x820 layout checks.
Rendering settings serve both independent video and grouped Blend / Flow jobs;
Image Synthesis now has its own active rendering path; see the implementation above.

- Output naming now sits to the right of the directory inputs. Removed the two
  batch/time explanatory messages. A per-run checkbox can disable batch folders.
- New destinations: outputs/ inside keys or video, the parent of either folder,
  project folder, or custom folder. The user confirmed that “root” means parent.
  Legacy project/renders remains the default. Colliding job folders are suffixed
  even without batches; saved project and rendering-preset data retain the choices.
- Key/video/mask-guide weights and Enable masks are on the directory panel.
  Key weight (default 1, minimum .001) adjusts the native style-to-guide ratio by
  dividing all guide weights. Mask-guide weight (default 0) adds mask correspondence
  only when masks are enabled. Mask compositing is separately controlled by Enable
  masks. No changes to engine files; this is frontend adapter behavior.
- Mapping, Deflicker and Diversity label the related position-guide, warped-style
  and uniformity controls. These are not verified numerical equivalents to Beta.
- **88 tests passed in 6.484 seconds**, including destination selection, collision
  preservation, persistence, layout placement, weight normalization, mask guide
  forwarding with/without premasking, and disabling masks. Offscreen layout checked
  at 1320x820 using the installed Segoe UI font. No GPU rendering or dependency
  installation was performed; visual output of the new weights remains unverified.
- Include `test_reezsynth_destinations` in the explicit test command in README.

Full upstream feature parity is tracked in [EZSYNTH_PARITY.md](EZSYNTH_PARITY.md).
The renewed local review pinned Trentonom0r3/Ezsynth at b198f2d7051eee542c4efc51c2d43dc442630bbf,
confirmed the existing backend-forwarding differences, and reran all 66 tests
successfully (4.848 s). Grouped-video parity is now implemented with mock validation;
model/architecture selection remains pending. Image synthesis and auxiliary exports
are now implemented as described below.

## Auxiliary export update

- Optional Rendering checkboxes save numerical error/selection maps as lossless
  `.npy` arrays and upstream flow visualizations as `.png` images, for independent
  and grouped jobs. Defaults are off; projects, presets and last-used state persist
  the optional `exports` object. Older files receive disabled defaults.
- `reezsynth_artifacts.py` records original frame numbers, sequence positions and
  artifact meanings in `auxiliary/manifest.json`. It accounts for upstream boundary
  trimming and distinguishes blended selection masks from synthesis errors.
- Flow PNGs are normalized visualizations, not numerical vector data. A single
  source frame yields an empty manifest. Failed requested exports prevent COMPLETE.
- **81 tests passed in 5.887 seconds**, including exhaustive small-sequence mapping
  against live upstream methods with expensive computation mocked. No engine changes,
  GPU rendering, dependency installation, commits or pushes. Real export values and
  visual quality still require a GPU render check.
- Add `test_reezsynth_artifacts` to the explicit lightweight suite below; the README
  contains the complete current command.

## Grouped-video update

- Combined lightweight suite: **73 tests passed in 5.481 seconds**. No GPU renders,
  dependency installations, commits or pushes were performed.
- `reezsynth_video_plan.py` validates grouped ranges, keyframe subsets and blend
  settings, and computes synthesis work using upstream boundary rules.
- `reezsynth_grouped_controls.py` replaces the Blend / Flow placeholder. It uses
  separate ranges and names, leaving independent row definitions intact.
- The adapter passes multiple styles and relative indices to the existing engine,
  supports all three propagation modes and Poisson options, checks CuPy availability,
  and preserves original frame numbers in output. No engine files were changed.
- Projects optionally persist `grouped_video` and `blend_options`; old projects
  receive defaults. Render presets include blending options.
- Run `python -B -m unittest test_reezsynth_gui test_reezsynth_lifecycle
  test_reezsynth_worker test_reezsynth_options test_reezsynth_render_adapter
  test_reezsynth_grouped` (one command). The grouped tests execute live upstream
  sequence/pass methods with computation mocked, cover every keyframe combination
  for two through six source frames in all three modes, and check project/preset
  round trips, original output numbering, worker completion and cancel/restart.
- Real blending quality, CuPy execution and grouped GPU memory remain unverified.

## Working rules

- Working checkout: `D:\Downloaded\_software\Ezsynth-main (1)\Ezsynth-main`.
  Origin: `https://github.com/goatonastik/ReEzSynth-Windows-GUI.git`.
  Do not develop in an older sibling checkout.
- No AGENTS.md was found in this repository or its checked parent directories.
- Preserve engine code, runtime libraries, weights, user inputs/outputs, licenses
  and upstream attribution. Use companion modules, not versioned GUI subclasses.
- New numeric editors should use QueueSpinBox/QueueDoubleSpinBox from
  reezsynth_widget_style; keep QueueStyle and COMBO_STYLE installed for all tabs,
  dropdowns and checkboxes. Keep logo/tab header compact and Save Log available
  while busy. Tests must isolate QSettings and input/output data.
- Do not commit/push, delete project data, run destructive Git operations,
  install/upgrade dependencies or run expensive GPU renders without approval.

## Current implementation

- `reezsynth_gui.py`: consolidated PySide6 entry point, launched through
  `run_reezsynth.bat` and the existing reezsynth Conda environment.
- `reezsynth_project_controls.py`: folder history, remembered legacy setup,
  output templates, suffix toggles, validation and batch collision handling.
- `reezsynth_config.py`: frontend configuration validation, version-1 preset
  library storage and matching keyframe/video subfolder discovery.
- `reezsynth_options.py`: rendering controls, four preset groups, per-group
  startup choices, masks, discovery, automatic-start guards and notifications.
- `reezsynth_jobs.py`: input planning, mask validation and renderer adapter.
  Jobs now carry optional render_options, guide_weights and masks. Missing
  options preserve legacy Preview/Standard behavior. Engine code in ezsynth/
  was not changed; renderer adapter forwarding and mask loading were extended.
- `reezsynth_shared_worker.py`: unchanged protocol and cleanup; uses
  `render_job(job_path)` with no session argument. Each multi-frame job creates
  a new RunConfig/EzsynthBase. Do not explicitly share models across jobs.
- `reezsynth_parallel.py`: optional bounded isolated-process queue. Disabled by
  default; enabling uses a limit of 2 initially, with 0 meaning all queued jobs.
  Failures stop pending/active work, and cancellation waits for all worker exits.
- `assets/complete.wav`: generated, replaceable placeholder notification tone.

Sequential mode still defaults to worker reuse, honoring a saved false preference.
Between jobs it collects unreachable objects without flushing allocator caches.
Queue completion requests quit, drains streams and waits for process exit, with
30-second normal shutdown timeout. Stop/timeout can skip Python cleanup. Final
process exit remains the resource boundary. COMPLETE.txt is required for success.

Rendering defaults to RAFT Sintel and explicitly selects the saved EbSynth backend
(CUDA by default); Kitti, CPU and Auto are exposed with the limits above.
Single-frame jobs do not initialize the engine; optional masks composite styled
pixels over the source. Cross-keyframe blending is available in Blend / Flow;
Image Synthesis is implemented; real CUDA validation remains pending.
Unsupported/model-architecture controls are not presented as working features.

Preset groups: directories, guide weights, render settings and application
settings. The shareable JSON library is separate from last-used fields and local
startup policies in `%LOCALAPPDATA%/ReEzSynth`. QSettings retains folder history
and legacy compatibility. Default startup behavior restores last used values;
users may instead choose defaults or a named preset for each group. Unsaved
custom queue ranges still require a saved project. Version-1 project fields were
extended optionally; older row output names remain intact.

Automatic start and directory discovery are opt-in. Auto start is delayed until
inputs validate, skips modal dialogs and preset application, suppresses duplicate
input identities, and is disarmed by manual starts. Merely restoring startup
settings or opening a project never launches a render. Discovery matches sibling
folder suffixes recursively and asks about ambiguous pairs. It does not watch
folders for newly arriving files. Completion sound defaults to queue completion.

## Validation

Interpreter: `E:\miniconda3\envs\reezsynth\python.exe`, Python 3.11.16.
Installed metadata checked: PySide6 6.11.2, NumPy 2.4.6, OpenCV 5.0.0.93,
torch 2.11.0+cu128 and torchvision 0.26.0+cu128.

Run only the explicit lightweight suite, not the upstream rendering demos:

```powershell
python -B -m unittest test_reezsynth_gui test_reezsynth_lifecycle test_reezsynth_worker test_reezsynth_options test_reezsynth_render_adapter test_reezsynth_grouped test_reezsynth_artifacts test_reezsynth_destinations test_reezsynth_image test_reezsynth_setup test_reezsynth_polish test_reezsynth_preview test_reezsynth_raft test_reezsynth_cli_benchmark test_reezsynth_serialization -v
```

Historical baseline: 66 tests passed; see the latest validation entry above.
Tests cover GUI construction, folder history/drag-drop, naming, preset
persistence, startup choices, old/new projects, masks, automation guards,
sequential/parallel failure/cancellation/close/restart and shutdown timeout.
Adapter tests use a fake engine and exercise actual CPU image handling, including
single-frame masked and unmasked output. Tests use temporary INI settings and
files, detect unhandled Qt callbacks and mock audio playback. No GPU models load.

Offscreen layout review covered the main, Rendering and Settings tabs at 1320x820;
Settings/Rendering scroll, and folder editor clipping found in review was fixed.
Qt reports offscreen font-directory/propagateSizeHints warnings. Normal Windows
visual behavior, actual audio playback, real shared/parallel GPU rendering,
performance and memory returning toward baseline remain unverified.

## Repository and dependency follow-up

### 2026-09-12 follow-up GPU diagnostic

- The opt-in FuouM 1080p diagnostic also passed on this Windows/RTX 5090 host:
  five bundled frames completed as both an ordinary video pass (7.97 seconds)
  and a grouped pass (12.28 seconds). Valid output, styled-keyframe preservation
  and normal shared-worker exit were verified. Both jobs disabled auxiliary
  exports; error/flow exports were tested in earlier small extended runs instead.
  The diagnostic did not assert engine manifests; a subsequent review confirmed
  both identify FuouM. It sampled a 16,151 MiB device-wide GPU peak (including
  other programs), with device-wide GPU memory at 2,504 MiB before
  and 2,496 MiB after worker exit. Diagnostics are ignored under
  `diagnostic_outputs/release_fuoum_20260912_121633_484674`.
- The opt-in legacy 4K diagnostic passed on this Windows/RTX 5090 host using
  the bundled three-frame sample and memory-efficient RAFT. It completed in
  10.60 seconds, sampled a device-wide GPU peak of 11,123 MiB, produced
  valid numbered output, previews and engine provenance, and exited its shared
  worker normally. Aggregate GPU memory was 2,529 MiB before and 2,518 MiB
  after the worker exited. Diagnostics are ignored under
  `diagnostic_outputs/engines_legacy_20260912_121412_671114`.
- This is a bounded smoke/stability observation, not an overnight leak test,
  a universal performance benchmark, or validation of user-provided footage.

### Earlier repository notes (historical; superseded by current checklist)

- `.gitignore` has the correct filename and ignores common weights, but three
  RAFT .pth files are already tracked (about 46 MB total). No files were untracked.
- Tracked source bundle, example inputs/keyframes, backup and output_synth PNGs
  remain; review provenance before changing their tracking. Root renders/,
  output_synth/ and outputs/ now have ignore rules; existing tracked files remain.
- `requirements.txt` now includes PySide6 and pinned direct dependencies.
  See INSTALL_WINDOWS.md for wheel-index/runtime guidance and the clean-install
  validation recorded above.
- History retains older saved paths even if no longer present; new entries must
  be valid directories. This behavior has regression coverage.
- No commit/push or GPU render was performed. Next manual step, with approval:
  compare sequential/shared and bounded parallel GPU runs, masks/edge settings,
  memory after exit and native completion sound. Do not claim mock-process tests
  establish real GPU speed, stability or memory behavior.
