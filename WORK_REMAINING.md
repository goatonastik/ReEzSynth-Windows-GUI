# Remaining work

Updated 2026-09-12. This checklist supersedes historical pending notes in
PROJECT_STATUS.md. Completed checks below are scoped to this Windows/RTX 5090
installation and the stated samples.

## Highest-risk work completed

- [x] Add selectable original and FuouM engines with separate worker runtimes.
- [x] Preserve old projects; persist engine/revision in new projects, presets and
  jobs; record source/native/checkpoint/runtime provenance in output manifests.
- [x] Implement FuouM image, independent video and normal grouped blending,
  parameter mapping, live previews and explicit capability validation.
- [x] Build and load FuouM's native extension on Windows/PyTorch 2.11/RTX 5090.
- [x] Verify real small image/video/grouped outputs and shared-worker reuse for
  both engines; verify real FuouM GUI cancellation/restart and parallel jobs.
- [x] Repair duplicate identical RAFT source conflicts. The supported RAFT build
  already used the clean third_party source; only the older copy contained markers.
- [x] Complete a three-frame 4K render using compiled memory-efficient RAFT, with
  valid output dimensions/previews and aggregate GPU memory returning to baseline.
- [x] Clarify upstream attribution and document the second engine's setup.
- [x] Pass the final explicit regression suite: 187 tests in 25.213 seconds.

## Next work

1. Extend FuouM capability coverage deliberately: masks/compositing and mask guides,
   custom edge sequences, auxiliary error/flow exports, grouped direction modes,
   NeuFlow and additional native controls. Keep unsupported requests explicit.
2. Compare longer real sequences and representative styles, including grouped
   boundaries, masks, exports, and image retargeting. Compare original RAFT versus
   compiled correlation at the same feasible resolution. Small diagnostics and
   inspected samples do not establish general visual parity or flicker quality.
3. Measure longer shared/parallel runs, cancellation/close cycles and high-resolution
   peak memory on an otherwise idle GPU. Short checks passed; their sampled memory
   observations are not long-duration leak tests or production speed benchmarks.
4. Validate CPU/Auto native backends on a CPU-only installation. Earlier local
   native CPU/Auto diagnostics passed; complete CPU-only video behavior remains.
5. Install and validate optional EF-RAFT/FlowDiffuser weights and dependencies for
   the original engine; verify first-run downloads and real memory/output behavior.
6. Validate optional CuPy blending and reconstruction in a controlled environment.
7. Decide numeric/API parity limits: UI caps, higher precision, per-level iteration
   arrays, stop thresholds and advanced detector settings; test native conversions.
8. Audit whether grouped input selection needs any additional flexibility. A
   keyframe checklist already exists; arbitrary file lists/gapped numbering need
   separate workflow and indexing decisions.
9. Verify audible completion notifications interactively on Windows. Real GUI
   diagnostics initialize multimedia, but that does not establish audible playback.
10. Prepare distribution: audit tracked assets/examples/backups and licenses,
    provide second-engine installation packaging, validate a clean machine, review
    all existing local changes, then commit/publish only when requested.

Detailed limitations and setup: [DUAL_ENGINE.md](DUAL_ENGINE.md).
Numeric boundaries: [NUMERIC_SETTINGS.md](NUMERIC_SETTINGS.md).
Recorded evidence and historical results: [PROJECT_STATUS.md](PROJECT_STATUS.md).
