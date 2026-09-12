# Windows setup

This guide installs the original Trentonom0r3/Ezsynth engine. To add the optional
FuouM/ReEzSynth runtime and native extension, follow [DUAL_ENGINE.md](DUAL_ENGINE.md)
after completing this setup.

ReEzSynth uses its own Conda environment. Do not install its packages into base
Conda, ComfyUI, or another application's environment. The setup below targets
64-bit Windows, Python 3.11 and an NVIDIA GPU supported by CUDA 12.8 PyTorch wheels.
GUI construction does not require a GPU; the current rendering paths use CUDA.
Allow several GB for the environment and download cache.

## First installation

1. Install a 64-bit Conda distribution, such as
   [Miniforge](https://github.com/conda-forge/miniforge#download). Keep your existing
   Conda installation if you already have one.
2. Install a current NVIDIA driver appropriate for your GPU. If a native DLL fails
   to load, check the [Microsoft x64 Visual C++ runtime](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist).
   Do not fetch missing DLLs from third-party DLL sites.
3. Download/clone the complete ReEzSynth repository into a writable folder and
   extract it before running scripts. Keep `ezsynth/`, `assets/`, and the licenses.
4. Open PowerShell in that folder. Preview the commands if desired:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_reezsynth.ps1 -Plan
   ```

5. Create the environment and run installation checks:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_reezsynth.ps1
   ```

   ExecutionPolicy Bypass applies only to that PowerShell process. Setup uses
   conda-forge for Python/pip, the official PyTorch CUDA index for torch/torchvision,
   and PyPI for the remaining packages. It installs pinned direct requirements
   using the working dependency snapshot as constraints. The PyTorch pair follows
   the [official 2.11.0 installation instructions](https://pytorch.org/get-started/previous-versions/).
   A separate system CUDA toolkit is not installed by this script.

6. Launch `run_reezsynth.bat`. Successful setup records two ignored local text
   files containing the Conda executable path and environment name so double-click
   launches can find custom installations. Do not share those machine-specific files.

Setup refuses to modify an environment with the chosen name if it already exists.
It never deletes environments, installs into base, downloads model weights, or runs
a render. If a step fails, its exit code stops setup; the partial environment remains
for inspection. Use another environment name for a retry rather than deleting a
working environment.

## Custom Conda installations and existing environments

For a nonstandard installation location:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_reezsynth.ps1 -CondaExe 'E:\miniconda3\Scripts\conda.exe'
```

To create a separate environment, add `-EnvironmentName reezsynth-new`. Use
`-NoLauncherConfig` if this is a temporary test environment and the launcher's local
configuration should remain untouched. `REEZSYNTH_ENV` overrides the launcher's
saved/default environment name. Without saved configuration the launcher also checks
`CONDA_EXE`, PATH and common Conda installation folders.

For an existing `reezsynth` environment, diagnose without installing anything:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_reezsynth.ps1 -CheckOnly
```

The diagnostic reports the actual interpreter, package versions/imports, dependency
conflicts, asset hashes, CUDA availability and EbSynth DLL loading. Its GUI smoke
test uses offscreen Qt and temporary settings/directories. It does not load model
weights or perform synthesis. Offscreen font/size-hint warnings are reported and
are not, by themselves, a failed GUI construction test.

Once the environment is available, the same check can run through the launcher:

```powershell
.\run_reezsynth.bat check_reezsynth.py --gui-smoke --cuda --native
```

To see what the optional EF-RAFT and FlowDiffuser architectures still need,
without importing models or using the GPU, run:

```powershell
.\run_reezsynth.bat check_reezsynth.py --flow-extras
```

## Runtime files and optional features

The current checkout includes `ezsynth/utils/ebsynth.dll` and RAFT Sintel/Kitti
weights. `runtime-assets.json` records their working-checkout hashes to detect
incomplete or changed copies. Hashes do not prove upstream provenance. Keep
licensing/attribution when distributing runtime files.
Do not replace the working DLL or remove the local CUDA-backend forwarding fixes.

If RAFT weights are absent, obtain them from the
[upstream RAFT project](https://github.com/princeton-vl/RAFT#demos), and verify the
intended file before use. Setup will report missing assets rather than silently
download them. The video controls offer the bundled Sintel default and Kitti RAFT
weights. Image synthesis needs the native library but does not load RAFT models.

CuPy GPU blending is optional and off by default. It is not part of this baseline
install. The EbSynth backend control offers CUDA, Auto and CPU; video optical flow
can still use PyTorch CUDA, so CPU EbSynth is not a complete CPU-only video mode.
If PyTorch CUDA is unavailable, CPU/Auto permits CPU optical flow with Classic
edges and GPU blending/correlation disabled. Native CPU/Auto rendering still needs
validation on actual installations.
The Rendering tab includes the upstream EF-RAFT and FlowDiffuser architecture
choices, but they are not part of the default installation. Before selecting one,
run `check_reezsynth.py --flow-extras`; the queue repeats the same preflight before
it creates any outputs. EF-RAFT needs its three model files
(`25000_ours-sintel.pth`, `ours_sintel.pth`, and `ours-things.pth`) in
`ezsynth/utils/flow_utils/ef_raft_models/`. FlowDiffuser needs `timm` and
`FlowDiffuser-things.pth` in `ezsynth/utils/flow_utils/flow_diffusion_models/`.
Its upstream code also initializes pretrained Twin-SVT backbones, which may fetch
additional weights on first use. The setup script does not download or install
these optional assets. Verify their source and compatibility with the pinned
environment before adding them; installing `timm` alone does not enable FlowDiffuser.
The Settings tab's **Optional flow components** panel can import checkpoint files
you have downloaded from the upstream source and can install `timm` after explicit
confirmation. It does not silently fetch model checkpoints.

## Memory-efficient RAFT extension

The **Memory-efficient RAFT correlation (CUDA)** extension is included in the
repository under `wheels/` and installed automatically by `setup_reezsynth.ps1`.
No CUDA Toolkit, Visual Studio, or separate command is required for normal use.
The bundled wheel is restricted to Windows x64, CPython 3.11, PyTorch
2.11.0+cu128 and NVIDIA architectures 7.5, 8.0, 8.6, 8.9 or 12.0. The setup
script installs it with a SHA-256 hash check, then verifies that it loads.

Enable the Rendering checkbox after setup. If the GPU architecture is not in the
wheel, the checkbox produces an explanatory error and normal RAFT remains
available. The extension preserves input/output resolution but other render
stages can still need more GPU memory.

### Manual rebuild for an unsupported setup

Only use this when the bundled wheel is incompatible, such as after changing
PyTorch, Python, CUDA, or to target an unlisted GPU. Install a CUDA toolkit
matching PyTorch (12.8 for the pinned environment) and Visual Studio 2022 with
the C++ x64 tools and Windows SDK. The CUDA compiler/toolkit is separate from
the runtime included in the PyTorch wheel.

```powershell
conda activate reezsynth
python build_reezsynth_corr.py --install
python check_reezsynth_corr.py
```

The helper selects the installed VS 2022 tools, checks the CUDA toolkit version,
builds a wheel for the detected GPU architecture, then installs only that wheel
into the current Python environment. Omit `--install` to build without installing.
Use `--arch 12.0` explicitly for RTX 5090. No admin rights or new Python packages
are needed when the compilers are already installed. Rebuild after changing
PyTorch, Python, CUDA or GPU architecture. The generated local build is not a
universal wheel; the bundled release wheel has the compatibility limits above.

Source and BSD license are included in `third_party/raft_alt_cuda_corr`, pinned to
[upstream RAFT commit 2888e15](https://github.com/princeton-vl/RAFT/tree/2888e15a51fa41140771d3f498ed8023cff098d1/alt_cuda_corr)
with documented compatibility changes. This is not an official upstream binary.
Validated locally: Windows x64, Python 3.11, PyTorch 2.11.0+cu128, CUDA 12.8.93,
MSVC 14.43 and RTX 5090 (sm_120).

The check runs small synthetic GPU calculations and a random-weight RAFT forward
comparison. It does not load pretrained models or render footage. For optional
timing and memory measurements, add `--benchmark --four-k`; these measure only
correlation at 960-width and 4K-equivalent feature sizes. The 4K all-pairs table is
never allocated by the benchmark. Run the GUI after verification and keep the
memory-efficient checkbox enabled to select the extension.

## Before sharing a release

Use the explicit test command in README; upstream test_imgsynth.py/test_redux.py
are rendering demos, not lightweight tests. Then run one short video and one image
synthesis with disposable inputs, checking completion, output dimensions, stop/restart
and GPU memory after shutdown. Dependency/GUI/DLL checks alone do not prove render
quality or compatibility with every GPU.

Do not include personal projects, footage, renders, virtual environments, local
launcher configuration, credentials, or backup dumps. Ignore rules do not remove
files already tracked by Git; audit the tracked files separately before publishing.

## Requests warning from base Conda

An earlier local warning was caused by base Requests 2.31.0 importing chardet 7.6.0,
outside its supported range. It was fixed on the development machine by pinning
base chardet to 5.2.0, after approval. ReEzSynth's environment did not contain
Requests and was not the source of that warning. Do not automatically apply that
base-environment change on other machines: inspect their actual versions first.
