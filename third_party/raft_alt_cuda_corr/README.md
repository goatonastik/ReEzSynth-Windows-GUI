# RAFT alternative CUDA correlation

Source: https://github.com/princeton-vl/RAFT/tree/2888e15a51fa41140771d3f498ed8023cff098d1/alt_cuda_corr

Copyright (c) 2020, princeton-vl. See LICENSE (BSD-3-Clause).

This ReEzSynth compatibility build updates the tensor CUDA check, validates the
forward interface, uses the current PyTorch CUDA stream/device, checks kernel
launch errors, initializes coordinates for edge threads and synchronizes shared
memory reuse. The CUDA translation unit uses torch/types.h to avoid Windows
compiler errors in Python-binding headers; the retained backward code uses an
explicit float square root for NVCC compatibility. It exposes inference forward
only; upstream backward does not
compute coordinate gradients. It is not an official Princeton release.

Float32 contiguous CUDA inputs are required; channels must be a multiple of 32.
RAFT's 128/256 feature channels satisfy this requirement. No fast-math flag or
reduced-precision option is enabled by this build. Build outputs are ignored by Git.

The repository release wheel is built for Python 3.11 and PyTorch 2.11.0+cu128,
with CUDA architectures 7.5, 8.0, 8.6, 8.9 and 12.0. Use the helper to build for
another supported local configuration.
