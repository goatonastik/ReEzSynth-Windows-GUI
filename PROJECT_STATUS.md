# Project status

Updated 2026-09-11. Live files are authoritative. Usage and settings are described
in [README.md](README.md).

Latest real-render report: 3840x2160 video on RTX 5090 failed in RAFT CorrBlock
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
python -B -m unittest test_reezsynth_gui test_reezsynth_lifecycle test_reezsynth_worker test_reezsynth_options test_reezsynth_render_adapter test_reezsynth_grouped test_reezsynth_artifacts test_reezsynth_destinations test_reezsynth_image -v
```

Historical baseline: 66 tests passed; current full suite is 102 tests (see above).
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
