from pathlib import Path
import time

import cv2
import numpy as np
import torch

from ezsynth.utils.flow_utils.OpticalFlow import RAFT_flow
from ezsynth.aux_flow_viz import flow_to_image
from reezsynth_synthetic_inputs import frame


def main():
    root = Path(__file__).resolve().parent

    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch CUDA is unavailable.")

    # Small diagnostic resolution, not final rendering resolution.
    frames = [frame((512, 288), index, 11) for index in range(2)]

    print("GPU:", torch.cuda.get_device_name(0), flush=True)
    print("Loading RAFT sintel...", flush=True)

    rafter = RAFT_flow(model_name="sintel", arch="RAFT")
    print("Model device:", next(rafter.model.parameters()).device, flush=True)

    for attempt in range(1, 3):
        torch.cuda.synchronize()
        started = time.perf_counter()

        flow = rafter._compute_flow(frames[0], frames[1])

        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started

        if flow.shape != (288, 512, 2):
            raise RuntimeError(f"Unexpected flow shape: {flow.shape}")

        if not np.isfinite(flow).all():
            raise RuntimeError("Optical flow contains NaN or infinity.")

        print(
            f"Run {attempt}: {elapsed:.3f}s | "
            f"shape={flow.shape} | "
            f"range=[{flow.min():.3f}, {flow.max():.3f}]",
            flush=True,
        )

    output = root / "diagnostic_raft_flow.png"
    visualization = flow_to_image(flow, convert_to_bgr=True)

    if not cv2.imwrite(str(output), visualization):
        raise RuntimeError(f"Could not save {output}")

    print("Saved:", output)
    print("RAFT diagnostic passed.")


if __name__ == "__main__":
    main()
