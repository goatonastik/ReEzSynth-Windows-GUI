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
LSQR/LSMR grouped reconstruction, automatic pyramid depth, and its temporal NNF
propagation and sparse feature guides. The latter two are enabled by default for
FuouM and appear only when that engine is selected.

Video masks, custom edge sequences, video auxiliary exports, grouped forward-only
or reverse-only modes, CuPy blending, EF-RAFT/FlowDiffuser and the legacy compiled
RAFT correlation option are not yet mapped to FuouM. Incompatible requests fail
before queue outputs are created. Existing saved values are preserved, so selected
incompatible controls stay editable until cleared. Image jobs ignore video-only
settings. CUDA is the supported FuouM synthesis backend in this integration.

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
benchmark. Broader visual quality, long-sequence stability, other GPUs and the
unsupported FuouM capabilities remain on WORK_REMAINING.md.
