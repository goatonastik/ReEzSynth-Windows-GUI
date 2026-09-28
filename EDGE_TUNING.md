# Advanced edge tuning and preview

In Rendering, select Edge method and expand **Advanced edge settings** immediately
below it. PST and PAGE show their own detector settings. Classic retains its
existing fixed filter and can also be previewed.

## Normal workflow

1. Select the source-frame folder and rendering processing size.
2. Choose PST or PAGE, expand Advanced edge settings, and adjust a small number
   of controls at a time.
3. Open **Edge Preview…**, select a numbered source frame, and click
   **Update Preview**. Refresh frame list after replacing/changing the source folder.
4. Inspect Source, Edges, a 50% Overlay, Detector defaults, or Current / defaults
   side by side. Left is current tuning; right is the detector default.
5. Save a rendering preset or project when satisfied. Rendering uses those same
   detector parameters. **Reset edge settings to defaults** resets the selected
   detector, not guide weights or the other detector's remembered settings.

The edge preview is a guide inspection tool, not a synthesized-output preview or
a guarantee that a detector/settings combination will produce the best render.
The existing Edge guide weight controls how strongly synthesis uses that guide;
detector tuning controls its construction.

## Resolution, masking and bypasses

One frame is computed at the rendering processing size, including restored legacy
maximum-width limits. Display scaling fits the window without changing the
computed image. No independent reduced-resolution approximation is used.

When input premasking is enabled, the worker applies the selected engine's actual
premask behavior before edge computation: Legacy uses nonzero mask inclusion;
FuouM multiplies by grayscale mask intensity. Mask resizing uses nearest-neighbor
interpolation, as rendering does.

Custom edge-guide frames bypass automatic detection. Tuning/automatic preview are
disabled in that mode. These controls do not apply to Image Synthesis, which has
explicit image-guide pairs.

## Settings and compatibility

Six PST and ten PAGE settings are exposed, matching the existing detector APIs:

| Detector | UI setting | Kernel parameter | Existing default |
| --- | --- | --- | --- |
| PST | Phase strength | S | 0.3 |
| PST | Warp strength | W | 15 |
| PST | Low-pass sigma | sigma_LPF | 0.15 |
| PST | Lower / upper threshold | thresh_min / thresh_max | 0.05 / 0.9 |
| PST | Morphological cleanup | morph_flag | On |
| PAGE | First / second frequency center | mu_1 / mu_2 | 0 / 0.35 |
| PAGE | First / second frequency sigma | sigma_1 / sigma_2 | 0.05 / 0.8 |
| PAGE | First / second phase strength | S1 / S2 | 0.8 / 0.8 |
| PAGE | Low-pass sigma | sigma_LPF | 0.1 |
| PAGE | Lower / upper threshold | thresh_min / thresh_max | 0 / 0.9 |
| PAGE | Morphological cleanup | morph_flag | On |

Finite numeric values, positive sigma/warp widths, threshold ordering, and
frontend bounds are validated. Bounds are input safety limits, not recommended
quality ranges. Start near defaults; inspect the resulting guide rather than
assuming increasing a setting improves quality. PST/PAGE require the selected
engine's CUDA/PyCV environment; Classic retains its CPU-compatible detector path.

Rendering presets, projects, and last-used settings retain both detectors' tuning.
Older documents without these fields use exactly the existing defaults. Quality
profiles remain synthesis-only and do not reset detector tuning. Effective output
metadata includes only the selected detector's active tuning; custom-guide jobs
omit automatic detector settings. The shared edge adapter is included in output
component hashes.

Cache identity includes effective non-default detector parameters. Changing tuning
does not silently reuse old edge maps or unnecessarily invalidate optical flow.
Default settings preserve existing valid default edge cache keys; changing settings
for the inactive detector does not affect the selected detector's cache.

## Preview process and recovery

Update Preview starts a separate short-lived process in the selected engine's
Python environment. The GUI stays responsive, retains the previous images while
computing, and reports outdated images after settings/context changes. It does
not continuously rerun while sliders/spin boxes are edited.

Application-controlled rendering and component maintenance cannot start during
an active edge preview, and preview cannot start during rendering/maintenance.
This guards this application's GPU work, not unrelated programs on the machine.

Cancel terminates the preview worker, escalating to kill after a short timeout.
Ownership remains until process exit; restarting is allowed afterward. Closing
the preview (including Escape) cancels asynchronously. Closing the main window
also waits for its preview worker to stop before completing shutdown.

Failed launch/computation is shown in the preview with details in Diagnostics /
Log. Existing images are not replaced on failure/cancellation. Temporary request
and image files are cleaned after completion; cleanup errors are logged and do
not silently permit replacement of an uncleared scratch directory.

## Developer verification

`test_reezsynth_edges` is included in `run_maintained_tests.py`. It covers defaults,
validation, kernel dispatch, cache identities, FuouM pipeline use/bypass, preset
compatibility, UI relevance, premasking/resolution, failed launch, cancellation,
and obsolete-process signals. Legacy adapter tests also exercise edge cache
invalidation while retaining cached flow.

Opt-in real-worker checks (synthetic frames; no synthesis or flow models):

```powershell
python -B diagnose_reezsynth_edges.py --engine legacy
python -B diagnose_reezsynth_edges.py --engine fuoum
python -B diagnose_reezsynth_edges.py --engine legacy --gui
python -B diagnose_reezsynth_edges.py --engine fuoum --gui
```

The GUI checks use temporary preferences and retain offscreen screenshots under
ignored `diagnostic_outputs/`. Normal Windows interactive visual review and
representative full synthesis quality comparisons remain separate acceptance work.

Local verification on 2026-09-26: 439 maintained tests passed in 79.583s,
including 12 edge-specific tests. Both engines passed real Classic/PST/PAGE
one-frame worker checks at 256x128 and real asynchronous GUI preview,
cancel/restart, cleanup, stale-setting indication and comparison-layout checks.
Retained final GUI screenshots are in `edge_preview_20260926_010349_757191`
(FuouM) and `edge_preview_20260926_010454_151191` (Legacy).
