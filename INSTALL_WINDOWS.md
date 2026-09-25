# Windows setup

The standard setup installs **both Trentonom0r3/Ezsynth and FuouM/ReEzSynth**.
FuouM is an included engine, with a separate Python worker environment to keep
the two engines' packages isolated. Its RAFT Sintel/Kitti and three NeuFlow
checkpoints are included in setup. [DUAL_ENGINE.md](DUAL_ENGINE.md) describes
engine selection and component maintenance.

ReEzSynth uses its own Conda environment. Do not install its packages into base
Conda, ComfyUI, or another application's environment. The setup below targets
64-bit Windows, Python 3.11 and an NVIDIA GPU supported by CUDA 12.8 PyTorch wheels.
GUI construction does not require a GPU; the current rendering paths use CUDA.
Allow several GB for the environment and download cache.

## First installation

### Installer-managed setup (recommended)

1. Install a current NVIDIA driver appropriate for your GPU. If a native DLL fails
   to load, check the [Microsoft x64 Visual C++ runtime](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist).
   Do not fetch missing DLLs from third-party DLL sites.
2. On **Select Additional Tasks**, leave the four prerequisite checkboxes selected:
   **Git for Windows**, **Miniforge/Conda**, **Visual Studio 2022 C++ Build Tools,
   MSVC x64 toolchain, and Windows SDK**, and **NVIDIA CUDA Toolkit 12.8**. Each is
   an install-if-missing choice: a compatible existing installation is kept.
3. On the finish page, leave **Set up and validate the ReEzSynth engine environment
   now** selected. This fifth checkbox is also selected by default. The same complete
   setup action is available later from the ReEzSynth Start-menu folder.
4. The bootstrap checks and processes selections in order: Git, Conda, Visual Studio
   C++ tools/SDK, CUDA 12.8, then the engines. Visual Studio and CUDA can require
   Windows administrator approval. ReEzSynth does not suppress those approval
   prompts or restart Windows automatically.
5. After prerequisites pass, setup records the exact Conda/environment pair, then
   creates and verifies the Legacy environment and the separate FuouM worker
   environment. If Windows, a prerequisite, download, or build interrupts setup,
   restart if requested and run the same Start-menu action again. Compatible
   prerequisites are preserved and only the recorded interrupted setup can resume.
6. Launch ReEzSynth from the Start menu or desktop shortcut after setup reports that
   both engines passed.

Clearing a prerequisite checkbox prevents the installer from installing that shared
component. It still detects and uses an already compatible installation. If the
component is absent or incompatible, setup explains the consequence: without Git,
FuouM source cannot be obtained; without Conda, the application environment cannot
be created; without MSVC and a Windows SDK, native extensions cannot be built; and
without CUDA 12.8, GPU engine/native-extension setup cannot pass. Engine setup stops
before creating or changing environments if any required selected-or-existing
component is unavailable. Clearing the finish-page engine checkbox installs only
the application and shortcuts; rendering remains unavailable until the Start-menu
setup action completes.

Compatibility detection requires a runnable `git --version`, a runnable
`conda --version`, Visual Studio 2022 (17.x) with an x64 `cl.exe` and a complete
Windows 10/11 SDK containing the UM and UCRT headers, and `nvcc --version` reporting
CUDA release 12.8. Detection does not replace, downgrade, or remove shared tools.
Immediately after a selected install, the same process searches again and refreshes
its executable paths. For CUDA it sets process `CUDA_HOME` and `CUDA_PATH`, prepends
the toolkit `bin` directory, and verifies the detected `nvcc` before engine setup.

Preview the full ordered bootstrap without making changes:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\install_reezsynth.ps1 -Plan
   ```

### Manual setup

Use this path when `winget` is unavailable or an administrator manages system
software separately.

1. Install Git for Windows.
2. Install a 64-bit Conda distribution such as
   [Miniforge](https://github.com/conda-forge/miniforge#download). Keep an existing
   Conda installation; never target its `base` environment.
3. Install Visual Studio 2022 C++ Build Tools with the C++ x64 workload, recommended
   components, and a Windows SDK.
4. Install the NVIDIA CUDA **12.8 toolkit**. The CUDA runtime supplied by PyTorch and
   the maximum CUDA version displayed by `nvidia-smi` are not substitutes for the
   toolkit compiler. If several toolkits exist, set `CUDA_HOME` to CUDA 12.8.
5. Download/clone and extract the complete ReEzSynth repository into a writable
   folder, retaining `ezsynth/`, `assets/`, licenses, setup helpers, and runtime assets.
6. Open PowerShell in that folder and create the environments and run checks:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_reezsynth.ps1
   ```

   ExecutionPolicy Bypass applies only to that PowerShell process. Setup uses
   conda-forge for Python/pip, the official PyTorch CUDA index for torch/torchvision,
   and PyPI for the remaining packages. It installs pinned direct requirements
   using the working dependency snapshot as constraints. The PyTorch pair follows
   the [official 2.11.0 installation instructions](https://pytorch.org/get-started/previous-versions/).
   Setup checks Git/CUDA/C++ build prerequisites after creating the initial
   Python environment and before downloading the large Python packages.
   It then installs and verifies the original engine, invokes the FuouM component
   installer, copies the verified local RAFT weights, downloads revision-pinned
   NeuFlow weights with SHA-256 verification, and builds/checks FuouM's extension.
   System compilers and the CUDA toolkit must already be installed.

7. Launch `run_reezsynth.bat` and choose either engine in Rendering. Only after
   both engines pass does setup record two ignored local text
   files containing the Conda executable path and environment name so double-click
   launches can find custom installations. Do not share those machine-specific files.

Setup refuses to modify an unrelated existing Conda environment or FuouM worker
environment. It never deletes environments, installs into base, or runs a render.
The installer bootstrap writes `.reezsynth-setup-resume.json` immediately before
engine setup and removes it only after both engines pass. A later run resumes only
when that marker matches the exact resolved Conda executable, environment name, and
app-local FuouM worker-environment path.
If either engine fails, launcher configuration is not updated and partial work is
retained. Manual `setup_reezsynth.ps1 -Resume` and `setup_fuoum.py --resume` are
only for the same interrupted installation; do not use them to adopt or repair an
unrelated environment. Use check-only or a fresh application folder for independent
installations.

The safest rerun/resume command is the Start-menu prerequisite/dependency action or:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_reezsynth.ps1
```

It re-detects prerequisites and validates `.reezsynth-setup-resume.json` before
passing `-Resume`. Direct `setup_reezsynth.ps1 -Resume` applies the same exact
resolved-Conda-path and environment-name check. A missing, unreadable, or mismatched
marker stops without invoking Conda. Do not edit the marker to adopt an environment.

## Custom Conda installations and existing environments

For a nonstandard installation location:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_reezsynth.ps1 -CondaExe 'E:\miniconda3\Scripts\conda.exe'
```

To run the full prerequisite bootstrap with a custom environment name, use
`install_reezsynth.ps1 -EnvironmentName reezsynth-new`. To run only the engine
setup with already installed prerequisites, use `setup_reezsynth.ps1` and the same
option. Use
`-NoLauncherConfig` if this is a temporary test environment and the launcher's local
configuration should remain untouched. `REEZSYNTH_ENV` overrides the launcher's
saved/default environment name. Without saved configuration the launcher also checks
`CONDA_EXE`, PATH and common Conda installation folders.
Both engine environments should be installed together in a fresh repository
folder when creating a second independent installation.

Uninstalling ReEzSynth removes the app-local FuouM worker environment/source,
downloaded engine sources, local cache, compiled Python caches, launcher files, and
any interrupted-setup marker along with the installed application. It does not
remove Git, Conda/Miniforge, Visual Studio Build Tools, CUDA, the selected external
named Conda environment, external projects/renders, or user test media. Those are
shared or user-owned; remove them separately only after confirming that nothing
else needs them.
After removing registered and generated application files, uninstall removes the
ReEzSynth installation directory only when it is empty. An unknown file is preserved
and therefore keeps the directory for inspection rather than being deleted broadly.

## Troubleshooting setup

Verify the exact prerequisite commands seen by setup:

```powershell
git --version
conda --version
where.exe cl
where.exe nvcc
nvcc --version
Get-ChildItem Env:CUDA_HOME,Env:CUDA_PATH
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_reezsynth.ps1 -CheckOnly
```

`nvcc --version` must report release 12.8; the CUDA value printed by `nvidia-smi`
describes driver capability and is not this test. Run the bootstrap from the same
PowerShell window to refresh CUDA variables immediately. If a third-party installer
requests a restart, restart Windows and rerun the bootstrap; its guarded marker and
compatible-installation detection make that the supported recovery path.

Setup output remains in its PowerShell window. To retain it, run the command through
`Start-Transcript`/`Stop-Transcript`, or redirect both streams to a chosen log file.
The Inno installer can produce its own install log when launched with
`/LOG="C:\path\ReEzSynth-install.log"`. Render jobs write `worker.log`, `job.json`,
and engine manifests in their selected output folder. The GUI's **Save Log...**
button saves the current session log; inspect paths before sharing logs because they
can contain local folder names.

For an existing `reezsynth` environment, diagnose without installing anything:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_reezsynth.ps1 -CheckOnly
```

Check-only verifies both engines, including FuouM's selected source revision,
native imports, dependency consistency and RAFT/NeuFlow checkpoint checksums.
It does not require compiler tools when checking existing binaries.
The diagnostic reports the actual interpreter, package versions/imports, dependency
conflicts, asset hashes, CUDA availability and EbSynth DLL loading. Its GUI smoke
test uses offscreen Qt and temporary settings/directories. It does not load model
weights or perform synthesis. Offscreen font/size-hint warnings are reported and
are not, by themselves, a failed GUI construction test.

For older installations that have only the original engine, activate their
working Python 3.11 environment and add the included FuouM component:

```powershell
conda activate reezsynth
python -B setup_fuoum.py --preflight
python -B setup_fuoum.py --neuflow
```

These component-install commands require an absent FuouM worker environment.
Use `python -B setup_fuoum.py --check-only --neuflow` for an existing working one,
or `--resume` only for the same interrupted component setup.

The original-engine check can also run through the launcher:

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
`imageio-ffmpeg 0.6.0` is a direct frontend dependency used only when rendered-
video export is enabled. The worker invokes its bundled FFmpeg executable after
PNG saving and before the completion marker; no system FFmpeg installation is
required for the normal setup.
Do not replace the working DLL or remove the local CUDA-backend forwarding fixes.

If RAFT weights are absent, obtain them from the
[upstream RAFT project](https://github.com/princeton-vl/RAFT#demos), and verify the
intended file before use. Setup will report missing assets rather than silently
download them. The video controls offer the bundled Sintel default and Kitti RAFT
weights. Image synthesis needs the native library but does not load RAFT models.

CuPy GPU blending is optional and off by default. It is not part of this baseline
install. The tested RTX 5090 configuration requires a CUDA 13.4-capable driver and
the isolated pins in `requirements-cupy-cuda13.txt`:

```powershell
python -m pip install -r requirements-cupy-cuda13.txt -c reezsynth-working-requirements.txt
python -B diagnose_reezsynth_engines.py --engine legacy --gpu-blending --cupy-poisson
```

The second command exercises the readiness kernel, GPU histogram blending and
CuPy Poisson reconstruction through a real grouped frontend job. Do not install a
CUDA 13 wheel on a system whose NVIDIA driver cannot support it; use the official
CuPy compatibility guidance for other hosts. The CUDA 12 CuPy 14.2.0 wheel failed
with `CUDA_ERROR_NO_BINARY_FOR_GPU` on this RTX 5090, while the pinned CUDA 13 set
passed. The EbSynth backend control offers CUDA, Auto and CPU; video optical flow
can still use PyTorch CUDA, so CPU EbSynth is not a complete CPU-only video mode.
If PyTorch CUDA is unavailable, CPU/Auto permits CPU optical flow with Classic
edges and GPU blending/correlation disabled. To check both native backends and CPU
optical flow through real frontend jobs, run:

```powershell
python -B diagnose_ebsynth_backend.py both
```

This starts separate CUDA-hidden workers and validates image/video outputs,
completion and backend provenance. It passed locally on generated diagnostic inputs.
A CPU-only installation remains a separate portability test.
The Rendering tab includes the upstream EF-RAFT and FlowDiffuser architecture
choices, but they are not part of the default installation. Before selecting one,
run `check_reezsynth.py --flow-extras`; the queue repeats the same preflight before
it creates any outputs. EF-RAFT needs its three model files
(`25000_ours-sintel.pth`, `ours_sintel.pth`, and `ours-things.pth`) in
`ezsynth/utils/flow_utils/ef_raft_models/`. FlowDiffuser needs the tested
dependency set in `requirements-flowdiffuser.txt` and
`FlowDiffuser-things.pth` in `ezsynth/utils/flow_utils/flow_diffusion_models/`.
Upstream `timm 0.6.12` does not import on this Python 3.11 environment. The tested
path uses `timm 1.0.29`, `huggingface_hub 1.31.0` and `safetensors 0.8.0`.
`setup_flowdiffuser.py` downloads two pinned Twin-SVT files (about 494 MB total),
verifies their hashes and makes rendering load them locally. It never fetches
model data during a render. The separate official FlowDiffuser checkpoint must
still be supplied through the Settings installer.
The Settings tab's **Optional flow components** panel can import checkpoint files
you have downloaded from the upstream source and can install `timm` after explicit
confirmation. It does not silently fetch the main model checkpoint.

## Memory-efficient RAFT extension

The **Memory-efficient RAFT correlation (CUDA)** extension is included in the
repository under `wheels/` and installed automatically by `setup_reezsynth.ps1`.
This wheel itself needs no compiler or separate build command. The included
FuouM engine still requires the build prerequisites above for its first build.
The bundled wheel is restricted to Windows x64, CPython 3.11, PyTorch
2.11.0+cu128 and NVIDIA architectures 7.5, 8.0, 8.6, 8.9 or 12.0. The setup
script installs it with a SHA-256 hash check, then verifies that it loads.

Enable the Rendering checkbox after setup. Before use, a tiny kernel checks the
actual loaded extension on the active GPU, once per worker/device. Compatible
custom or PTX builds are accepted without a fixed architecture allow-list;
unusable builds produce an explanatory rebuild error and normal RAFT remains
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
into the current Python environment and verifies a real correlation kernel.
Omit `--install` to build without installing.
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
