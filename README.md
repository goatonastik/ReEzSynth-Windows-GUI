# ReEzSynth Windows GUI

A Windows graphical front end for preparing and running keyframe-based
video stylization with Ezsynth and EbSynth.

ReEzSynth aims to make the workflow easier to manage: select your source
image sequence and styled keyframes, configure frame ranges, queue renders,
and monitor progress without manually preparing each rendering job.

Rendering now includes a **Synthesis engine** selector for Trentonom0r3/Ezsynth
and FuouM/ReEzSynth. Standard setup installs both engines. The original engine
remains the initial selection. FuouM uses a separate Python runtime and supports
image synthesis, RAFT/NeuFlow video, masks/custom guides, exports, and grouped
blending or directional passes.
Engine-specific controls are labelled and greyed out when inapplicable. See
[dual-engine setup and capabilities](DUAL_ENGINE.md), the
[remaining-work checklist](WORK_REMAINING.md), and [release gates](RELEASE_AUDIT.md).
Candidate source/installer builds are documented in [PACKAGING.md](PACKAGING.md);
the packaging workflow never publishes a release automatically.

## Project goals

- Make keyframe-based rendering more accessible through a Windows interface.
- Provide clear control over frame ranges and rendering options.
- Organize multiple render jobs into a manageable queue.
- Show useful progress, logs, and error messages.
- Reduce repeated startup overhead while keeping worker cleanup explicit.

Worker reuse is enabled by default for queued renders. Each job initializes
its own rendering engine, while the Python worker stays running between
jobs and exits when the queue finishes. An isolated-worker option is
available for troubleshooting memory growth or instability.

## Status

ReEzSynth is under active development. The interface and workflow may
change as rendering, queue management, and resource handling are refined.

Contributions are welcome under the repository's GNU AGPL v3 license. See
[CONTRIBUTING.md](CONTRIBUTING.md) before submitting code or assets,
[SECURITY.md](SECURITY.md) for private vulnerability reporting, and
[SECURITY_CHECKS.md](SECURITY_CHECKS.md) for the automated checks and evidence
required before a downloadable public release.

## Windows installation

The Windows installer presents four clearly labeled prerequisite checkboxes on its
Additional Tasks page: Git, Miniforge/Conda, Visual Studio 2022 C++ Build Tools with
MSVC and a Windows SDK, and CUDA Toolkit 12.8. All are selected by default and mean
"install only if a compatible copy is missing." Its finish page has a fifth,
default-selected **Set up and validate the ReEzSynth engine environment now**
checkbox. The same complete setup is available later from **Start > ReEzSynth >
Install ReEzSynth prerequisites and dependencies**.

Setup requires an NVIDIA CUDA-capable GPU and an installed NVIDIA driver. It uses
Windows Package Manager (`winget`) for third-party prerequisites, displays their
package identities before running them, and may show Windows administrator
approval prompts. It installs several gigabytes and can take a substantial amount
of time. Do not close the setup window while an installer or engine build is
running.

Prerequisites and ReEzSynth components are installed in this order:

1. Verify 64-bit Windows, `winget`, the NVIDIA GPU driver, and free access to the
   required package sources.
2. Keep an existing Git for Windows installation, or install `Git.Git`.
3. Keep an existing Conda distribution, or install Miniforge with
   `CondaForge.Miniforge3`. ReEzSynth never installs packages into Conda `base`.
4. Keep compatible Visual Studio 2022 C++ x64 tools, or install
   `Microsoft.VisualStudio.2022.BuildTools` with the C++ workload, recommended
   components, and Windows SDK. This step can require administrator approval.
5. Keep an exact CUDA 12.8 toolkit, or install `Nvidia.CUDA` version 12.8. The
   NVIDIA driver-reported CUDA capability is not a toolkit and does not provide
   `nvcc`.
6. Create a new Python 3.11 Conda environment named `reezsynth`; install pinned
   PyTorch CUDA 12.8 and frontend dependencies; and verify the Legacy engine,
   bundled EbSynth DLL, RAFT checkpoints, and CUDA correlation extension.
7. Create the separate FuouM worker environment, obtain its pinned source and
   checksum-verified NeuFlow checkpoints, build its native CUDA extension, and
   verify both engines.
8. Save the successful Conda launcher location and environment name, then launch
   ReEzSynth with `run_reezsynth.bat`.

Compatible existing Git, Conda, compiler/SDK, and CUDA installations are preserved.
Setup confirms runnable Git and Conda commands, Visual Studio 2022 with an x64 MSVC
compiler and complete Windows SDK headers, and `nvcc` reporting CUDA 12.8. Clearing
a checkbox prevents installation of that shared component; detection still uses a
compatible existing copy, while an absent requirement produces a feature-specific
warning and prevents engine setup from changing environments. CUDA detection refreshes
`CUDA_HOME`, `CUDA_PATH`, and the running process's `PATH` before engine setup.
Setup refuses to overwrite an unrelated existing `reezsynth` Conda environment or
FuouM worker environment. Before creating the application environments it records
an app-local resume marker containing the exact Conda executable, environment name,
and app-local FuouM worker path. If that setup is interrupted, running the same Start-menu action continues
the recorded installation with idempotent package steps; a missing, unreadable, or
mismatched marker stops instead of modifying an existing environment. Partial
installations are retained for diagnosis and are never automatically deleted.

Uninstalling ReEzSynth removes the application, shortcuts, app-local FuouM worker
environment, downloaded engine source, local and compiled-Python caches, launcher
files, and an interrupted-setup marker. It preserves Git, Miniforge/Conda, Visual
Studio Build Tools, CUDA, the selected external Conda environment, external projects
and renders, and user test media because those components may be shared or user-owned.

If an installer reports that Windows must restart, restart Windows and run the
Start-menu setup shortcut again. The bootstrap rechecks every prerequisite and
skips compatible components already installed. It does not restart Windows by
itself and does not silently replace environments.

To preview the prerequisite plan without installing anything, open PowerShell in
the installed ReEzSynth directory and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_reezsynth.ps1 -Plan
```

To verify an existing ReEzSynth installation without installing prerequisites or
changing environments:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_reezsynth.ps1 -CheckOnly
```

For manual installation, install the same components in the numbered order above,
then run `setup_reezsynth.ps1`. Detailed custom-Conda, troubleshooting, optional
component, and native rebuild instructions are in [Windows setup](INSTALL_WINDOWS.md).

## Using the interface

For a new machine, use the installer workflow above or follow
[Windows setup](INSTALL_WINDOWS.md). The setup script
creates the GUI environment and the separate FuouM worker environment, installs
pinned dependencies and FuouM's RAFT/NeuFlow checkpoints, and checks both engines
without rendering. The installer bootstrap supplies Git, Miniforge, the CUDA 12.8
toolkit and Visual Studio 2022 C++ build tools when compatible installations are
not already present.

Launch `run_reezsynth.bat` with the existing `reezsynth` Conda environment.
The entry point is `reezsynth_gui.py`.
The logo and tabs share the top row; **Save Log...** stays available at its right
from every tab, including while a worker is running.

- **Video / Keyframes:** select or drop project, source, styled-keyframe and
  optional mask directories. Sources must be consecutive numbered PNG/JPEG
  images; keyframe numbers must match sources. Set inclusive propagation ranges.
- **Rendering:** edit guide weights, uniformity, patch size, pyramid levels,
  iteration counts, polishing, edge method, masks, RAFT model and EbSynth backend.
  Preview, Standard, and Highest reset only synthesis parameters while preserving
  guide weights and all controls outside this tab.
- **Legacy keyframe preservation:** **Current behavior** retains the original
  Trentonom0r3 blend assembly. **Exact output** restores every supplied styled
  keyframe after synthesis without changing neighboring frames. A configured
  mask/background composite is then applied consistently to all frames, including
  keys; without masks, the loaded keyframe is byte-exact at the processing size.
  **Transition-aware** also restores each key and, over the two neighboring frames
  on either side, favors the motion-propagated candidate from that key to reduce a
  one-frame boundary pop. FuouM already passes styled
  keyframes through exactly, so this selector is disabled for that engine.
- **Masks:** tick the Masks checkbox beside its directory input. Untick it to ignore
  the remembered mask folder for rendering and compositing. Supply one mask per source frame,
  matching its number and dimensions. White selects stylized pixels; black keeps
  source pixels. Feather size is zero or an odd integer. With transparent RGBA
  styles, style alpha participates in the source-over composite: transparent
  styled areas reveal the opaque source frame, so masked output is opaque there.
  Disable Masks when the rendered RGBA transparency itself must be retained.
- **Custom edge guides:** select a numbered edge-guide sequence and enable **Use
  custom edge-guide frames** in Rendering to use those maps instead of automatic
  Classic, PST, or PAGE edge generation. Edge-guide numbers and dimensions must
  exactly match the selected source video. The folder is remembered in directory
  presets and projects; it is ignored until the checkbox is enabled.
- **Live previews:** **Previews** opens a resizable window showing each completed
  synthesis frame in its keyframe/direction tile, during shared, isolated, or
  parallel rendering. Capture and image loading run only while the window is open;
  reopening shows the last captured images and resumes on the next finished frame.
  Previews are capped at 960 pixels on the longest edge and precede final mask
  compositing/grouped blending; saved renders retain the selected resolution.
  Queue pairs/Square grid is selected in this window. Settings controls its image
  cap (default 8); later active jobs replace earlier completed jobs at the cap.
  Small latest-frame files live under each job's `.reezsynth-preview/` directory.
- **Queue recovery:** every started queue receives an atomic
  `.reezsynth-queue.json` journal. After a crash or interrupted run, use
  **Recover Queue...**; recovery never starts automatically. Completed jobs are
  skipped. Jobs whose JSON hash or input path/size/modification time changed are
  blocked for review. An unchanged unfinished job can resume, while a job with
  partial output restarts in a new `_recovered` sibling so existing files are
  never overwritten. The last unfinished journal is noted at the next startup.
- **Reusable precomputations:** video jobs automatically keep validated optical
  flow and computed edge maps under the selected project's `.reezsynth-cache`.
  Cache identities include processed frame content and shape, engine/revision,
  edge method, and the selected flow checkpoint's SHA-256; changing synthesis
  settings alone can therefore reuse safe results. Files are checksum, shape,
  type and finiteness checked before use and written atomically for parallel workers. Cached flow is
  memory-mapped during synthesis to reduce resident RAM on longer clips. Source,
  style and final result frames are still held in memory, so this is not a fully
  streaming renderer. Close all workers before manually deleting the cache to
  reclaim disk space; it will be rebuilt when needed.
- **Settings:** includes optional discovery, automatic start, parallel rendering,
  notifications and startup choices. **Included engine setup and maintenance**
  reports pinned versions, runs read-only readiness checks for both standard
  engines, and provides confirmed native-extension rebuild actions. Checks and
  builds stream details to Diagnostics; rebuilds do not replace pinned source or
  environments.
- **Diagnostics / Log:** retains all queue runs for the open application session.
  Each queue has prominent start/end separators; use **Save Log...** to write the
  complete current session to a `.log` or `.txt` file, including an active run.
  Logs include effective render settings, per-frame EbSynth time, time between
  synthesis calls (flow/guides/blending), and total preview-capture time. These
  distinguish synthesis cost from preview work when investigating slowdowns.
  To compare the GUI with a direct renderer process, run
  `benchmark_current_gui_settings.bat` after saving a GUI log. It clones the last
  completed job in `reezsynth-session.log` into a new sibling output folder and
  invokes `reezsynth_jobs.py job.json` in a fresh process. The resulting
  `cli-benchmark.log` contains the same render timing lines, an automatic
  engine-specific summary, and a direct CLI wall time. FuouM call times include
  preview/progress work and exclude precomputation, grouped reconstruction and
  output saving; they are not isolated native-kernel timings. A successful exit
  and `COMPLETE.txt` establish completion, not the presence of timing lines.
  You may instead pass an explicit job JSON path to the batch file. Existing
  outputs are never overwritten.

Projects and shareable preset libraries may also be saved or imported as `.yaml`
or `.yml`. JSON remains the default. YAML uses PyYAML safe loading and the same
version and field validation as JSON; job files and worker protocol remain JSON.
Queue journals are local recovery records, not shareable presets: they contain
absolute input and runtime paths and should be removed or reviewed before sharing
a render folder.
Precomputation caches are also local generated data and are ignored by Git.

### Presets and startup behavior

Key, video and mask-guide weights occupy a column between their directory inputs
and Select buttons. The remaining Guide weights are underneath the directories. Key weight
controls the style-to-guide ratio: because the native library fixes style weight
at 1, the adapter divides all guide weights by the key weight (minimum 0.001).
Video weight controls the source-image guide. Mask guide weight adds a source/target
mask correspondence guide when masks are enabled; zero disables that additional
guide without disabling mask compositing. Defaults (key 1, mask guide 0) preserve
previous rendering behavior. All are saved in weight presets and projects.

The default quality preset is Standard. Preview is the lower-cost draft profile;
Highest uses Standard settings with automatic pyramid depth. Video weight 6, Mapping 2 and Deflicker
0.5 match Ezsynth's RunConfig defaults.
Patch size must leave at least one usable pyramid level: each processed style
and target dimension must be at least twice the patch size plus one pixel.
Invalid combinations report an error before engine initialization. Current numeric
ranges and their limitations are listed in [NUMERIC_SETTINGS.md](NUMERIC_SETTINGS.md).
Processing size defaults to Original resolution; explicitly saved size choices
remain respected. With Original resolution selected, video jobs check selected
source-frame and keyframe dimensions before creating outputs or launching workers.
Mismatches show the filename, actual size and expected size. Image Synthesis keeps
its separate rule allowing target dimensions to differ from source/style dimensions.
Choose an exact Processing size preset (512/1024 square, 720p or 1080p landscape
or portrait), or Custom to enter exact width and height. Preset dimensions are
shown but locked; Custom dimensions are editable and apply to video and Image
Synthesis output. Exact sizes resize to the chosen dimensions; a different aspect
ratio stretches the input rather than cropping it. Original shows source dimensions
(the target image on Image Synthesis), or a dash until an input is available.
Older projects/presets using maximum-width limits reopen as **Legacy max width
512/960**. This compatibility entry preserves aspect ratio and never upscales;
image source and target groups retain their separate sizes. New presets continue
to use the exact sizes above. Select one explicitly to replace a legacy limit.
Existing saved weights are preserved. The visible guide order is Mapping,
Deflicker, Diversity.

Rendering labels relate familiar Beta concepts to Ezsynth controls: Mapping
(position guide), Deflicker (warped-style guide), and Diversity (uniformity).
These are related controls, not a promise of identical EbSynth Beta behavior or
matching numerical scales. The native weighting model is described in the
[EbSynth source documentation](https://github.com/jamriska/ebsynth#examples).

The flow controls offer RAFT with bundled Sintel (default) and Kitti weights, plus
the upstream EF-RAFT and FlowDiffuser architecture/model pairs for video. EF-RAFT
and FlowDiffuser are optional: a queue checks their exact files (including
FlowDiffuser's pinned dependencies and offline backbones) before it creates output
or starts a worker. Use
`check_reezsynth.py --flow-extras` to see what is missing. The default install and
existing projects remain on RAFT; Memory-efficient RAFT correlation applies only
to that architecture. EbSynth backend defaults to CUDA; Auto lets the native library decide and
CPU avoids its CUDA synthesis backend. Video optical flow can still use PyTorch
CUDA when it is available, so CPU EbSynth is not a complete CPU-only video mode.
When PyTorch CUDA is unavailable, CPU/Auto jobs can proceed with CPU optical flow,
Classic edges, GPU blending off and memory-efficient CUDA correlation off.
`diagnose_ebsynth_backend.py` performs bounded real image/video frontend checks in
fresh CUDA-hidden workers. CPU and Auto passed locally on generated diagnostic inputs; this
is same-host functional evidence, not CPU-only installation portability coverage.
Single-frame keyframe copies require no flow weights or GPU initialization.

Settings > **Optional flow components** displays each optional model's readiness.
Its install buttons copy user-selected official checkpoint files into the expected
directories; the FlowDiffuser component button installs the tested dependency set
and downloads two checksum-pinned Twin-SVT backbones only after confirmation.
Rendering never downloads models implicitly. An unavailable architecture returns to RAFT with
an explanation instead of allowing an invalid queue setting.

**Pyramid levels: Automatic** forwards the upstream `-1` setting, which chooses
the available depth from image and patch dimensions. Fixed values remain available.

Directories, Output naming, Guide weights, Rendering, Blend / Flow, Application,
and Image Synthesis presets are independent. Every dropdown includes a protected
**Default** entry with the recommended built-in values. The bottom of Settings
has **Reset all settings to defaults**, which restores those values after
confirmation without deleting saved projects or custom preset files. Resetting
directory inputs rebuilds the queue from those default inputs.
Select from a dropdown; **+** saves the current group and **-** removes it after
confirmation. Saving pre-fills the selected name and confirms overwriting an
existing name. Named Rendering presets include only controls from Rendering;
they do not alter processing resolution, output naming, or Blend / Flow. Per-job
frame ranges belong in saved projects.

The versioned JSON library is `%LOCALAPPDATA%/ReEzSynth/presets.json`.
Settings provides Import/Export buttons; import replaces the local library after
confirmation. Directory presets contain paths that may need adjustment on another
computer. Corrupt preset libraries are preserved and reported in Diagnostics.

Each group can start with defaults, a named preset or its last-used values.
`application.json` stores local startup choices separately from shareable presets.
`last-used.json` stores field values after a short save debounce and on close.
Folder history remains in QSettings. Remembered setup does not recover unsaved
custom queue ranges; use Save/Open project. Older version-1 projects preserve
saved row names and get the original quality defaults for missing new settings.

### Per-level iteration schedules

Rendering controls include optional **Search/vote schedule** and **Patch-match
schedule** fields for both engines. Enter up to 32 comma-separated integers
from 1 to 1000, in coarse-to-fine order. Blank uses the corresponding scalar
iteration count. Schedules align at the finest level: `12, 8, 4` becomes `8, 4`
if only two levels fit, or `12, 12, 8, 4` if four fit. Quality presets clear
schedules. Projects and named render presets retain them. A scheduled render
records its resolved counts in `iteration_schedule.json`; FuouM's extra 3x3
pass uses the finest counts, while Legacy retains its DLL's polishing behavior.

### Guide modulation

Optional grayscale maps vary guide strength across the target image: white keeps
the normal weight, black removes that guide's local cost, and intermediate values
multiply it by `value / 255`. This changes matching costs, not output opacity or
mask compositing. Leave modulation off/blank to preserve the existing behavior.
Both engines support this through CUDA. Legacy **CPU and Auto are rejected** when
modulation is enabled because its CPU implementation ignores these maps.

For video, select **Video modulation** under Rendering and a numbered modulation
folder whose frame numbers exactly match the source sequence. Apply the map to
Edge, Video, Position, Warped-style, or All guides. All includes active sparse and
mask guides. Maps follow the actual target frame through forward, reverse and
grouped passes. Single-frame keyframe copies perform no synthesis or modulation.
For still images, select an optional **Primary modulation** map and/or maps in the
additional-guide table; each affects only its corresponding logical guide.

Maps must be single-channel, 8-bit grayscale images matching the original target
dimensions (use lossless PNG). RGB and 16-bit maps are rejected. Processing-size
changes resize maps with area interpolation; native engines handle their own
pyramid resizing. A map is repeated across all channels of its logical guide;
guides without maps retain full weight. Projects/presets preserve selections,
queued jobs freeze numbered paths, and recovery checks the map inputs.
`modulation_manifest.json` records processed-map hashes, native channel layouts
and video target identities. Video map arrays support disk-backed frame storage;
the packed native modulation buffer still requires per-frame memory.

### Experimental FuouM PyTorch synthesis

Select FuouM, then **Synthesis backend > torch** under Rendering to use the
versioned repaired PyTorch search. `cuda` remains the default native implementation.
Both run on CUDA; this is not a CPU fallback. Projects/presets retain the choice.
The repaired path supports images, video/grouped passes, guides/modulation,
SSD/NCC, voting, iteration schedules, masks and temporal NNFs.

Its synchronous search can produce different results and generally costs more
time and memory. Parallel admission includes patch-buffer reservations, and a
per-level free-memory guard rejects oversized work with guidance to reduce
processing/patch size or choose `cuda`. Disk-backed clip storage does not bound
these GPU buffers. Manifests record `frontend-torch-v1` and its adapter hash.
See [TORCH_BACKEND_AUDIT.md](TORCH_BACKEND_AUDIT.md) for repairs, evidence and limits.

### Output naming

Output naming sits to the right of the directory inputs. By default outputs go
to `<project>/renders/<batch>/<job>`. Disable **Create a batch folder for each run**
to put job folders directly in the selected output location. The location choices
include `outputs/` inside the keyframes or video folder, the parent of either input
folder, the project folder, or a custom folder (typing, selection and drag/drop).
The original project/renders location remains available and is the default for old
projects. Existing job folders receive numeric suffixes instead of being overwritten.
Output location and batch choices are saved in projects and rendering presets.
Default templates:
`batch_{date}_{time}_{microsecond}` and `out_{key:0{padding}d}`.

Batch fields: `date`, `time`, `microsecond`, `quality`, `width`,
`keyframe_dir_name`, `video_dir_name`.
Additional job fields: `key`, `start`, `end`, `index`, `padding`, `key_name`
(the styled image filename without extension).

Suffix checkboxes edit the job template for filename, date/time and input-folder
names. Apply to Queue confirms replacing row names; it never renames rendered
files. Batch collisions receive numeric suffixes. Job folders must be distinct
relative paths without overlap or traversal.

### Optional automation and parallel rendering

Discovery matches sibling folders such as `keys_shot01` and `video_shot01` inside
the project directory, including nested directories. Prefixes are editable;
ambiguous matches prompt for selection. Discovery is disabled by default.

Automatic start is disabled by default. When enabled, input edits or directory
preset selection can start a validated queue after a short delay. Enabling it
with inputs already present also checks them. It can wait for a complete mask
sequence; tick Masks separately to apply masks. Startup restore and Open
project never automatically render. Identical input identities are not repeatedly
launched; manual Run All remains available. Folders are not continuously watched
for files arriving after validation.

Sequential rendering remains the default and reuses one worker per queue unless
disabled. **Enable parallel rendering** uses independent isolated workers, with
an initial hard limit of 2. A limit of 0 selects GPU-aware automatic scheduling.
The scheduler combines current NVIDIA free-memory telemetry with conservative
per-job reservations based on resolution, engine, flow model and GPU blending;
it also leaves a desktop/error safety reserve. If telemetry is unavailable,
automatic mode runs one worker at a time. Positive limits remain hard caps. The
queue log and job tooltips report the GPU snapshot, estimate and worker PID. It uses more GPU memory;
worker lifecycle has been checked with mocks and bounded real GPU jobs, while the
estimates remain conservative admission heuristics. Stop/Close waits for every worker
to exit. A render failure halts pending work and stops other active workers;
completed output is retained.

Completion sound defaults to queue completion. Choose per-render notification,
queue notification, both or neither, and optionally select a WAV file.
`assets/complete.wav` is a generated placeholder tone that may be replaced.

### Memory-efficient RAFT and GPU memory errors

For high-resolution video, enable **Memory-efficient RAFT correlation
(CUDA)** in Rendering while leaving Processing size at Original. This
option is saved in projects/rendering presets and defaults off for older projects.
It applies to video, including grouped jobs; Image Synthesis does not use RAFT.

The Windows setup installs the bundled compiled `alt_cuda_corr` extension; no
extra commands, CUDA Toolkit, or C++ compiler are needed after downloading a
complete repository release. It supports the project-pinned Windows x64 CPython
3.11/PyTorch 2.11.0+cu128 environment and NVIDIA architectures 7.5, 8.0, 8.6,
8.9 and 12.0. See [memory-efficient RAFT support](INSTALL_WINDOWS.md#memory-efficient-raft-extension)
for compatibility and manual rebuilding.
It retains full-resolution RAFT features, model weights, search neighborhoods and
iteration counts. The former pure-PyTorch implementation was too slow in the user's
4K trial and remains only as a numerical/benchmark reference. Missing or incompatible
extensions produce an error; there is no automatic slow fallback. The original
all-pairs implementation remains available when the checkbox is off.

GPU comparisons against all-pairs correlations and a random-weight RAFT forward
pass passed within numerical tolerances. On the development RTX 5090, a synthetic
4K-equivalent correlation lookup took about 45 ms versus 368 ms for the former
PyTorch implementation (about 8x faster), with 1207 MiB peak PyTorch allocation.
These are correlation-only measurements, not total render time or whole-render
VRAM requirements. Real-video visual quality remains unverified; bit-identical
results are not promised. Other stages can still exhaust GPU memory.

Explicit CUDA out-of-memory exception lines trigger one nonblocking error popup
per queue, including the original error details. Generic crashes and CPU memory
errors are not labelled GPU OOM. Shared, isolated and parallel worker shutdown
continues while the popup is visible. No automatic resizing or retry occurs.

### Regression tests

Run these explicit modules in the existing environment, without real GPU renders:

```powershell
python -B -m unittest discover -p "test_reezsynth_*.py" -v
```

`python -B run_maintained_tests.py` is the canonical equivalent used by CI.
GitHub-hosted Windows CI installs CPU PyTorch and sets CUDA hidden; real GPU
diagnostics are available only through an explicit workflow-dispatch choice on a
preconfigured self-hosted runner labelled `reezsynth-gpu`.

Tests isolate settings/files, use offscreen Qt, mock workers and a fake engine,
and include CPU image handling and CPU RAFT numerical checks without pretrained
weights. Audio playback is mocked. The canonical runner selects the maintained
lightweight suite.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for results and remaining manual checks.
Bounded GPU memory and output checks have passed; overnight/multi-GPU stability,
general visual-quality review and native audio playback remain unverified.
Use `python -B diagnose_reezsynth_stability.py --plan` to inspect the alternating
Legacy/FuouM campaign, then omit `--plan` for the default eight-hour run. Use
`--cycles 1` for one bounded pass through painting, poster and flat styles.
For user-supplied numbered frames and styled keyframes, run
`python -B diagnose_reezsynth_quality.py --video-dir <frames> --keyframe-dir <keys> --plan`,
review the matrix, then omit `--plan` to render Standard and Highest outputs from
both engines with videos, raw maps, flow visualizations and boundary metrics.
The matrix also verifies numerical flow exports. Add `--bidirectional` to use
independently estimated FuouM flow directions, and `--fuoum-flow-engine NeuFlow`
to exercise NeuFlow. In Rendering, **Estimate both flow directions** is opt-in;
**Export numerical flow vectors** saves lossless dx/dy arrays and explicit frame
direction metadata under `flow_vectors/`.
Rendering also has an opt-in **Store clip frames on disk to limit RAM** switch.
It keeps complete propagation/blending sequences while using a bounded decoded
array cache and temporary disk storage. It needs additional disk space and I/O;
per-frame GPU requirements are unchanged. See [FRAME_STORAGE.md](FRAME_STORAGE.md)
for its memory scope, cleanup behavior and diagnostic commands.
For small real CUDA checks of the frontend adapter, run
`python -B diagnose_reezsynth_adapter.py` for video masks/custom edge guides,
`python -B diagnose_reezsynth_adapter.py --image` for Image Synthesis, or
`python -B diagnose_reezsynth_adapter.py --grouped` for grouped blending. They use
procedurally generated inputs and write ignored output under `diagnostic_outputs/`.
The separate `python -B diagnose_reezsynth_torch_backend.py` command compares
FuouM's CUDA and alternate PyTorch backends against controlled mathematical
invariants. Add `--repaired` to test the frontend repair layer. Without it, the
original upstream backend still fails and a nonzero result is expected for
`torch`/`both`. See
[TORCH_BACKEND_AUDIT.md](TORCH_BACKEND_AUDIT.md) for failures and repair scope.
Add `--shared-worker` to the adapter diagnostic commands to run through the persistent
worker protocol and verify its completion event and normal cleanup/exit.
For the video diagnostic, also add `--live-preview` to renew a preview-window
lease and verify that a synthesis-stage thumbnail is produced by the worker.
Use `--reuse-worker` to send two independent video jobs through one persistent
worker and verify both completion events before it exits.
Use `--cancel-worker` to force-kill a worker after synthesis begins and verify
that it exits without writing `COMPLETE.txt`; it cannot be combined with the
preview or reuse checks.
Use `--parallel-workers` to run two independent jobs concurrently through the
same isolated-job entry point used by parallel rendering.
For an end-to-end offscreen GUI-controller check with temporary settings, run
`python -B diagnose_reezsynth_gui.py`. It opens the Preview window, runs one
small shared-worker queue, verifies a preview tile and completion marker, then
waits for the UI to unlock.
Add `--parallel` to run two independent jobs through the GUI's ParallelQueue.
Add `--cancel` to stop a longer small shared-worker queue after synthesis begins
and verify asynchronous worker finalization without `COMPLETE.txt`.
Add `--close` to exercise the same shutdown path through the window-close
confirmation and verify that the window closes after worker finalization.
Add `--cancel-restart` to stop a queue during synthesis, rebuild it, and complete
a fresh queue in the same GUI window.
Blend / Flow now renders one sequence from multiple selected keyframes, with its
own inclusive range and output subfolder. Choose normal blending, forward-only
or reverse-only propagation between keyframes. Outer tails propagate from the
nearest selected keyframe. CPU blending is the default; optional GPU blending
requires CuPy. On the RTX 5090 validation host, the CUDA 12 CuPy wheel could not
execute kernels; the separate `requirements-cupy-cuda13.txt` set passed with a
CUDA 13.4-capable driver. This optional set is not installed by standard setup.
Solver controls expose LSQR, LSMR and an automatic or explicit
LSMR iteration limit. These choices are included in render presets; projects also
save the grouped range and selection. Independent jobs retain their own ranges.
Rendering controls include optional numerical error/selection-map exports (.npy)
and flow visualization exports (.png). Both are off by default and apply to
independent and grouped video jobs. Results go in each job's `auxiliary/` folder;
`manifest.json` records artifact types, sequence positions and flow frame pairs.
Artifact filenames use result indices, not source-frame numbers: upstream removes
some boundary entries, and blended selection masks are not raw synthesis errors.
NumPy maps retain their numerical values and dtype. Flow PNGs use upstream color
visualization with per-image magnitude normalization; they are not raw flow vectors.
A single-frame copy writes an empty manifest when exports are requested.
Requested exports must finish before the job receives `COMPLETE.txt`.
Enable **Assemble render.mp4 after saving frames** in Rendering to create an H.264
MP4 beside each video job's PNG frames. Set an explicit rate from 0.1 to 240 FPS
and optionally select a separate audio file; short audio is padded and long audio
is trimmed to the exact frame-count duration. Encoding is atomic and must succeed
before `COMPLETE.txt` is written. The PNG sequence remains authoritative and is
not deleted. This is output assembly only: direct video import and synchronized
source/output playback are intentionally not included.
### Image Synthesis

Select or drop a styled image, its source guide and a target guide, then click
**Synthesize Image**. Add optional source/target guide pairs with their own weights.
Source guides must match the style's dimensions, and target guides must match each
other; the target may have a different size from the style. Each guide pair must
have the same channel count. Inputs must be 8-bit images, with at most 24 guide
channels in total. The style is read as a three-channel color image; its alpha is
not used as a mask. Outputs use the target dimensions after processing-size limits.

Quality, processing size, synthesis parameters and iteration schedules are shared with video.
Image jobs use their own primary-guide and style weights (defaults 6 and 1).
Video masks, automatic edges, position/warped-style guides, and blending options
do not apply. Additional guides are supplied explicitly as image pairs.

Output naming/location and batch settings apply. For input-relative destinations,
the styled image's folder takes the place of the keyframe folder and the target
image's folder takes the place of the video folder. Each run creates a unique job
subfolder containing `job.json`, `image.png`, a lossless numerical `error.npy`,
`image_manifest.json` and, only after successful saving, `COMPLETE.txt`.

Image presets store input files, guide pairs, weights and output subfolder in the
existing shareable preset file, with their own startup restore choice. Projects
store these inputs as optional `image_synthesis` data. Image-only projects can be
saved without video folders; older projects load with empty image inputs.
Use the tab's Stop and Open outputs buttons to manage an image run. Worker reuse,
isolated mode, cancellation and asynchronous shutdown use the existing lifecycle.
Rendering remains CUDA-backed. The implementation has mock/CPU file-handling
tests; real CUDA image quality and performance have not yet been validated.

## Credits and attribution

### EbSynth — Secret Weapons

[EbSynth](https://ebsynth.com/) is developed by **Secret Weapons**.
Its synthesis technology is a foundation of this workflow.

Website: **https://ebsynth.com/**

### Ezsynth — Trentonom0r3 and contributors

[Trentonom0r3/Ezsynth](https://github.com/Trentonom0r3/Ezsynth) supplies the
original Python pipeline and native EbSynth interface used by this frontend.
Its reworked pipeline credits **FuouM**; related earlier work is available at
[FuouM/Ezsynth](https://github.com/FuouM/Ezsynth).

### ReEzSynth — FuouM

[FuouM/ReEzSynth](https://github.com/FuouM/ReEzSynth) supplies the included
PyTorch/CUDA synthesis engine. It is a separate project from the original
Ezsynth pipeline and this Windows GUI. The supported revision, local build
compatibility patch and adapter limits are documented in DUAL_ENGINE.md.

### ReEzSynth Windows GUI

ReEzSynth focuses on the Windows interface, job preparation, queue
management, and user experience around these existing tools. It does not
claim authorship of EbSynth or Ezsynth and is not an official release from
their developers.

Please retain the upstream license files and attribution notices when
redistributing this project.

The consolidated runtime attribution and exact provenance references are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). A public candidate must also
complete [CLEAN_MACHINE_TEST.md](CLEAN_MACHINE_TEST.md).
