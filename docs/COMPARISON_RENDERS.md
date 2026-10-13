# Short comparison renders

In Rendering, select FuouM and use **Short comparison renders…**. Choose a
consecutive range containing at least two numbered keyframes and a non-keyframe
(normally 3–64 frames). All keyframes inside that range are used.

Available templates:

- RAFT versus NeuFlow
- One versus two independently estimated optical-flow directions
- LSQR versus LSMR versus disabled reconstruction (normal blending required)
- CUDA versus experimental torch synthesis

Current quality, processing resolution, guide weights, masks, custom edges,
edge tuning, modulation, and other rendering/blending settings are captured
without changing the visible settings or saving a different preset. Only the
selected comparison factor changes. An implicit AMG iteration limit is frozen
at 100 when comparing reconstruction methods. Models and runtime requirements
are checked before preparing output folders; no automatic dependency installs
are performed.

The ordinary render queue runs variants sequentially in isolated workers,
regardless of the user's shared-worker or parallel preference. Each variant has
its own numbered PNG output sequence, job specification and engine manifest.
Extra artifact exports and MP4 export are disabled for these comparisons.
The final queue job creates `comparison_sheet/contact_sheet.png` and
`comparison_manifest.json`. The manifest records requested/effective settings,
sampled image paths and hashes. Up to eight evenly spaced frames are shown as
aspect-preserving thumbnails with source and variant columns.

Use **Open comparison sheet** after completion (the system PNG viewer), or
**Open Outputs** to inspect individual full-size frames. This is not synchronized
playback and not a speed benchmark: cache reuse and worker/model initialization
can differ between variants. No automatic quality winner is selected.

Progress, errors, cancellation and restart recovery use the existing queue.
The sheet requires completed variant markers and matching job hashes. Recovery
redirects its dependencies when a partial variant is restarted in a fresh
sibling folder, preserving original jobs and outputs. Its completion marker is
published after the PNG and manifest. Comparison dialog choices and the quick
open-sheet location are session-only; job specifications and the journal persist.

Validation: `test_reezsynth_comparison.py` covers planning, independent settings
snapshots, templates, validation, sampling, sheet output, dependency snapshots,
dependency remapping, incomplete-output rejection, UI guards and queue isolation.
`diagnose_reezsynth_comparison.py` is an opt-in three-frame 128x128 real FuouM
comparison, not a production-resolution quality certification.

Native s9 follow-up on 2026-09-28 compared RAFT and NeuFlow over frames 26–29 at
1536×1536 with transparent keys, medium masks and source-composite output. Both
completed; generated-frame differences were visible around the moving hand and
arm (mean hand-crop MAE 1.494/255). This short interval does not establish a
general quality winner. Retained sheet and metrics:
`diagnostic_outputs/s9_feature_acceptance_20260928_0001`.
