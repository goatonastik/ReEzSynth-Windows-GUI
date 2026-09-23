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
| `ReEzSynth-source-bundle.txt`, the former `examples/gui_keyframes_v03.backup-20260908-184704697`, root `reezsynth_gui_v02.py`, `reezsynth_gui_v03.txt`, `reezsynth_gui_v031.txt`, `reezsynth_gui_v04.py` | Developer snapshots untracked and ignored after dependency review. Useful local copies and Git history are preserved; new commits/clones no longer include them. |
| Required RAFT checkpoints (`sintel`, `kitti`) | Keep the two proven, hash-locked checkpoints so clean installs and offline rendering retain the tested behavior. They are byte-identical to RAFT's official `models.zip`; exact hashes, the archive, and `download_models.sh` from pinned RAFT commit `2888e15` are retained in the 2026-09-21 audit. The unused `raft-small` checkpoint is removed. Retain the BSD notice and consolidated attribution. |
| `ezsynth/utils/ebsynth.dll` | Keep the proven DLL for stability. It is byte-identical to the precompiled DLL intentionally published by Trentonom0r3/Ezsynth commit `b198f2d`, which records the same checksum, documents using it without rebuilding, records a build command and names its build-source checkout. Preserve the AGPL source, original EbSynth public-domain statement, patent warning, exact hash and attribution. A different locally built DLL must pass a separate parity/performance gate before replacement. |
| Compiled RAFT wheel | Keep the tested CPython 3.11/Windows AMD64 wheel with its exact hash, platform limits, normal-RAFT fallback, included source and BSD-3-Clause license. It was added with its tracked source in local commit `4aa832e`; its metadata and archive embed the license. It is not represented as a universal or official upstream binary. |
| Sample photographs, paintings, masks and image-guide assets | Removed from the current tree by owner decision; neither release format may include them. Diagnostics now generate deterministic inputs at run time under the ignored `diagnostic_outputs/` tree. Their earlier hashes and provenance findings remain in local audit evidence and Git history. |

The media was removed from the current branch without rewriting Git history. No
release was uploaded. A GitHub source archive is not yet a cleared binary package.
Generated `.reezsynth-queue*.json` files are recovery data inside render batches.
They contain absolute input, output and Python-runtime paths; inspect or remove
them before sharing a render folder.
Project `.reezsynth-cache` directories contain generated NumPy flow/edge arrays
and identity records with checkpoint paths/hashes. They are ignored and must not
be packaged; stop workers before deleting them to reclaim disk space.

## Notices and provenance

- The base repository's [LICENSE](LICENSE) is **GNU AGPL v3**, not ordinary GPL
  or MIT. See the [original repository license](https://github.com/Trentonom0r3/Ezsynth/blob/main/LICENSE).
- FuouM's pinned source declares MIT; retain [its license](licenses/FuouM-MIT.txt)
  and [upstream attribution](https://github.com/FuouM/ReEzSynth/blob/aaa8d06170e6cc59054410aa9c422edd789f7ab2/LICENSE).
- RAFT declares BSD-3-Clause. The retained
  [license](third_party/raft_alt_cuda_corr/LICENSE) accompanies the compiled
  correlation source; see [upstream](https://github.com/princeton-vl/RAFT/blob/master/LICENSE).
  The three tracked checkpoints were compared byte-for-byte with the official
  archive referenced by `download_models.sh` at pinned RAFT commit `2888e15`;
  that script and archive are retained in ignored evidence. This establishes their
  source chain, while any model/training-data rights beyond the repository license
  remain a release-review question.
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

1. Complete the dependency-bundle notice review, including the imageio-ffmpeg
   executable and optional flow components. The retained DLL, required RAFT weights
   and correlation wheel now have accepted exact-hash provenance and distribution
   decisions in `THIRD_PARTY_NOTICES.md`. Confirm the final inventory contains no
   removed example media.
2. Validate the approved package on a separate clean Windows machine, including
   installation with no compiler/toolkit present (clear prerequisite errors),
   selected GPU architecture, paths with spaces, and a short render for both engines.
3. Review the final Git diff/staged inventory and deliberately create the release.
   Neither a model switch nor passing tests grants publishing permission.

## Candidate packaging

`build_release.ps1` and the manual `Build release candidates` workflow produce a
source ZIP and a per-user Inno Setup installer from one clean, reviewed commit.
They write SHA-256 checksums and a commit manifest, reject bundled raster/example
media and local output paths, and do not create a GitHub release. The installer
copies the application tree and offers the several-gigabyte dependency setup as
an explicit unchecked action. See `PACKAGING.md` for candidate validation.

Current candidates retain the tested EbSynth DLL, required RAFT checkpoints and
Windows correlation wheel under the stability-first decisions above. The unused
RAFT Small checkpoint is excluded. Do not publish one until the remaining
dependency notices are reviewed and a clean-machine candidate passes.

## 2026-09-21 local provenance comparison

The tracked DLL, checkpoints, wheel and all 65 example files now have a retained
exact-hash inventory. The three RAFT checkpoints match the official RAFT download
archive;
the DLL and 60 of 65 example files match Trentonom0r3/Ezsynth `b198f2d`; nineteen
example images also match jamriska/ebsynth `2f5c97c`. The three locally added GUI
keyframes are byte-identical duplicates of upstream style images. The remaining
two example differences are launcher scripts. Detailed hashes, method, limits and
the concrete release choices are retained locally in ignored evidence:
`diagnostic_outputs/provenance_audit_20260921/REPORT.md`.

This reduced source-chain uncertainty. The example-media issue was subsequently
resolved by removing the entire set from the current tree and generating diagnostic
inputs procedurally. Remaining decisions concern the DLL's non-reproducible retained
build provenance and whether checkpoint/wheel inclusion matches the chosen package
and notices. No public artifact was created.
