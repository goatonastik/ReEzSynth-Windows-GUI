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

## Optional Legacy optical-flow implementations

EF-RAFT revision `9ad323b373ba5f10f3bf97fdcf57e624be37d1b2` is distributed
under BSD-3-Clause. Its retained license is
`licenses/EF-RAFT-BSD-3-Clause.txt`. Optional EF-RAFT checkpoints are not bundled
and must be obtained separately from their upstream source.

The adapted FlowDiffuser implementation was distributed in
Trentonom0r3/Ezsynth commit `b198f2d7051eee542c4efc51c2d43dc442630bbf`
together with that repository's GNU AGPL v3 license. ReEzSynth retains that license,
corresponding source and attribution. The optional FlowDiffuser checkpoint is not
bundled and must be supplied separately; setup only downloads pinned Twin-SVT
backbones after explicit confirmation.

- EF-RAFT: https://github.com/n3slami/Ef-RAFT
- FlowDiffuser: https://github.com/LA30/FlowDiffuser
- AGPL source chain: https://github.com/Trentonom0r3/Ezsynth/tree/b198f2d7051eee542c4efc51c2d43dc442630bbf

## Downloaded Python and media dependencies

The source ZIP and Windows installer do not contain a Python environment or its
third-party packages. The explicit dependency setup installs pinned packages from
their package indexes, where their own licenses and notices remain included.

`imageio-ffmpeg 0.6.0` is a direct video-export dependency. Its Python wrapper is
BSD-2-Clause and its Windows wheel installs an FFmpeg 7.1 executable configured as
GPL v3. The executable runs as a separate subprocess. Neither the wheel nor FFmpeg
executable is embedded in ReEzSynth's release artifacts; it is downloaded by pip
during dependency setup. Users can inspect the installed binary with `ffmpeg -L`
and obtain FFmpeg corresponding source from https://ffmpeg.org/download.html.

Optional CuPy/NVIDIA packages, FlowDiffuser dependencies and model backbones are
also downloaded only after the user selects their setup path. They are not embedded
in the source ZIP or Windows installer. If a future standalone package embeds a
Python environment, FFmpeg, CUDA libraries, model files or wheels, it requires a
new license and corresponding-source audit before distribution.
