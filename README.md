# ReEzSynth Windows GUI

A Windows graphical front end for preparing and running keyframe-based
video stylization with Ezsynth and EbSynth.

ReEzSynth aims to make the workflow easier to manage: select your source
image sequence and styled keyframes, configure frame ranges, queue renders,
and monitor progress without manually preparing each rendering job.

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

## Using the interface

For a new machine, follow [Windows setup](INSTALL_WINDOWS.md). The setup script
creates a dedicated environment, installs pinned dependencies, and checks GUI,
CUDA and native-library availability without rendering.

Launch `run_reezsynth.bat` with the existing `reezsynth` Conda environment.
The entry point is `reezsynth_gui.py`.

- **Video / Keyframes:** select or drop project, source, styled-keyframe and
  optional mask directories. Sources must be consecutive numbered PNG/JPEG
  images; keyframe numbers must match sources. Set inclusive propagation ranges.
- **Rendering:** edit guide weights, uniformity, patch size, pyramid levels,
  iteration counts, polishing, edge method and masks. Preview/Standard reset
  synthesis parameters while preserving guide weights. RAFT Sintel and the CUDA
  synthesis backend remain selected.
- **Masks:** tick the Masks checkbox beside its directory input. Untick it to ignore
  the remembered mask folder for rendering and compositing. Supply one mask per source frame,
  matching its number and dimensions. White selects stylized pixels; black keeps
  source pixels. Feather size is zero or an odd integer.
- **Settings:** the toolbar button opens the Settings tab, including optional
  discovery, automatic start, parallel rendering, notifications and startup choices.

### Presets and startup behavior

Key, video and mask-guide weights occupy a column between their directory inputs
and Select buttons. The remaining Guide weights are underneath the directories. Key weight
controls the style-to-guide ratio: because the native library fixes style weight
at 1, the adapter divides all guide weights by the key weight (minimum 0.001).
Video weight controls the source-image guide. Mask guide weight adds a source/target
mask correspondence guide when masks are enabled; zero disables that additional
guide without disabling mask compositing. Defaults (key 1, mask guide 0) preserve
previous rendering behavior. All are saved in weight presets and projects.

The default quality preset is Standard. Video weight 6, Mapping 2 and Deflicker
0.5 match Ezsynth's RunConfig defaults.
Processing size defaults to Original resolution; explicitly saved size choices
remain respected. With Original resolution selected, video jobs check selected
source-frame and keyframe dimensions before creating outputs or launching workers.
Mismatches show the filename, actual size and expected size. Image Synthesis keeps
its separate rule allowing target dimensions to differ from source/style dimensions.
Existing saved weights are preserved. The visible guide order is Mapping,
Deflicker, Diversity.

Rendering labels relate familiar Beta concepts to Ezsynth controls: Mapping
(position guide), Deflicker (warped-style guide), and Diversity (uniformity).
These are related controls, not a promise of identical EbSynth Beta behavior or
matching numerical scales. The native weighting model is described in the
[EbSynth source documentation](https://github.com/jamriska/ebsynth#examples).

Directory, guide-weight, rendering and application presets are independent.
Select from a dropdown; **+** saves the current group and **-** removes it after
confirmation. Saving pre-fills the selected name and confirms overwriting an
existing name. Rendering presets include quality, resolution and output naming;
per-job frame ranges belong in saved projects.

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
an initial limit of 2; 0 permits all queued jobs at once. It uses more GPU memory
and has only been validated with mock workers. Stop/Close waits for every worker
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
python -B -m unittest test_reezsynth_gui test_reezsynth_lifecycle test_reezsynth_worker test_reezsynth_options test_reezsynth_render_adapter test_reezsynth_grouped test_reezsynth_artifacts test_reezsynth_destinations test_reezsynth_image test_reezsynth_setup test_reezsynth_raft -v
```

Tests isolate settings/files, use offscreen Qt, mock workers and a fake engine,
and include CPU image handling and CPU RAFT numerical checks without pretrained
weights. Audio playback is mocked. The older
`test_imgsynth.py` and `test_redux.py` are rendering demos; do not use unrestricted
test discovery for this lightweight suite.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for results and remaining manual checks.
Real GPU memory use, rendering quality and native audio playback remain unverified.
Blend / Flow now renders one sequence from multiple selected keyframes, with its
own inclusive range and output subfolder. Choose normal blending, forward-only
or reverse-only propagation between keyframes. Outer tails propagate from the
nearest selected keyframe. CPU blending is the default; optional GPU blending
requires CuPy. Solver controls expose LSQR, LSMR and an automatic or explicit
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
### Image Synthesis

Select or drop a styled image, its source guide and a target guide, then click
**Synthesize Image**. Add optional source/target guide pairs with their own weights.
Source guides must match the style's dimensions, and target guides must match each
other; the target may have a different size from the style. Each guide pair must
have the same channel count. Inputs must be 8-bit images, with at most 24 guide
channels in total. The style is read as a three-channel color image; its alpha is
not used as a mask. Outputs use the target dimensions after processing-size limits.

Quality, processing size and the six synthesis parameters are shared with video.
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

### Ezsynth — FuouM

[Ezsynth](https://github.com/FuouM/Ezsynth) is developed by **FuouM and
contributors**. It provides the Python rendering pipeline that this
front end builds upon.

GitHub: **https://github.com/FuouM/Ezsynth**

### ReEzSynth Windows GUI

ReEzSynth focuses on the Windows interface, job preparation, queue
management, and user experience around these existing tools. It does not
claim authorship of EbSynth or Ezsynth and is not an official release from
their developers.

Please retain the upstream license files and attribution notices when
redistributing this project.
