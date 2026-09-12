# Selecting the synthesis engine

Choose **Synthesis engine** in Rendering before starting a queue. The choices are
Trentonom0r3/Ezsynth (the existing default) and FuouM/ReEzSynth. The selection is
saved in projects, rendering presets and last-used settings. Old files keep the
original engine. Each prepared job freezes its engine, revision and runtime;
changing the selection requires completing or stopping the current queue.

Both engines support image synthesis, independent keyframe video and normal
grouped blending. Shared workers, isolated workers, parallel queues, live previews,
cancellation and restart use the same frontend lifecycle. The CLI benchmark uses
the Python executable recorded in the job.

FuouM's current adapter supports RAFT Sintel/Kitti, Classic/PST/PAGE edges,
automatic pyramid depth, temporal NNF propagation and sparse feature guides. Its
engine-specific controls expose weighted/plain voting, SSD/NCC patch cost,
early-stop and search-pruning thresholds, sparse-guide weight, plus LSQR, LSMR,
CG, AMG, seamless or disabled grouped reconstruction and its luminance/chroma
gradient weights. The temporal and sparse options are enabled by default and all
FuouM-only controls are enabled only when that engine is selected. AMG additionally
requires `pyamg` in the FuouM environment.

Both engines now support masks, optional premasking/feathered compositing, mask
guides, custom edge sequences, auxiliary exports, and grouped forward-only or
reverse-only rendering. FuouM additionally supports NeuFlow v2 with Sintel, Mixed
and Things checkpoints. Its RAFT checkpoint is stored separately from the legacy
flow model, so switching engines or flow algorithms preserves both selections.

CuPy blending, EF-RAFT/FlowDiffuser and compiled memory-efficient RAFT remain
Trentonom0r3-only. Inapplicable controls are greyed out and labelled by engine.
Saved values are retained but excluded from effective FuouM jobs. Direct CLI jobs
that explicitly request incompatible capabilities are rejected. Image jobs ignore
video-only settings. CUDA is the supported FuouM synthesis backend.

## Source and runtime isolation

The adapter is pinned to FuouM/ReEzSynth commit
`aaa8d06170e6cc59054410aa9c422edd789f7ab2`. It uses the structured configuration and
pipeline classes because this revision's convenience API does not forward every
setting, including Poisson solver selection. Automatic pyramid depth is translated
to a positive maximum because that engine does not implement the legacy `-1` value.
Grayscale image guides receive an explicit channel dimension before native calls.

Both upstream projects name their Python package `ezsynth`. FuouM runs in a separate
worker process with its own package search path and Python executable. A worker
refuses to switch imported engines. Input arrays are validated/resized by the
adapter and supplied to the pinned data manager; the frontend saves outputs and
preserves original frame numbers. Each job gets its own temporary upstream cache.

Each output includes `engine_manifest.json` with the upstream revision, source and
native-binary hashes, selected checkpoint hash, adapter hashes and runtime package
versions. These identify the actual local files, including compatibility changes;
they are not a claim of bit-identical rendering across hardware or engine versions.
Preset/project revisions are checked when loading. Existing presets without a
revision use the selected engine's current supported baseline.

## Setup on another Windows machine

First complete the normal GUI setup and activate its Python 3.11 environment.
The guarded installer is the recommended entry point:

```powershell
python -B setup_fuoum.py --plan --neuflow
python -B setup_fuoum.py --neuflow
python -B setup_fuoum.py --check-only --neuflow
```

`--neuflow` explicitly enables download/checking of three official, revision-pinned,
SHA-256-verified checkpoints. Without it only existing local RAFT checkpoints are
copied. Existing environments and changed checkpoints are never overwritten.
Existing native binaries are reused and import-checked; rebuild explicitly with
`build_fuoum_engine.py` only after stopping render workers. Custom paths are
available through `--source` and `--venv`. Failed installations are retained for
inspection; `--check-only` does not repair them. A fresh source/environment install
passed on the development host; another-machine validation is still required.

Manual equivalent (without the optional NeuFlow download):

The following commands create a worker virtual environment which reuses that
environment's PyTorch and other installed packages. FuouM's NumPy/OpenCV overrides
are installed only into the new virtual environment. It remains dependent on the
parent GUI environment; this is not a standalone portable distribution.

```powershell
git clone --filter=blob:none --sparse https://github.com/FuouM/ReEzSynth.git engine_sources/fuoum_reezsynth
git -C engine_sources/fuoum_reezsynth sparse-checkout set ezsynth ebsynth_extension models
git -C engine_sources/fuoum_reezsynth checkout --detach aaa8d06170e6cc59054410aa9c422edd789f7ab2
python -m venv --system-site-packages .engine_envs/fuoum
.\.engine_envs\fuoum\Scripts\python.exe -m pip install -r requirements-fuoum.txt
```

Copy the existing RAFT Sintel/Kitti checkpoints from
`ezsynth/utils/flow_utils/models/` into the upstream checkout's `models/raft/`
folder. Preserve their names and original copies. The setup does not download new
model weights. Keep the upstream license and attribution files with the checkout.

Building requires the CUDA toolkit matching PyTorch and Visual Studio 2022 C++
tools. On the development machine this is PyTorch 2.11.0+cu128, CUDA 12.8 and an
RTX 5090. The helper builds for the detected GPU architecture:

```powershell
.\.engine_envs\fuoum\Scripts\python.exe -B build_fuoum_engine.py
.\.engine_envs\fuoum\Scripts\python.exe -m pip check
python -B diagnose_reezsynth_engines.py --engine fuoum
```

`build_fuoum_engine.py` applies the checked-in
`patches/fuoum-windows-torch-types.patch` before compiling. The three header
substitutions keep Python binding headers out of CUDA compilation, resolving the
observed NVCC/MSVC `std` ambiguity with PyTorch 2.11. Synthesis algorithms are not
changed by that patch. The extension is built into the upstream checkout and
verified by importing it; unsupported source revisions are rejected.

Settings has optional source-folder and Python-executable fields. Blank fields use
`engine_sources/fuoum_reezsynth` and `.engine_envs/fuoum/Scripts/python.exe` within
this project. Those local installations and diagnostic outputs are ignored by Git.
The normal setup script still installs only the original engine.

## Validation

The adapter aligns forward/reverse errors by target frame before blending and
preserves every supplied styled keyframe exactly before optional masking. Its
Poisson gradient matrix has explicit zero right/bottom boundaries, and histogram
normalization handles flat-color styles. These are frontend corrections to the
pinned FuouM pipeline, not claims of identical upstream output. Reverse warping
still follows the pinned engine's negative-forward-flow approximation.

FuouM auxiliary maps are raw per-pass synthesis errors, before keyframe preservation,
blending and compositing. Each record names its error frame and pass direction.
Legacy grouped exports retain their existing offset-error selection-mask semantics.
Flow exports in both engines are color visualizations, not numerical vector fields.
Do not compare differently scoped error maps as a common quality score.

`diagnose_reezsynth_release.py` exercises repeated real sequence jobs with
`--engine legacy|fuoum`, `--frames`, `--repeats`, `--extended`,
`--style poster|painting|flat`, `--images`, and `--size WIDTH HEIGHT`.
It checks exact FuouM keyframes, unmasked backgrounds, finite auxiliary arrays,
retargeted image dimensions, orderly shared-worker exit, and records process-tree
RSS and sampled aggregate GPU memory. Adjacent-frame differences include motion;
they are not flicker scores or proof of general visual parity.

`diagnose_reezsynth_gui.py --fuoum --parallel --frames 60 --cycles 3` repeats real
GUI lifecycle checks. Substitute `--cancel-restart` or `--close` for those paths.


`diagnose_reezsynth_engines.py` runs real image, video and grouped jobs through one
persistent worker, checks output dimensions/content, lossless image error maps,
original numbering, previews, attribution and orderly exit. It records logs and
aggregate GPU-memory observations under `diagnostic_outputs/`. These observations
include other GPU users; sampled peaks are not exact per-process allocation peaks.

GUI checks accept `--fuoum`: `diagnose_reezsynth_gui.py --fuoum --parallel` and
`diagnose_reezsynth_gui.py --fuoum --cancel-restart`. They use temporary preferences
and copied sample inputs. See PROJECT_STATUS.md for completed local checks.

For the original engine, the real 4K check is:

```powershell
python -B diagnose_reezsynth_engines.py --engine legacy --memory-efficient --four-k
```

This is a short, three-frame test with Preview settings, not a long-production
benchmark. Repeated local checks are recorded in PROJECT_STATUS.md. Broader visual
acceptance, other GPUs, optional legacy components and release gates remain on
WORK_REMAINING.md; current deliberate capability limits are described above.
