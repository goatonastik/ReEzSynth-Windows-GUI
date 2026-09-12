# Distribution audit and release gates

Reviewed 2026-09-12. This records engineering evidence and unresolved provenance;
it is not blanket legal clearance to redistribute all files in this checkout.

## Packaging decision

Standard Windows setup installs both engines. FuouM is included through a
separately pinned source checkout and worker venv using `setup_fuoum.py`, with
RAFT and checksum-verified NeuFlow checkpoints. Check-only verifies both engines;
setup does not report success or save launcher configuration if either fails.
Do not combine both `ezsynth` packages in one Python process.
The worker venv inherits the base CUDA/PyTorch environment: it is not portable.
Build native extensions for the target Python/PyTorch/CUDA/GPU combination.
Do not bundle the development venvs or an architecture-specific build as a
universal binary. Stop workers before rebuilding their loaded DLL/PYD files.

A new sparse upstream checkout and a new worker environment were installed from
scratch in `diagnostic_outputs/install_verify_20260912/`; dependency checks,
official NeuFlow checksum downloads, native compilation and imports passed.
This reused the host's GUI environment, compiler and CUDA toolkit. It is not a
clean-machine or CPU-only test.

## Repository/archive inventory

| Category | Decision |
| --- | --- |
| Frontend/adapter source, maintained regressions, documented diagnostics | Keep; diagnostics help users validate their own GPU/install. |
| Requirements, build/setup scripts, compatibility patch, licenses/notices | Keep with source distribution. |
| `engine_sources/`, `.engine_envs/`, `diagnostic_outputs/`, generated renders, secrets, caches, logs | Already ignored; never stage or distribute them. |
| `ReEzSynth-source-bundle.txt`, `examples/gui_keyframes_v03.backup-20260908-184704697`, root `reezsynth_gui_v02.py`, `reezsynth_gui_v03.txt`, `reezsynth_gui_v031.txt`, `reezsynth_gui_v04.py` | Developer snapshots untracked and ignored after dependency review. Useful local copies and Git history are preserved; new commits/clones no longer include them. |
| Three tracked RAFT checkpoints (`sintel`, `kitti`, `small`) | Existing tracked exceptions despite `*.pth` ignore. Required GUI hashes cover Sintel/Kitti; `small` is not a GUI choice. Do not assume the ignore rule removes them from a commit/archive. Preserve the working installation; resolve distribution provenance before publishing. |
| `ezsynth/utils/ebsynth.dll` and compiled RAFT wheel | Existing runtime assets. Hashes detect changes; they do not prove source correspondence or redistribution clearance. |
| Sample photographs, paintings, masks and image-guide assets | Existing tracked examples, not generated test output. Audit their individual sources/permissions before including a public release. |

No existing assets were deleted or removed from Git history in this audit. No
release was uploaded. A GitHub source archive is not yet a cleared binary package.

## Notices and provenance

- The base repository's [LICENSE](LICENSE) is **GNU AGPL v3**, not ordinary GPL
  or MIT. See the [original repository license](https://github.com/Trentonom0r3/Ezsynth/blob/main/LICENSE).
- FuouM's pinned source declares MIT; retain [its license](licenses/FuouM-MIT.txt)
  and [upstream attribution](https://github.com/FuouM/ReEzSynth/blob/aaa8d06170e6cc59054410aa9c422edd789f7ab2/LICENSE).
- RAFT declares BSD-3-Clause. The retained
  [license](third_party/raft_alt_cuda_corr/LICENSE) accompanies the compiled
  correlation source; see [upstream](https://github.com/princeton-vl/RAFT/blob/master/LICENSE).
- NeuFlow v2 declares Apache-2.0. Retain [its license](licenses/NeuFlow-Apache-2.0.txt)
  and [official repository attribution](https://github.com/neufieldrobotics/NeuFlow_v2).
  Downloaded checkpoints are pinned to `204b5e3744461d90303b9ff82caa7a1bb56a2ca2`
  with exact hashes in `setup_fuoum.py`. A repository's code license alone does
  not establish every training dataset's or third-party asset's rights.
- [EbSynth's source README](https://github.com/jamriska/ebsynth#license) declares
  its code public domain and also gives a patent warning. That does not establish
  the provenance of this checkout's existing DLL or of the commercial application.
- Preserve notices for copied EF-RAFT/FlowDiffuser code and dependencies. Their
  optional checkpoint licensing and the complete dependency redistribution notice
  set still need review before a packaged binary release.
- Local validation used EF-RAFT revision `9ad323b` and the official FlowDiffuser
  Google Drive checkpoint. Pinned Twin-SVT artifacts came from
  `timm/twins_svt_large.in1k` revision `9985cdd` and
  `timm/twins_svt_small.in1k` revision `42c9bf4`. Hash enforcement in
  `setup_flowdiffuser.py` establishes integrity, not redistribution rights.
- Optional CUDA 13 CuPy installation pulls NVIDIA runtime/toolkit component wheels.
  Review their licenses and redistribution terms separately before bundling them;
  the repository only records an opt-in requirements set.
- Rendered-video export makes `imageio-ffmpeg 0.6.0` a direct dependency. Inspect
  the bundled FFmpeg binary's build configuration, notices and redistribution
  obligations for the final release artifact; successful local encoding is not
  a licensing clearance.

## Gates before publishing

1. Record trusted provenance and applicable terms for the existing DLL, model
   weights, sample artwork, optional flow sources/checkpoints, and dependency bundle.
   Decide which examples/assets may actually ship; replace or omit uncleared files.
2. Validate the approved package on a separate clean Windows machine, including
   installation with no compiler/toolkit present (clear prerequisite errors),
   selected GPU architecture, paths with spaces, and a short render for both engines.
3. Review the final Git diff/staged inventory and deliberately create the release.
   Neither a model switch nor passing tests grants publishing permission.
