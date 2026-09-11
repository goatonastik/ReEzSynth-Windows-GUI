from setuptools import setup
from torch.utils.cpp_extension import BuildExtension, CUDAExtension
import sys


setup(
    name='reezsynth-alt-cuda-corr',
    version='0.2.0',
    description='RAFT alternative correlation, Windows/PyTorch compatibility build for ReEzSynth',
    license='BSD-3-Clause',
    license_files=['LICENSE'],
    ext_modules=[
        CUDAExtension('alt_cuda_corr',
            sources=['correlation.cpp', 'correlation_kernel.cu'],
            extra_compile_args={'cxx': ['/O2'] if sys.platform == 'win32' else ['-O3'], 'nvcc': ['-O3']}),
    ],
    cmdclass={
        'build_ext': BuildExtension.with_options(use_ninja=False)
    })
