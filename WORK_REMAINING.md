# Remaining work

Reviewed 2026-09-12 against baseline commit `91d116e`, then updated after the
default-installation and local-review fixes below. This is the current checklist; older
PROJECT_STATUS.md entries are historical. The core dual-engine integration is
implemented; remaining validation and approved enhancements are listed below.
Results describe this Windows/RTX 5090 host and the stated samples.

User decisions after review: proceed with the enhancements below, excluding
direct video import and synchronized comparison playback. FuouM is to be
installed as part of the standard application setup, not as an optional engine.

## High-reasoning implementation and local checks completed

- [x] Dual-engine routing, runtime isolation, saved project/preset compatibility,
  revision checks, and base output manifests (coverage gaps are listed below).
- [x] FuouM masks, premasking/feathered compositing, mask guides, custom edges,
  raw error/flow-visualization exports, grouped forward/reverse modes, and NeuFlow.
- [x] Separate engine-specific voting/cost/threshold/sparse/flow/reconstruction
  settings; greyed-out controls cannot leak legacy-only options into FuouM jobs.
  RAFT/NeuFlow checkpoints and legacy flow selections survive engine switches.
- [x] Correct FuouM frame/error correspondence, exact styled-keyframe preservation,
  Poisson row boundaries, and flat-color histogram normalization.
- [x] Fix zero-context build-patch application and Windows Path/PATH collisions
  in the FuouM builder. Build its native extension in a new checkout/environment.
- [x] Add the guarded optional-engine installer with pinned source, official
  checksum-verified NeuFlow downloads, no-overwrite rules and check-only mode.
- [x] Run longer shared-worker, parallel, cancel/restart and close-cycle checks;
  retain real logs, frame outputs and scoped memory observations locally.
- [x] Compare painted/flat/posterized styles, grouped boundaries, masks, exports,
  original versus compiled RAFT, and three multiguide retargeting examples.
  Inspected sample frames; do not claim general visual parity or flicker quality.
- [x] Decide/document numeric and indexing limits: retain scalar defaults,
  six-decimal controls and consecutive source numbering. Optional per-level
  schedules now have an explicit schema; arbitrary precision and frame gaps
  remain unsupported.
- [x] Audit tracked assets/licenses and distribution architecture. Preserve original
  assets; exclude historical developer snapshots/backups from source archives.
- [x] Pass 226 frontend regression tests, including preserved original setup tests,
  FuouM installer safety/state/mathematical checks and the local-review regressions.
- [x] Confirm completion audio through the user's audible queue-completion check.
- [x] Run short high-resolution checks: legacy 3840x2160 with compiled RAFT
  (three frames), and FuouM 1920x1080 video/grouped passes (five frames).
  These used Preview synthesis settings and bundled samples. Saved reports show
  successful completion and aggregate GPU memory returning near its starting level.

## Local follow-up found in this review

1. [x] Fix FuouM CLI benchmark reporting: recognize its timing lines, label their
   scope correctly, and establish success using exit status plus `COMPLETE.txt`.
   Regression tests and a new real FuouM log passed.
2. [x] Correct custom RAFT compatibility: probe the actual loaded CUDA kernel
   instead of a fixed architecture list. Custom-architecture regression and real
   RTX 5090 numerical checks passed. Normalize Windows environment names in the
   legacy builder and verify a kernel after installation.
3. [x] Complete output provenance: use the correct selected checkpoint directory,
   hash the actual correlation extension and additional adapter files, and record
   effective frontend settings/normalized guide weights separately from requests.
   Tests cover optional checkpoints without downloading them; all six new real
   image/video/grouped manifests were checked against on-disk component hashes.
4. [x] Untrack and ignore six developer snapshots after dependency review. Local
   files and Git history are preserved; see RELEASE_AUDIT.md for exact names.
   Maintained regression tests, documented diagnostics and runtime/example assets
   remain tracked. Generated environments/checkouts/results stay ignored.
5. [x] Correct validation documentation: the old 1080p check disabled video
   exports and did not assert engine manifests. Earlier extended runs cover
   exports. GPU samples are device-wide, not per-process peaks. Historical parity
   statements are now explicitly separated from current status.
6. [x] Refresh the requested ChatGPT source handoff:
   `Z:\temp\reezsynth_frontend_handoff_d66ad6a` contains 48 source/documentation/
   dependency files plus `HANDOFF_MANIFEST.txt`, with every copied source file
   verified by SHA-256. Includes all maintained frontend modules and the new
   provenance helper. It is a review bundle, not a standalone installation.
   The older 28-file `reezsynth_frontend_handoff_f5551c9` snapshot is preserved.

## Validation still needed

- [x] Validate real legacy CPU/Auto image and video output. Both backends completed
  a 256x144 image-synthesis job and two-frame video job in separate CUDA-hidden
  workers. Logs confirmed CPU optical flow; output/error shapes and values,
  completion markers, effective backend/engine provenance and worker exits passed.
  Retained report: `diagnostic_outputs/backend_20260912_140820_787666`.
  This is same-host functional evidence; a CPU-only installation remains a
  separate portability check before broadly advertising hardware compatibility.
- [ ] Review representative production clips/styles in both engines at the
  intended Standard/Highest settings. Include playback around styled-keyframe
  boundaries, occlusion, fast motion, fine detail and feathered masks. The recent
  4K/1080p smoke checks used Preview settings; they do not replace this comparison.
  One user-owned 73-frame 1536x1536 clip now has reviewed Standard/Highest runs:
  Legacy used native transparent keys; FuouM used explicitly source-composited
  opaque diagnostic copies because native transparent keys remain unsupported.
  Standard is the practical profile for both on this sample. FuouM preserved the
  hand more clearly around frames 18-22 and passes keys through exactly by policy;
  other sampled differences did not support a general engine ranking. Medium was
  the best supplied mask baseline, but tracking gaps remain. Retained ignored
  evidence: `diagnostic_outputs/s9_quality_review/REVIEW.md`. Broader clips/styles
  and controlled playback are still required before checking this item complete.
- [ ] Validate installation and short renders on another clean Windows system
  and a different supported GPU, including prerequisite errors and custom paths.
  The fresh local FuouM environment inherited this host's GUI/PyTorch/compiler/
  CUDA installation; it was not an independent clean-machine installation.

## Approved enhancements

The user selected these additions. They remain planned unless checked below;
the existing RAFT/NeuFlow workflow can be used while they are developed.

1. [x] **Additional optical-flow choices:** all three official EF-RAFT checkpoints
   from pinned revision `9ad323b` were hash-recorded, installed locally and passed
   direct finite-flow plus full frontend image/video/grouped tests. FlowDiffuser's
   official checkpoint and exact Twin-SVT artifacts were hash-recorded; upstream
   `timm 0.6.12` failed on Python 3.11, while the pinned tested 1.0.29 dependency
   set passed in quarantine and the normal environment. Rendering now loads local
   backbones only. A forced-offline full frontend run passed. Model files remain
   ignored; their licensing/distribution remains a release gate.
2. [x] **Optional GPU blending:** CuPy 14.2.0 with its pinned CUDA 13.4 component
   set passed the real readiness kernel, histogram blending, sparse construction,
   three-channel Poisson solve, and a full grouped frontend job on RTX 5090. The
   retained CUDA 12 failure remains useful compatibility evidence. Reproducible
   pins are separate from standard installation in `requirements-cupy-cuda13.txt`.
3. [x] **Rendered-video export:** both engines can atomically assemble each job's
   PNG frames into `render.mp4` at an explicit 0.1-240 FPS, with an optional
   separately selected audio file padded/trimmed to the exact video duration.
   Encoder failure prevents `COMPLETE.txt`; metadata records the inputs. Direct
   video import/frame extraction and synchronized playback remain excluded.
4. [x] **Durable queue recovery:** shared, isolated and parallel queues atomically
   record pending/running/final states. Manual recovery skips complete jobs,
   rejects changed job JSON or input path/size/time fingerprints, and restarts
   partial jobs in fresh sibling folders. Interrupted lifecycle and real parallel
   FuouM GUI checks passed; no recovery starts without confirmation.
5. **Cache reuse and longer-clip memory management:**
   - [x] Automatically reuse content-addressed per-frame edges and directional
     flow pairs across settings changes. Keys cover engine/revision, actual
     checkpoint hashes, processed input content and resolution. Arrays are
     validated and atomically published; FuouM and Legacy reuse memory-mapped
     flows. Unit/adapter tests and two-run real GUI checks passed for both engines.
   - [x] Optional disk-backed source/style/intermediate/result processing for both
     engines, with a 64 MiB/eight-array decoded cache. Full sequence propagation
     and grouped boundaries are preserved. A 101-frame FuouM video/grouped pair
     retained the same decoded-cache peak as 11-frame cases. See FRAME_STORAGE.md
     for per-frame native-memory, disk-space and forced-termination limits.
6. [x] **GPU-aware parallel scheduling:** parallel admission now combines current
   NVIDIA free-memory telemetry with conservative per-job VRAM reservations based
   on processed resolution, engine, flow path and GPU blending. Zero selects
   automatic scheduling rather than unlimited workers; positive values remain hard
   caps, and automatic mode serializes safely when telemetry is unavailable. Queue
   logs and job tooltips report the GPU, safety reserve, estimate and worker PID.
   Unit/lifecycle coverage and a real two-job automatic FuouM GUI run passed.
7. [x] **Engine setup controls in the GUI:** Settings now identifies both engines
   as standard included components, shows their pinned revisions and configured
   runtimes, and asynchronously runs the authoritative Legacy and FuouM read-only
   readiness checks with live Diagnostics output. Confirmed maintenance actions
   rebuild only the selected Legacy RAFT or FuouM native extension in place; they
   never imply source/environment repair or replacement. Controls and window close
   are guarded while an operation runs. Command/UI regressions and the real combined
   check against this host's installed engines passed; no rebuild was needed.
8. [x] **Advanced controls/workflows:** reviewed per-pyramid-level iterations,
   finer numeric precision, supported modulation guides, numerical flow-vector
   exports, and FuouM's alternate synthesis backend. Exposed options have explicit
   mapping and validation; six-decimal policy caps remain deliberate. Some upstream
   fields are unused by the selected pipeline and remain unexposed.
   - [x] Numerical flow-vector exports for both engines, with lossless arrays,
     ordered frame identities and explicit sampling-grid/pixel-unit metadata.
   - [x] Optional per-level search/vote and patch-match schedules in both engines,
     with finest-level alignment, native mapping, GUI/preset persistence and
     resolved output metadata. Scalar defaults and six-decimal caps remain.
   - [x] Target-grid grayscale modulation for image guides and numbered video
     guide groups, including grouped/reverse passes and bounded storage. Both
     CUDA engines passed native multiplier/channel-order checks and real renders.
     Legacy CPU/Auto are explicitly rejected because CPU ignores maps. Presets,
     queue snapshots, recovery and processed-map/channel manifests are covered.
   - [x] Alternate synthesis backend: user-approved repairs are implemented as
     versioned, instance-local `frontend-torch-v1`. Original upstream failures
     remain reproducible; the repaired path and unchanged CUDA pass all nine
     invariant gates. Real 14-case and nine-case Standard matrices plus GUI
     cancellation/restart and automatic parallel admission passed. The experimental
     FuouM `torch` selector still
     requires CUDA; no CPU fallback or quality parity is claimed. See
     TORCH_BACKEND_AUDIT.md for algorithm differences and memory safeguards.
9. [ ] **Stronger quality/stability evidence:** overnight repeated-job testing,
    isolated performance comparisons, multi-GPU coverage, and investigation of
    true backward flow in place of FuouM's negative-forward-flow approximation.
    The backward-flow investigation is now implemented as an opt-in RAFT/NeuFlow
    path with explicit pull sampling and accumulated coordinate/NNF propagation.
    Standard/Highest runs and numerical direction/cache tests passed.
    Automated stability and user-input quality-matrix harnesses are now present.
    A bounded six-case alternating-engine run passed with post-exit GPU drift no
    higher than 292 MiB. Separate 11-frame Standard renders passed for both engines;
    the run exposed and fixed FuouM's final-3x3 missing-mode bug. An attempted
    eight-hour 384x216 Standard campaign reached 94 passing isolated cases, but
    its 95th was rejected by the device-wide guardrail at +2,448 MiB. Its child
    render passed (all 95 child suites exited successfully); device-wide usage
    rose from 4,130 to 7,102 MiB on an active WDDM desktop. The cause cannot be
    attributed from these samples, so the result is inconclusive. Retained report:
    `stability_20260912_193422_040460`. Repeat on an idle host (or add an
    attributable metric); overnight, multi-GPU and broader visual review remain
    open.
10. [x] **Automated regression checks:** a canonical maintained-suite runner and
    Windows GitHub Actions workflow now use CPU PyTorch with CUDA hidden for normal
    push/PR checks. Real Legacy/FuouM diagnostics require an explicit manual input
    and a preconfigured self-hosted `reezsynth-gpu` runner. The canonical command
    initially passed all 258 tests locally both normally and with the CI environment
    flags; the suite has since expanded with flow and bounded-storage regressions;
    the workflow itself remains unrun until this commit is pushed to GitHub.

### Excluded by user preference

- Direct video import and frame extraction from video files.
- Synchronized source/style/output or engine-comparison playback.

### Default dual-engine installation

- [x] Make standard Windows setup install and verify both engines, including
  FuouM's RAFT/NeuFlow checkpoints, in their separate runtimes. Keep saved engine
  selections and the existing initial selection compatible.
- [x] Check Git/CUDA/C++ build prerequisites before large package downloads.
  Fail setup if either component fails, preserve existing environments, and
  record launcher configuration only after both engines pass.
- [x] Cover default installation, check-only, missing prerequisites, component
  failure, existing environments and no-write plan behavior in setup regressions.
- [x] Pass 26 setup regressions, the real combined check-only command against
  this host's existing engines, and a fresh-build prerequisite probe that created
  no source directory. No engine reinstall or new render was needed.
- [ ] Validate the combined fresh installation on another clean Windows machine;
  the existing same-host component build evidence remains recorded separately.

## Before a public release

- [ ] Resolve the existing DLL/weights/example/dependency provenance items in
  [RELEASE_AUDIT.md](RELEASE_AUDIT.md), and decide which assets to distribute.
- [ ] Complete clean-machine validation and inspect the final tracked/archive
  inventory for the chosen distribution. Publishing a release is a separate action.

## Evidence for this review

- Original alternate-backend readiness failed in both repeated runs. The final
  hash-recorded report is `torch_backend_20260912_211813_699042`: CUDA passed
  nine of nine controlled cases, PyTorch five of nine. The user then approved
  repairs: `torch_backend_20260912_212429_874906` passes nine of nine for both
  CUDA and the repaired PyTorch layer. Two real Standard matrices passed 23 total
  jobs, followed by successful GUI cancellation/restart. Exact reports and
  experimental limitations are in PROJECT_STATUS.md and TORCH_BACKEND_AUDIT.md.
- Modulation passed controlled native multiplier/channel tests in both CUDA
  engines and 13 real Standard image/video/grouped cases per engine, including
  masks, reverse mode, bounded storage and iteration schedules. An additional
  eight-case FuouM run covered NCC and scalar defaults on intermediate frames.
  Legacy CPU was shown to ignore maps, so CPU/Auto modulation is rejected.
  Exact reports and limitations are recorded in PROJECT_STATUS.md.
- Per-level schedules passed eight real Standard cases per engine at 257x145,
  including one-level/Automatic pyramids, scalar fallback and three multiguide
  image retargeting jobs. Both used bounded storage; FuouM also used measured
  backward flow. Reports: `release_legacy_20260912_205556_943246` and
  `release_fuoum_20260912_205631_250465`.
- Full suite through the canonical CI runner: 317 maintained tests passed in 45.954 seconds with
  normal temporary-directory/Qt access. Both cache publication races are now fixed;
  50 concurrent-producer stress rounds also passed. Focused recovery/cache selections, a real
  parallel FuouM journal audit, and two-run cache checks for both engines passed.
- Optional bounded frame storage passed a two-engine Standard matrix, 19 FuouM
  and six Legacy extended cases, both GUI cache-reuse checks, and FuouM GUI
  cancellation/restart. A 101-frame video/grouped pair kept the decoded-cache peak
  at 2,359,296 bytes, matching the 11-frame sample. Native memory is additional;
  exact reports and scratch-space observations are in PROJECT_STATUS.md.
- Automatic GPU-aware admission also passed a real two-job 512x288 FuouM GUI run.
  Each worker reserved an estimated 2.4 GiB against 28.2 GiB initially free with a
  3.2 GiB safety reserve; both completed, logged their PIDs/resource snapshots and
  left 28.2 GiB free after exit. Retained diagnostic:
  `gui_controller_20260912_160955_548162`.
- The new combined read-only readiness command passed on this host in 15.7 seconds.
  It verified both pinned revisions, Legacy dependency consistency/runtime hashes,
  CUDA 12.8, the EbSynth entry point and compiled RAFT extension, plus FuouM's
  dedicated environment, native import, RAFT and NeuFlow assets. It loaded no
  models and performed no render or rebuild.
- Synthetic CUDA correlation checks passed, followed by real 256x144 Preview
  image/video/grouped smoke checks for both engines. Legacy used compiled RAFT.
  Completion, previews, image errors, numbering, worker exit and the new component
  hashes were verified; these small runs did not enable video auxiliary exports.
  Exact retained diagnostic names and limits are in PROJECT_STATUS.md.
- The new bounded stability campaign passed all six Legacy/FuouM and
  painting/poster/flat cases at 128x128 Preview. Post-exit GPU drift ranged from
  154 to 292 MiB. Retained report: `stability_20260912_165159_943355`.
- The attempted eight-hour Standard stability campaign is retained as
  `stability_20260912_193422_040460`. All 95 child suites rendered successfully;
  the 95th exceeded the device-wide guardrail after 94 guardrail passes. It is not
  evidence of a renderer memory leak or a completed overnight validation.
- Standard 256x144 quality renders passed on the bundled 11-frame/three-key input
  for Legacy and FuouM. The retained FuouM pass is
  `quality_20260912_165006_794209`; general visual judgment is still manual.
- The earlier default-setup verification passed 26 setup tests, real combined
  check-only, and a no-write compiler prerequisite check. No installed engine was
  replaced during the local-review fixes. Clean-machine testing remains open.

Setup/capabilities: [DUAL_ENGINE.md](DUAL_ENGINE.md).
Numeric/indexing decisions: [NUMERIC_SETTINGS.md](NUMERIC_SETTINGS.md).
Release gates: [RELEASE_AUDIT.md](RELEASE_AUDIT.md).
Detailed evidence: [PROJECT_STATUS.md](PROJECT_STATUS.md).

## Next model handoff

The high-reasoning implementation sequence is complete, including the approved
alternate-backend repairs. Switch to a lower-reasoning model for routine campaign
execution, report collection and documentation. Keep PyTorch synthesis explicitly
experimental; return to high reasoning if new numerical/render failures need
diagnosis or fixes.

Next evidence work: repeat overnight stability on an idle host, review supplied
production frame/keyframe folders, and validate setup on another Windows/GPU
system. The previous overnight guardrail result was inconclusive, not a confirmed
renderer leak. Remote CI remains unrun because the commits are not pushed;
publishing/pushing and distribution decisions require separate authorization.
