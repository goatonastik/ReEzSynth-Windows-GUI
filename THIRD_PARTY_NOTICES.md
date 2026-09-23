# Third-party components and runtime assets

ReEzSynth is distributed under GNU AGPL v3. It combines and adapts work from
other projects. Preserve this file, the top-level `LICENSE`, and the license files
under `licenses/` and `third_party/` when redistributing ReEzSynth.
This inventory records engineering provenance and notices; it is not blanket legal
clearance for every jurisdiction or use.

## EbSynth and the original Ezsynth pipeline

The original EbSynth source is published by Ondrej Jamriska as public-domain
code. Its README warns that the implementation uses PatchMatch, which it identifies
as patented in the United States, and places responsibility for patent review on
the user. ReEzSynth is not affiliated with the commercial EbSynth application.

The included `ezsynth/utils/ebsynth.dll` is retained for stability. Its SHA-256 is
`e3cfad210d445fcbfa6c7dcd2f9bdaaf36d550746c108c79a94d2d1ecce41369`.
It is byte-identical to the precompiled DLL published in Trentonom0r3/Ezsynth at
commit `b198f2d`. That project publishes its Python pipeline under GNU AGPL v3 and
documents the DLL as an included alternative to rebuilding from its EbSynth fork.

- Original source and license statement: https://github.com/jamriska/ebsynth
- Python pipeline and published DLL: https://github.com/Trentonom0r3/Ezsynth
- Corresponding ReEzSynth source license: `LICENSE`

## RAFT optical flow

RAFT is Copyright (c) 2020, princeton-vl and licensed under BSD-3-Clause. The full
license is retained at `third_party/raft_alt_cuda_corr/LICENSE`.

The included `raft-sintel.pth` and `raft-kitti.pth` checkpoints are byte-identical
to the files in the official `models.zip` referenced by RAFT's download script at
commit `2888e15a51fa41140771d3f498ed8023cff098d1`. Their expected hashes are recorded
in `runtime-assets.json`. The unused `raft-small.pth` checkpoint is intentionally
excluded from the distribution. ReEzSynth does not claim authorship of the models
or use the Princeton or contributor names to endorse this project.

The optional memory-efficient correlation wheel is a ReEzSynth Windows build from
the included RAFT `alt_cuda_corr` source with documented compatibility changes. It
is limited to the Python, PyTorch, CUDA, Windows and GPU architectures listed in
`INSTALL_WINDOWS.md`; normal RAFT remains available when it is incompatible.

- Upstream project: https://github.com/princeton-vl/RAFT
- Retained license and build source: `third_party/raft_alt_cuda_corr/`

## FuouM ReEzSynth and NeuFlow v2

FuouM/ReEzSynth supplies the separately installed synthesis engine and is licensed
under MIT. Its license is retained at `licenses/FuouM-MIT.txt`.

NeuFlow v2 is an optional optical-flow component used by that engine and is
licensed under Apache-2.0. Its license is retained at
`licenses/NeuFlow-Apache-2.0.txt`. Setup downloads its pinned checkpoint from the
upstream project and verifies the expected SHA-256 before installation.

- FuouM/ReEzSynth: https://github.com/FuouM/ReEzSynth
- NeuFlow v2: https://github.com/neufieldrobotics/NeuFlow_v2

## Other dependencies

Python packages installed by the setup scripts retain their own licenses and
notices. Optional EF-RAFT, FlowDiffuser and CuPy components are not bundled runtime
assets. Their setup paths, sources and limitations are documented in
`INSTALL_WINDOWS.md` and `RELEASE_AUDIT.md`.
