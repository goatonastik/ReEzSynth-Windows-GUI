# Remaining work

Updated 2026-09-12 after the high-reasoning pass. This is the current checklist;
older PROJECT_STATUS.md entries are historical. Results below describe this
Windows/RTX 5090 host and the stated samples, not universal release certification.

## High-reasoning implementation and local checks completed

- [x] Dual-engine routing, runtime isolation, saved project/preset compatibility,
  revision checks, and output provenance.
- [x] FuouM masks, premasking/feathered compositing, mask guides, custom edges,
  raw error/flow-visualization exports, grouped forward/reverse modes, and NeuFlow.
- [x] Separate engine-specific voting/cost/threshold/sparse/flow/reconstruction
  settings; greyed-out controls cannot leak legacy-only options into FuouM jobs.
  RAFT/NeuFlow checkpoints and legacy flow selections survive engine switches.
- [x] Correct FuouM frame/error correspondence, exact styled-keyframe preservation,
  Poisson row boundaries, and flat-color histogram normalization.
- [x] Fix zero-context build-patch application and Windows Path/PATH collisions.
  Build the native extension in a new checkout/environment, not just reuse a binary.
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
- [x] Pass 198 frontend regression tests, including preserved original setup tests
  and new FuouM installer safety/state/mathematical checks.

## Suitable for an average/turbo model

1. Run the documented CPU/Auto video checks on a CPU-only installation.
2. Install and verify optional EF-RAFT/FlowDiffuser checkpoints and dependencies
   in a controlled environment once an authoritative, versioned checkpoint source
   with acceptable terms is selected. Their upstream projects use external model
   downloads; the frontend deliberately imports user-selected files only.
3. Revisit optional legacy CuPy blending when a CuPy release supports this GPU.
   An isolated CuPy 14.2.0 / CUDA 12 build was tested and cannot generate a kernel
   for RTX 5090; the frontend now rejects this condition before a render starts.
4. Review more user-provided clips/styles at production resolutions; retain
   reproducible job settings and report visual failures without claiming a universal
   engine quality ranking. Escalate actual algorithmic failures to high reasoning.
5. Review final documentation/staged-file inventory and commit when requested.

## Requires external evidence or a user decision, not a model upgrade

- A separate clean Windows machine/GPU and a CPU-only machine are still needed
  for release-level installation and hardware coverage. The fresh local venv
  inherits this host's working GUI/PyTorch/compiler/CUDA setup.
- Clear provenance/redistribution terms for existing DLL/weights, sample artwork,
  optional flow code/checkpoints and dependencies before publishing a package.
  Decide which uncleared assets to replace or omit; see RELEASE_AUDIT.md.
- Agree on any future expansion to per-level iteration arrays, detector-internal
  controls, arbitrary precision or gapped-file timing. These are deliberate current
  limits, not silently implemented partial features.
- Overnight leak testing and truly idle-GPU production benchmarks remain optional
  stronger evidence. Current repeated runs are bounded tests, not that claim.

Setup/capabilities: [DUAL_ENGINE.md](DUAL_ENGINE.md).
Numeric/indexing decisions: [NUMERIC_SETTINGS.md](NUMERIC_SETTINGS.md).
Release gates: [RELEASE_AUDIT.md](RELEASE_AUDIT.md).
Detailed evidence: [PROJECT_STATUS.md](PROJECT_STATUS.md).
