# Project status

Updated 2026-09-10. Live files are authoritative. Usage and settings are described
in [README.md](README.md).

Full upstream feature parity is tracked in [EZSYNTH_PARITY.md](EZSYNTH_PARITY.md).
The renewed local review pinned Trentonom0r3/Ezsynth at b198f2d7051eee542c4efc51c2d43dc442630bbf,
confirmed the existing backend-forwarding differences, and reran all 66 tests
successfully (4.848 s). Grouped-video parity is now implemented with mock validation;
image synthesis and model/architecture selection remain pending. Auxiliary exports
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

Rendering uses RAFT Sintel and explicitly selects runner.eb.backends["cuda"].
Single-frame jobs do not initialize the engine; optional masks composite styled
pixels over the source. Cross-keyframe blending is available in Blend / Flow;
Image Synthesis remains planned.
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
python -B -m unittest test_reezsynth_gui test_reezsynth_lifecycle test_reezsynth_worker test_reezsynth_options test_reezsynth_render_adapter -v
```

Final execution: all 66 tests passed in 4.913 seconds with the interpreter above.
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

- `.gitignore` has the correct filename and ignores common weights, but three
  RAFT .pth files are already tracked (about 46 MB total). No files were untracked.
- Tracked source bundle, example inputs/keyframes, backup and output_synth PNGs
  remain; review provenance before changing their tracking. Generic renders/
  and output_synth/ are not covered by current ignore rules.
- `requirements.txt` omits PySide6. The working dependency snapshot includes
  CUDA PyTorch pins but lacks complete wheel-index/model provisioning guidance.
  Clean-environment reproduction has not been demonstrated.
- History retains older saved paths even if no longer present; new entries must
  be valid directories. This behavior has regression coverage.
- No commit/push or GPU render was performed. Next manual step, with approval:
  compare sequential/shared and bounded parallel GPU runs, masks/edge settings,
  memory after exit and native completion sound. Do not claim mock-process tests
  establish real GPU speed, stability or memory behavior.
