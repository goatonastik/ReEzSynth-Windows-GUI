"""Conservative classification of explicit worker exception lines."""
import re


def is_cuda_out_of_memory(line):
    return bool(re.match(
        r'^(?:(?:torch(?:\.cuda)?\.)?OutOfMemoryError|RuntimeError):\s*'
        r'(?:CUDA out of memory\b|CUDA error: out of memory\b)', line.strip(), re.I))
