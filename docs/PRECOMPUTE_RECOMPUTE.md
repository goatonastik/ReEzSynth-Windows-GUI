# FuouM precomputation recompute controls

In Rendering with FuouM selected, use:

- **Recompute optical flow — ignore shared cache**
- **Recompute edges — ignore shared cache**

Both are off by default. The note below them describes which data will be
recomputed. With both off, validated shared cache reuse is unchanged.

## Scope and safety

An enabled control computes fresh data for the current render instead of reading
or writing the corresponding shared-cache entries. It does **not** delete,
replace, repair, or refresh the shared cache. Other jobs, including parallel
readers, keep their existing cache data. Uncheck the control to resume ordinary
reuse; this can reuse the original shared entries again.

Recomputing flow covers forward flow and independently estimated backward flow
when Estimate both flow directions is enabled. It works with RAFT and NeuFlow.
Recomputing edges uses the current detector and tuning. Either category can still
reuse its valid cache while the other is recomputed.

These are FuouM video controls. They do not affect Legacy or Image Synthesis.
Jobs that only copy a keyframe and do not need these precomputations remain copies.
Custom edge-guide frames bypass automatic edge computation; the edge-recompute
control is disabled while retaining its remembered value for switching back.

Controls are saved in projects, rendering presets, and last-used settings. They
are persistent options, not one-shot buttons. Quality selection does not reset
them. Old documents without these fields default both controls to off. Requested
settings are retained in job metadata; effective metadata omits inactive/bypassed
fields. Diagnostics logs distinguish forced computation from validated reuse.

Frontend fields are `fuoum_force_recompute_flow` and
`fuoum_force_recompute_edge`. They implement per-render bypass in the frontend's
content-addressed cache, not upstream's mutable project-cache refresh behavior.
Future native FuouM YAML interchange must explain that difference rather than
claim cache-management equivalence.

## Verification

`test_reezsynth_recompute` is included in the maintained suite. Tests cover:

- Old defaults and strict boolean validation.
- Independent flow/edge bypass on a warm cache with fresh results retained.
- Shared-cache file preservation and normal reuse after turning bypass off.
- Both flags on a cold cache without creating shared entries.
- Custom-edge bypass, NeuFlow/forward-only flow, and disk-backed storage.
- Effective metadata, UI relevance, preset round trips, and engine/quality changes.

An opt-in real diagnostic uses two generated 128x128 frames, both flow directions,
and separate warm/reuse/forced renders:

```powershell
python -B tools/diagnostics/diagnose_reezsynth_recompute.py
```

It checks normal reuse, forced computation, successful outputs/completion,
effective settings, and unchanged shared-cache file hashes. Results are retained
under ignored `diagnostic_outputs/recompute_<timestamp>/`. This bounded check is
not long-running stability or general quality evidence.

Local verification on 2026-09-26: 449 maintained tests passed in 82.686s,
including 10 recompute-specific tests. The real explicit Preview diagnostic
`diagnostic_outputs/recompute_20260926_020605_860142` passed all three render
stages with both flow directions, successful outputs/completion, recorded flags,
and unchanged shared-cache file hashes.

Native s9 follow-up on 2026-09-28 repeated a masked 1536×1536 Standard job with
an empty cache, normal reuse and both recompute controls enabled. All jobs passed,
endpoint keys were byte-identical, alpha was unchanged, and shared-cache hashes
remained unchanged. Generated-frame RGB differed across CUDA launches (MAE
0.152–0.171/255; localized maximum 107/255); reused and forced results varied by
the same scale, so byte-identical generated pixels are not asserted. The first
diagnostic attempt stopped when its byte-equality assumption failed on frame 27;
after the spread was inspected, the resumed run used and recorded a bounded
mean-difference criterion. Retained comparison sheet, metrics and both logs:
`diagnostic_outputs/s9_feature_acceptance_20260928_0001`.
