# Project status

Updated 2026-09-21. Live files are authoritative. Usage and settings are described
in [README.md](README.md).

## Legacy keyframe-preservation modes (2026-09-20)

- Rendering now provides a Legacy-only Keyframe preservation selector. Current
  behavior remains the default and retains the previous synthesis/blend assembly.
  Exact output pins the supplied processed key at every styled frame after synthesis,
  leaving neighboring frames unchanged. Optional mask/background compositing runs
  afterward so it is applied consistently to keys and propagated frames; without
  masks, keys are byte-exact to the loaded keyframes at the processing size.
- Transition-aware also restores each supplied key before optional compositing.
  For the two adjacent frames on each side of a blend boundary, it biases the
  completed blend toward the
  already generated forward/backward motion-propagated candidate; it does not
  dissolve a stationary key over moving footage. RGBA candidates are mixed in
  premultiplied space and returned as straight BGRA.
- FuouM already preserves supplied keys exactly, so its UI disables this control.
  Older projects and presets default to Current behavior. The selected mode is
  retained in projects, Rendering presets, job settings and provenance.
- The focused 127-test rendering/options/grouped/artifact set passed. A direct
  real-`run_blend` dispatch regression was then added and passed with the pinning,
  RGB transition and RGBA edge tests. Independent Claude review initially required
  that missing dispatch coverage; the corrected patch received SAFE TO COMMIT.
  The full maintained suite passed **408 tests in 60.139 seconds** after the final
  alpha-aware multi-frame and single-frame composite coverage. Its first run
  exposed a shared-process test-order assumption: the GUI lazy-import check now
  verifies that construction does not add or replace heavy modules already loaded
  by earlier engine tests. The native s9 comparison used post-fix Exact and
  Transition-aware renders plus the earlier Current-behavior render. Their opaque
  styled-key cores are directly comparable because the compositing change does not
  affect fully opaque style pixels under a white mask. Exact and Transition-aware
  preserved all six cores, while Current behavior measurably differed at four
  interior keys (core RGB MAE 5.5-21.8). Relative to Exact output, Transition-aware
  reduced adjacent-frame RGB discontinuity at every boundary by 14.7%-55.0% and
  looked more coherent around the fast-moving hands at frames 25-33. Current remains
  the compatibility default; Transition-aware is the best choice on this sample
  when exact keys and smoother handoffs are both wanted. Retained ignored evidence:
  `diagnostic_outputs/s9_keyframe_preservation_native_20260920_0001/REVIEW.md`.

## Native production-footage review and Legacy alignment fix (2026-09-15)

- Reviewed the user's 73-frame s9 clip at its original 1536x1536 resolution with
  six transparent styled keys and three imperfect real-world mask sequences.
  Medium is the best baseline: sharp narrows some fringes but has hard contours
  and invalid opening coverage; blurry ends with empty masks. Playback metadata
  is 24 fps; no frame or evidence image was resampled.
- The review exposed mismatched Legacy interior blend-error correspondence.
  Commit `a782302` preserves the boundary mask and seed policies while pairing
  each interior forward/backward error on the same frame. Focused tests cover
  real selection/consumption, two-frame behavior, disk storage, RGB/RGBA seeds,
  mapping and multi-segment metadata. The maintained suite passed 396 tests;
  independent review returned SAFE TO COMMIT, and a seven-frame native check
  passed before the normal fast-forward push to `origin/main`.
- Post-fix Legacy Standard and Highest full renders passed in 840.062 and
  904.657 seconds with 73 RGBA outputs, 72 directed flow arrays, videos and
  provenance. Their outputs are close; Highest showed no reliable quality or
  stability gain. Standard remains the practical Legacy profile for this clip.
  Legacy's internal keys still drift because its blend assembly mixes the next
  key's backward propagation at internal boundaries; changing key authority is
  a separate product decision.
- FuouM intentionally rejects the transparent keys. For a bounded RGB comparison,
  diagnostic-only opaque keys were created at native size by alpha-compositing
  each style over its matching source frame, with all hashes recorded. FuouM
  Standard and Highest passed in 551.360 and 520.234 seconds. The sequential,
  cache-warmed timings are not a performance ranking. Standard/Highest were
  again visually close.
- FuouM passes every supplied key through exactly by architecture, while Legacy's
  internal keys are blended. FuouM Standard also retained clearer glove/finger
  detail around frames 18-22 in the inspected native crops. Other cross-engine
  differences were marginal or broadly tonal with unisolated causes; no general
  engine-quality winner is claimed. Standard is the practical profile for both
  engines on this sample. Use Legacy without mask/background compositing when native
  transparent output is required; FuouM evidence applies only to explicitly prepared
  opaque keys.
- Detailed ignored evidence is in `diagnostic_outputs/s9_quality_review/REVIEW.md`,
  including mask geometry, key-core metrics, full run reports and unscaled native
  sequences. Claude's initial cross-engine review required narrower visual claims
  and clearer policy/method distinctions; after correction the final verdict was
  CROSS-ENGINE REVIEW SOUND. Broader clips/styles, controlled playback, native
  FuouM transparency policy and other-hardware validation remain open.

## Native s6 scene-1 production review (2026-09-21)

- Reviewed source frames 50-97 as an independent 48-frame scene at the original
  1900x1060 resolution and 24 fps, excluding the 97/98 jump cut. Seven transparent
  keys and generated masks anchored original frames 53, 59, 61, 63, 66, 75 and 78.
- Legacy Standard used Transition-aware preservation; FuouM Standard used
  hash-recorded opaque diagnostic keys composited over their matching source frames.
  Both engines completed 48 native frames and videos. Legacy matched the documented
  feathered source-over composite exactly at all keys; FuouM differed by at most
  0.00525 RGB MAE. Both matched the source exactly outside blurred mask support.
- The Legacy run had lower key-adjacent temporal change on twelve of fourteen
  transitions, was effectively tied on one and higher on one. This run does not
  isolate Transition-aware from other engine differences and establishes no general
  engine ranking. Native inspection found only modest facial and line differences.
- Both engines show microphone/left-helmet defects at original frame 97, nineteen
  forward-only frames after the last key. A key near 97 is the most useful controlled
  next test, but improvement remains a hypothesis. Scene 2 separately needs a late
  key near original 117 for its observed mask-tracking failure. Independent review
  returned REVIEW SOUND. Retained ignored evidence:
  `diagnostic_outputs/s6_scene1_native_20260921_0001/REVIEW.md`.

## Native s1 production review (2026-09-21)

- Reviewed all 141 frames at the original 1440x1440 resolution and 24 fps with
  seven transparent keys at frames 49, 73, 81, 99, 112, 121 and 126. Legacy
  Standard used Transition-aware preservation; FuouM Standard used hash-recorded
  opaque diagnostic keys composited over their corresponding source frames.
- Both engines completed 141 native frames and videos. Legacy matched the
  documented feathered source-over composite exactly at every key; FuouM differed
  by at most 0.00764 RGB MAE. Both matched the source exactly outside blurred mask
  support on every frame.
- Sixteen subject-region transitions have effectively held source footage. FuouM
  had lower output change on thirteen, often substantially; Legacy was lower on
  three. This is direct evidence of lower held-frame flicker for FuouM on this
  run, not a general engine ranking. The fourteen transitions immediately into or
  out of keys were mixed: FuouM lower on eight and Legacy on six.
- Native inspection found Legacy visibly cleaner at frame 0, forty-nine backward-
  only propagation steps from the first key: FuouM showed a washed/ghosted raised
  cannoli and hand plus mottled chest/lapel detail. Both engines remained
  geometrically coherent through that opening span and the fourteen-frame final
  forward-only tail. Feather 9 contained changes to mask support without a broad
  exterior halo; a narrow styled contour remains inseparable from mask-edge
  behavior in this material.
- Independent review returned REVIEW SOUND after requiring the held-frame flicker
  analysis and narrower visual/causal wording. Retained ignored evidence:
  `diagnostic_outputs/s1_native_20260921_0001/REVIEW.md`.

## Repaired experimental PyTorch backend verified (2026-09-12)

- User approved repairs following the failed upstream readiness audit below.
  Added an instance-local, versioned `frontend-torch-v1` level implementation;
  installed engine files and the CUDA default are unchanged. FuouM's Rendering
  backend selector now offers experimental `torch`, still requiring CUDA.
- Fixed target-grid errors, spatial per-channel modulation, weighted voting
  normalization, masked candidate acceptance, occupancy consistency, single-target
  random search and iterative search/vote refinement. Pyramids/flow/NNF transport
  remain upstream. Synchronous candidate batches and rounded voting are explicit
  differences; no bit-identical or general quality-parity claim is made.
- Float cost temporaries are chunked; patch storage still scales with both grids,
  patch area and channels. Parallel reservations include these buffers, and each
  level checks free CUDA memory with a 512 MiB margin. Presets, busy-state locks,
  version/hash/device provenance and image backend metadata are covered.
- Both CUDA and repaired PyTorch passed all nine original invariant cases:
  `torch_backend_20260912_212429_874906`. Original upstream failures remain
  reproducible without `--repaired`.
- The 14-case Standard matrix at 257x145/five frames passed modulation modes,
  masks/custom edges, reverse/grouped passes, per-level schedules, bounded storage,
  bidirectional flow and three multiguide retargeted images:
  `release_fuoum_20260912_212621_248210`. Three images were inspected for gross
  corruption. A further nine-case scalar Standard matrix passed default temporal
  propagation, sparse/temporal toggles, plain NCC, feathered masks, NeuFlow,
  auxiliary exports and corrected image backend metadata:
  `release_fuoum_20260912_212938_505364`.
- A real nine-frame 512x288 Preview GUI cancellation/restart passed with bounded
  storage: `gui_controller_20260912_212834_678710`. Device-wide memory was
  5,339 MiB before and 5,342 MiB after (snapshots, not attributable leak evidence).
  A two-job 512x288 Preview GUI queue also passed automatic GPU-aware parallel
  admission with the larger PyTorch reservations and bounded storage:
  `gui_controller_20260912_213219_627804`.
- The canonical maintained suite passed **317 tests in 45.954 seconds**, including
  independent scalar SSD/NCC/modulation oracles, brute-force occupancy/voting,
  mask/pruning/rank/iteration checks, allocation guards, instance restoration,
  GUI persistence, scheduling estimates and provenance. New tests preserve lazy
  torch import during GUI construction. The selector layout was inspected.
- See TORCH_BACKEND_AUDIT.md for the repair design and reproducible commands.
  This completes the high-reasoning implementation sequence. Routine validation
  can move to a lower-reasoning model; production/overnight/other-hardware and
  release gates remain open.

## Alternate PyTorch backend fails readiness (2026-09-12)

- Audited the pinned FuouM alternate synthesis backend before exposing controls.
  Added `diagnose_reezsynth_torch_backend.py`, which runs separate CUDA/PyTorch
  workers against nine independent constant-style/cost/shape/NNF invariants.
  It retains incremental reports, native exceptions, source/extension/diagnostic
  hashes, output hashes, device, timings and allocator peaks; failures return a
  nonzero exit status. It is not a production quality/performance comparison.
- CUDA passed all nine; the alternate backend failed four. Retargeting 19x17 to
  23x21 crashes with a tensor-size mismatch; gray and black modulation are
  ignored; high-cost weighted voting changes a constant 127 style into values
  6-19. Repeated reports: `torch_backend_20260912_211602_747745` and the final
  hash-recorded `torch_backend_20260912_211813_699042`.
- Source review identifies incorrect source-sized error buffers, unused
  modulation and denominator clamping. Additional propagation/occupancy,
  single-active-target, iteration semantics and unfolded-memory concerns require
  targeted tests. See TORCH_BACKEND_AUDIT.md for exact evidence and repair scope.
- The canonical maintained suite passed **303 tests in 39.902 seconds**. Five
  new CPU-only tests check the independent cost oracle, ignored modulation,
  constant-color corruption, nonfinite/wrong-grid errors, invalid NNF centers
  and continued report collection after a native exception.
- No installed engine files or rendering defaults were changed. No alternate
  backend selector was added, and the feature is not marked implemented.
  Repairing the algorithm remains high-reasoning work; a repair-versus-deferral
  decision is pending before moving to routine validation on a lower-reasoning
  model.

## Guide modulation verified (2026-09-12)

- Both CUDA engines now accept optional target-grid grayscale modulation for
  individual image guides and numbered video guide groups. Video supports Edge,
  Video, Position, Warped-style and All (including active sparse/mask guides),
  actual target identities in reverse/grouped passes, and bounded frame storage.
  Blank/off defaults preserve existing behavior. Original dimensions, uint8
  grayscale inputs and exact numbered source correspondence are validated.
- Each map repeats across its logical guide's native channels. Legacy images
  pack additional guides before the primary guide; FuouM packs primary first.
  Manifests record processed hashes, channel layouts and video synthesis targets.
  Presets/projects, queue snapshots, recovery fingerprints and GUI busy-state
  locks include map inputs. Manifest failure prevents completion publication.
- Controlled native CUDA probes verified white = unchanged, black = zero local
  guide error, gray 128 = 128/255, and independent 1/3-channel guide weighting in
  both engines: `modulation_20260912_210537_668201`. The Legacy CPU probe proved
  that CPU silently ignores maps: `modulation_20260912_210543_866781` is an
  intentionally failed diagnostic. Enabled Legacy modulation therefore requires
  explicit CUDA and rejects both CPU and Auto before synthesis.
- Real 257x145 Standard five-frame runs passed 13 cases per engine, combining
  per-level schedules, every video modulation mode, grouped/reverse synthesis,
  masks/custom edges and three multiguide image examples. Both used disk-backed
  arrays; FuouM also used measured backward flow. Reports:
  `release_legacy_20260912_210306_031727` and
  `release_fuoum_20260912_210429_083016`. An additional eight-case FuouM run
  covered scalar defaults and NCC on intermediate frames:
  `release_fuoum_20260912_210929_788513`. These establish execution/mapping on
  this host, not general artistic quality improvements.
- The canonical maintained suite passed **298 tests in 41.230 seconds**.
  New tests cover packed channel order, target mapping, map type/size validation,
  CPU/Auto rejection, native-buffer lifetime/restoration, manifest failure,
  bounded storage, GUI persistence and durable queue inputs. Both new control
  layouts were inspected with a real Windows font in offscreen Qt captures.
  Alternate FuouM synthesis-backend implementation remains the next
  high-reasoning checkpoint; external validation/release gates remain open.

## Per-level iteration schedules verified (2026-09-12)

- Both engines support optional search/vote and patch-match schedules, ordered
  coarse-to-fine and aligned at the finest level after pyramid clamping. Missing
  coarse levels repeat the first count; excess coarse entries are dropped.
  Empty schedules preserve scalar defaults. Quality selection clears schedules;
  named presets and projects retain them. See NUMERIC_SETTINGS.md for the schema.
- Legacy receives native C-int arrays through a scoped runner override. FuouM
  receives one scalar per actual backend level, resets on every frame and uses
  finest counts for final 3x3 polishing. Hooks restore on exceptions. Effective
  provenance excludes overridden scalars and links `iteration_schedule.json`.
- Real 257x145 Standard runs each passed eight cases: video, grouped video,
  one-level clamping, Automatic, scalar fallback and three differently sized
  multiguide images. Both used disk-backed clip storage; FuouM also used measured
  backward flow. Reports: `release_legacy_20260912_205556_943246` and
  `release_fuoum_20260912_205631_250465`. These establish correct execution and
  mapping on this host; they do not establish general quality improvements.
- The canonical maintained suite passed **284 tests in 36.586 seconds**, including
  schedule validation/alignment, native-array mapping, per-frame reset, exception
  restoration, effective provenance, disk-preset round trips and GUI busy state.

## Bounded frame storage verified (2026-09-12)

- Added opt-in disk-backed source, style, mask, edge, intermediate and result
  arrays for both video engines. The decoded cache is limited to 64 MiB/eight
  arrays. Full propagation and grouped boundaries are preserved; slices share
  immutable references and explicit frame identities survive eviction. Legacy
  selection/reconstruction and FuouM sparse guides/passes/reconstruction avoid
  whole-clip pixel allocations. Details and limits: FRAME_STORAGE.md.
- The 11-frame Standard matrix passed for both engines with maps, visual and
  numerical flow exports, video encoding and bidirectional FuouM:
  `quality_20260912_171451_703914`. Each decoded-cache peak was 2,359,296 bytes.
- FuouM's 19-case Standard matrix at 257x145 passed with masks/custom edges,
  PST/PAGE, direction modes, temporal/sparse toggles, SSD/NCC, all reconstruction
  solvers and three NeuFlow checkpoints:
  `release_fuoum_20260912_171533_939907`. Legacy's six-case Standard matrix passed
  masks/custom edges, directions and compiled RAFT:
  `release_legacy_20260912_171721_464871`.
- A 101-frame FuouM Preview video/grouped pair passed in 16.875/21.125 seconds:
  `release_fuoum_20260912_171816_458952`. Both decoded-cache peaks remained
  2,359,296 bytes. Scratch writes were 148,222,720 / 259,605,376 bytes, cleaned on
  completion. Process-tree RSS after the jobs was about 1,606 / 1,632 MiB;
  these measurements include native/runtime memory beyond the decoded cache.
- Real 13-frame GUI preview/cache-reuse checks passed for both engines:
  `gui_controller_20260912_171924_604873` (Legacy) and
  `gui_controller_20260912_172011_471202` (FuouM). A 24-frame FuouM cancellation
  after native synthesis and subsequent restart passed:
  `gui_controller_20260912_172128_932523`. Forced termination can retain private
  scratch data in an incomplete output; restart uses a new output folder.
- Completion publication is deferred until scratch cleanup succeeds. Tests
  cover cache eviction/bounds, lossless values, source identities, exact legacy
  sequence boundaries, exception cleanup and cleanup failure. The final canonical
  suite passed **277 tests in 36.027 seconds**.
- Numeric/advanced-control decisions are recorded in NUMERIC_SETTINGS.md.
  Per-level iteration lists, modulation-channel input and alternate FuouM
  synthesis backend remain deferred; overnight/production/other-hardware and
  release validation remain separate outstanding work.

## Bidirectional flow and numerical exports verified (2026-09-12)

- FuouM now offers opt-in independently estimated forward/backward RAFT or
  NeuFlow. Sampling, temporal NNF, accumulated keyframe coordinates and blend
  masks use the field defined on their target grid. The default stays off for
  compatibility. Directional cache entries are keyed by ordered frame content;
  partial cache misses compute only missing pairs with one model instance.
- Both engines can export lossless numerical dx/dy arrays with source/target
  frame numbers, grid identity and processed-pixel units. These exports are
  independent of the existing trimmed visual-flow/error artifacts.
- The 11-frame/three-key Standard/Highest matrix passed for both engines at
  256x144: `quality_20260912_170629_359982`. Each Legacy case exported 10 directed
  fields and each bidirectional FuouM case 20, all finite and correctly labelled.
  NeuFlow Highest also passed at 257x145 with 20 fields:
  `quality_20260912_170734_726296`. These observations establish functionality,
  not general artistic superiority or ground-truth optical-flow accuracy.
- Completed the final-3x3 compatibility fix for still images as well as video.
  FuouM Standard passed video/grouped and all three multiguide image examples:
  `release_fuoum_20260912_170821_878598`.
- Corrected the previous sandbox ACL workaround: the temporary-folder denial
  occurred inside the managed sandbox, not under normal Windows permissions.
  Private TemporaryDirectory handling and visible cleanup errors are restored;
  affected tests and real renders run with approved normal filesystem access.
- Fixed both observed Windows cache publication races: publish validation before
  data visibility, and publish immutable identity/data files without replacing
  valid concurrent readers. Fifty concurrent-producer stress rounds passed.
  The complete maintained suite passed **270 tests in 35.192 seconds**.

## Quality and stability harnesses added (2026-09-12)

- `diagnose_reezsynth_stability.py` alternates both engines across painting,
  poster and flat styles, records each child report and GPU baseline/drift, and
  supports bounded cycles or a deadline-based overnight campaign. A bounded
  128x128 Preview cycle passed all six cases; post-exit drift was 154-292 MiB.
  Retained report: `diagnostic_outputs/stability_20260912_165159_943355`.
- An attempted eight-hour 384x216 Standard campaign completed 94 passing
  isolated render cases before its 95th case was marked failed solely by the
  device-wide post-exit guardrail (+2,448 MiB versus a 2,048 MiB limit).
  That child render itself passed. The host was an active WDDM desktop with
  Photoshop, browsers, ChatGPT, Docker and other graphics clients, and
  `nvidia-smi` showed total device use rising from 4,130 to 7,102 MiB. All 95
  child suites exited successfully. The memory change cannot be attributed
  from device-wide samples; the overnight result is inconclusive.
  Retained report: `diagnostic_outputs/stability_20260912_193422_040460`.
  Repeat the overnight campaign on an otherwise idle host, or with an
  attributable per-process metric, before treating it as release evidence.
- `diagnose_reezsynth_quality.py` validates user-supplied numbered frames,
  keyframes and optional masks, then produces a both-engine Standard/Highest
  review matrix with videos, auxiliary maps/flow and descriptive key-boundary
  metrics. Legacy and FuouM Standard both passed the bundled 11-frame input at
  256x144. Retained FuouM report: `quality_20260912_165006_794209`.
- That Standard FuouM run exposed two integration defects now covered by tests:
  the pinned engine supplied `None` modes to its optional final 3x3 CUDA pass,
  and Python temporary-directory ACL tightening could lock an isolated Windows
  worker out of its cache. The adapter now repairs only missing final-pass modes
  and uses a unique normally inherited cache directory with cleanup.
- These are bounded functional observations. Overnight/multi-GPU behavior and
  general visual-quality conclusions remain unverified.
- The expanded canonical suite passed **263 tests in 35.050 seconds**. One earlier
  run encountered an intermittent Windows sharing violation in the pre-existing
  parallel cache-publisher test; that test passed three immediate repetitions and
  the subsequent complete suite passed.

## Maintained-suite CI added (2026-09-12)

- `run_maintained_tests.py` is now the single canonical module list, excluding the
  two upstream render demos and all real GPU diagnostics. A Windows GitHub Actions
  workflow runs it for pushes and pull requests using Python 3.11, CPU PyTorch,
  offscreen Qt and hidden CUDA. Workflow permissions are read-only.
- Real GPU checks are a separate workflow-dispatch option targeting only a
  preconfigured self-hosted Windows runner labelled `reezsynth-gpu`; they verify
  both included engines and run bounded Legacy/FuouM diagnostics. Reports are
  uploaded only for that explicitly requested job.
- The canonical runner passed **258 tests in 35.498 seconds** locally with the same
  CUDA-hidden/offscreen flags. It also passed normally in 35.440 seconds. The
  workflow syntax and routing were reviewed locally, but no remote Actions run is
  claimed because the commit has not been pushed.

## Included-engine GUI setup controls verified (2026-09-12)

- Settings now has an **Included engine setup and maintenance** panel. It reports
  both supported pinned revisions, the current GUI interpreter and configured
  FuouM source/worker paths. Its asynchronous readiness action runs the existing
  Legacy CUDA/native/compiled-RAFT checks and FuouM's check-only path including
  RAFT and NeuFlow assets, streaming combined output to Diagnostics.
- Confirmed maintenance buttons target only the Legacy RAFT extension in the GUI
  environment or the FuouM native extension in its dedicated runtime. FuouM has an
  explicit forced-recompile mode for this action. Neither button updates, repairs
  or replaces a pinned source checkout/environment. Runtime selectors, competing
  component actions and window close are guarded until the child process exits.
- The full maintained suite passed **257 tests in 34.923 seconds**. The actual
  combined readiness command then passed in 15.7 seconds on this installation:
  exact Legacy/FuouM revisions, package consistency, four Legacy runtime hashes,
  CUDA 12.8, native EbSynth and compiled RAFT imports, FuouM environment/native
  import and all standard RAFT/NeuFlow checkpoints. It loaded no models, rendered
  nothing and made no installation changes. No rebuild was needed.

## GPU-aware parallel scheduling verified (2026-09-12)

- Parallel queues now reserve conservative per-job VRAM estimates derived from
  processed resolution, engine, optical-flow path and GPU blending. Admission
  combines those reservations with live `nvidia-smi` free-memory telemetry and a
  10% safety reserve bounded to 1-4 GiB. The initial worker limit remains a hard
  cap; zero now means GPU-aware automatic rather than unlimited. Without NVIDIA
  telemetry, automatic mode safely uses one worker. A single estimate larger than
  the safe budget is admitted alone so the queue cannot deadlock.
- Queue logs and row tooltips report the selected GPU, current/free memory, safety
  reserve, estimated peak, processed size, engine and worker PID. Finish records
  include the post-exit device snapshot. These estimates are deliberately
  conservative admission heuristics, not measured per-process allocation claims.
- The maintained suite passed **253 tests in 34.995 seconds**. A real automatic
  two-job FuouM GUI queue then passed at 512x288: each worker reserved 2.4 GiB
  against 28.2 GiB initially free with a 3.2 GiB reserve, both completion markers
  were written, both PIDs exited, and the final snapshot again showed 28.2 GiB
  free. Retained diagnostic and controller log:
  `diagnostic_outputs/gui_controller_20260912_160955_548162`.

## Local review fixes verified (2026-09-12)

- Both engines now share frontend-owned, project-local content-addressed caches
  for computed edges and directional optical-flow pairs. Identities include
  processed frame bytes/shape, engine revision, flow architecture/model and
  actual checkpoint hashes. Loads validate artifact checksums, shape, numerical type and finiteness;
  writes are atomic and tolerate identical parallel producers. Flow arrays are
  memory-mapped during synthesis, including immediately after FuouM first computes
  them. Real three-frame GUI runs for each engine then changed Uniformity and
  completed a second queue with all three edges and both flow pairs reused.
  Retained final-format diagnostics: `gui_controller_20260912_151314_436376`
  (Legacy) and `gui_controller_20260912_151327_547807` (FuouM). This reduces repeated work and
  resident flow memory but is not full source/result-frame streaming.
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
- Full maintained suite: **249 tests passed in 31.226 seconds**. This includes
  default dual-engine setup, validated precomputation caching, queue recovery, optional-flow readiness and
  provenance, timing/completion tests, custom-kernel readiness, and metadata
  regressions, including simultaneous cache publishers. Expected upstream deprecation/offscreen Qt warnings remain; no
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
