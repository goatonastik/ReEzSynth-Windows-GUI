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
- [x] Decide/document numeric and indexing limits: retain scalar iterations,
  six-decimal controls and consecutive source numbering; do not silently accept
  unsupported arrays, arbitrary precision or frame gaps.
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
6. [ ] Refresh the requested ChatGPT handoff if it is to represent current code.
   `Z:\temp\reezsynth_frontend_handoff_f5551c9` exists with 28 copied files and
   its manifest. It predates the CuPy-kernel preflight fix and the subsequent
   default dual-engine setup changes. Keep the original snapshot
   identifiable and supply a new revision-labelled copy when refreshing it.

## Validation still needed

- [ ] Validate real legacy CPU/Auto image and video output. Existing coverage
  checks adapter behavior with mocks. Initial native CPU and CUDA-hidden CPU-flow
  checks can be performed on this host in isolated processes; separate CPU-only
  hardware is not required to start that work. A CPU-only installation remains
  a separate portability check if CPU support is to be advertised.
- [ ] Review representative production clips/styles in both engines at the
  intended Standard/Highest settings. Include playback around styled-keyframe
  boundaries, occlusion, fast motion, fine detail and feathered masks. The recent
  4K/1080p smoke checks used Preview settings; they do not replace this comparison.
- [ ] Validate installation and short renders on another clean Windows system
  and a different supported GPU, including prerequisite errors and custom paths.
  The fresh local FuouM environment inherited this host's GUI/PyTorch/compiler/
  CUDA installation; it was not an independent clean-machine installation.

## Approved enhancements

The user selected these additions. They remain planned unless checked below;
the existing RAFT/NeuFlow workflow can be used while they are developed.

1. [ ] **Additional optical-flow choices:** install and test EF-RAFT/FlowDiffuser
   in a controlled environment with identified checkpoint versions. FlowDiffuser
   also constructs pretrained Twin-SVT backbones, so readiness must account for
   their downloads/cache and compatibility, not just the main checkpoint and timm.
2. [ ] **Optional GPU blending:** investigate a working CuPy configuration on
   RTX 5090 and test histogram/Poisson blending. The retained CuPy 14.2.0/CUDA 12
   experiment failed a real kernel; a compatible configuration is not yet
   demonstrated. The normal installation does not depend on CuPy.
3. [ ] **Rendered-video export:** assemble existing rendered frames into video
   with an explicit frame rate and optional separately selected audio. Direct
   video import/frame extraction is excluded from this workflow.
4. [ ] **Durable queue recovery:** save pending jobs and resume after application
   restart/crash, with explicit handling of partial outputs and changed inputs.
5. [ ] **Cache reuse and longer-clip memory management:** reuse validated flow/
   edge data across settings changes, then consider chunking or streaming long
   sequences. Cache keys must include engine, checkpoint, inputs and resolution.
6. [ ] **GPU-aware parallel scheduling:** limit concurrent jobs by measured or
   estimated memory demand and show useful per-worker resource information.
   Current scheduling uses a fixed worker limit, including an unlimited option.
7. [ ] **Engine setup controls in the GUI:** expose component readiness checks
   and maintenance/rebuild/version handling. Standard installation now includes
   FuouM; these controls should describe it as an included engine.
8. [ ] **Advanced controls/workflows:** consider per-pyramid-level iterations,
   finer numeric precision, supported modulation guides, numerical flow-vector
   exports, or FuouM's alternate synthesis backend. Each needs explicit mapping
   and validation. Some upstream configuration fields are unused by the selected
   CUDA pipeline; do not turn those into misleading controls.
9. [ ] **Stronger quality/stability evidence:** overnight repeated-job testing,
    isolated performance comparisons, multi-GPU coverage, and investigation of
    true backward flow in place of FuouM's negative-forward-flow approximation.
10. [ ] **Automated regression checks:** run the lightweight suite in CI and keep
    GPU diagnostics opt-in, so future changes to either adapter are easier to review.

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

- Full suite after the fixes: 226 tests passed in 29.340 seconds with normal
  temporary-directory/Qt access. The focused new regression selection also passed.
- Synthetic CUDA correlation checks passed, followed by real 256x144 Preview
  image/video/grouped smoke checks for both engines. Legacy used compiled RAFT.
  Completion, previews, image errors, numbering, worker exit and the new component
  hashes were verified; these small runs did not enable video auxiliary exports.
  Exact retained diagnostic names and limits are in PROJECT_STATUS.md.
- The earlier default-setup verification passed 26 setup tests, real combined
  check-only, and a no-write compiler prerequisite check. No installed engine was
  replaced during the local-review fixes. Clean-machine testing remains open.

Setup/capabilities: [DUAL_ENGINE.md](DUAL_ENGINE.md).
Numeric/indexing decisions: [NUMERIC_SETTINGS.md](NUMERIC_SETTINGS.md).
Release gates: [RELEASE_AUDIT.md](RELEASE_AUDIT.md).
Detailed evidence: [PROJECT_STATUS.md](PROJECT_STATUS.md).
