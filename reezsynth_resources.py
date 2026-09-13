"""Lightweight GPU telemetry and conservative per-job VRAM estimates."""
import json
import os
from pathlib import Path
import subprocess

from PySide6.QtGui import QImageReader

from reezsynth_engines import FUOUM


def gpu_snapshot(run=subprocess.run, environ=None):
    """Return the CUDA-default NVIDIA GPU without importing CUDA or torch."""
    command = ["nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free",
               "--format=csv,noheader,nounits"]
    try:
        result = run(command, capture_output=True, text=True, timeout=2,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            return None
        devices = []
        for line in result.stdout.splitlines():
            fields = [field.strip() for field in line.split(",", 5)]
            if len(fields) != 6:
                continue
            devices.append(dict(index=int(fields[0]), uuid=fields[1], name=fields[2],
                                total_mib=int(fields[3]), used_mib=int(fields[4]),
                                free_mib=int(fields[5])))
        if not devices:
            return None
        environment = os.environ if environ is None else environ
        visible = environment.get("CUDA_VISIBLE_DEVICES", "").split(",")[0].strip()
        if visible == "-1":
            return None
        if visible:
            match = next((item for item in devices
                          if str(item["index"]) == visible or item["uuid"].startswith(visible)), None)
            return match
        return devices[0]
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None


def safety_reserve_mib(snapshot):
    """Leave room for the desktop and estimate error."""
    return max(1024, min(4096, int(snapshot["total_mib"] * 0.10)))


def _source_path(job):
    image = job.get("image_synthesis", {})
    for value in (image.get("target"), image.get("source"), job.get("style")):
        if value:
            return Path(value)
    frames = job.get("frames", [])
    if frames and isinstance(frames[0], (list, tuple)) and len(frames[0]) == 2:
        return Path(frames[0][1])
    return None


def processed_size(job):
    """Resolve the effective dimensions cheaply from job metadata/image header."""
    exact = job.get("processing_size")
    if isinstance(exact, (list, tuple)) and len(exact) == 2 and all(type(v) is int and v > 0 for v in exact):
        return int(exact[0]), int(exact[1])
    source = _source_path(job)
    if source is None:
        return 1920, 1080
    size = QImageReader(str(source)).size()
    if not size.isValid() or size.width() <= 0 or size.height() <= 0:
        return 1920, 1080
    width, height = size.width(), size.height()
    maximum = job.get("max_width", 0)
    if type(maximum) is int and maximum > 0 and width > maximum:
        height = max(1, round(height * maximum / width))
        width = maximum
    return width, height


def estimate_job_vram(job_or_path):
    """Estimate peak worker VRAM in MiB from resolution and selected algorithms.

    This intentionally errs high. It is an admission reservation, not a claim of
    measured allocation and not a replacement for CUDA's own OOM handling.
    """
    if isinstance(job_or_path, (str, Path)):
        job = json.loads(Path(job_or_path).read_text(encoding="utf-8"))
    else:
        job = job_or_path
    width, height = processed_size(job)
    megapixels = width * height / 1_000_000
    options = job.get("render_options", {})
    engine = options.get("engine") or job.get("engine_runtime", {}).get("engine")
    grouped = job.get("type") == "grouped_video" or "styles" in job
    blend = job.get("blend_options", {})

    if engine == FUOUM:
        base, per_mp = 2200, 1800
        if options.get("fuoum_flow_engine") == "NeuFlow":
            base += 400
    else:
        architecture = options.get("flow_arch", "RAFT")
        base = {"RAFT": 1900, "EF_RAFT": 2300, "FLOW_DIFF": 4100}.get(architecture, 2300)
        per_mp = 800 if options.get("memory_efficient_raft") else 1300
    if grouped:
        base += 400
    if blend.get("use_gpu"):
        base += 800
        per_mp += 350
    if blend.get("use_poisson_cupy"):
        base += 600
    estimate = max(1024, int(round(base + per_mp * megapixels)))
    if engine == FUOUM and options.get('fuoum_backend', 'cuda') == 'torch':
        from reezsynth_torch_backend import working_bytes
        source_size = (width, height)
        channels = 24  # Conservative video/native channel cap, including sparse/mask guides.
        if job.get('type') == 'image_synthesis':
            image = job.get('image_synthesis', {})
            source_size = processed_size(dict(job, image_synthesis={'target': image.get('style')}))
            try:
                from PIL import Image
                channels = 0
                for guide in [image, *image.get('guides', [])]:
                    with Image.open(guide['target']) as handle:
                        channels += len(handle.getbands())
                channels = min(24, max(1, channels))
            except (OSError, KeyError, ValueError):
                channels = 24
        from reezsynth_config import quality_profile
        patch = options.get('patchsize', quality_profile(job.get('quality', 'Standard'))['patchsize'])
        estimate += (working_bytes(source_size, (width, height), channels, patch) + 2 ** 20 - 1) // 2 ** 20
    return dict(estimated_mib=estimate, width=width, height=height,
                engine=engine or "unknown", basis="conservative estimate")


def format_mib(value):
    return f"{value / 1024:.1f} GiB" if value >= 1024 else f"{value} MiB"
