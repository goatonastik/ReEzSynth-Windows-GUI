from datetime import datetime
from pathlib import Path
import time

import cv2
import numpy as np

from ezsynth.aux_classes import RunConfig
from ezsynth.main_ez import EzsynthBase
from reezsynth_synthetic_inputs import frame, style


def main():
    root = Path(__file__).resolve().parent
    size = (512, 288)

    frames = [frame(size, index, 11) for index in range(3)]
    key_style = style(frames[0])

    cfg = RunConfig(
        patchsize=5,
        pyramidlevels=3,
        searchvoteiters=4,
        patchmatchiters=3,
        extrapass3x3=False,
        use_gpu=False,          # CPU blending; blending is not used here.
        use_poisson_cupy=False,
    )

    started = time.perf_counter()

    runner = EzsynthBase(
        style_frs=[key_style],
        style_idxes=[0],
        img_frs_seq=frames,
        cfg=cfg,
        edge_method="Classic",
        raft_flow_model_name="sintel",
        flow_arch="RAFT",
        do_mask=False,
    )

    # Requires the backend-forwarding edits made earlier.
    runner.eb.backend = runner.eb.backends["cuda"]

    print("Running three-frame sequence with requested EbSynth CUDA backend.",
          flush=True)

    results, errors = runner.run_sequences()

    if len(results) != len(frames):
        raise RuntimeError(
            f"Expected {len(frames)} output frames, received {len(results)}."
        )

    output_dir = (
        root / "diagnostic_outputs"
        / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    )
    output_dir.mkdir(parents=True, exist_ok=False)

    for index, image in enumerate(results):
        if image.shape != frames[index].shape:
            raise RuntimeError(f"Unexpected shape for frame {index}: {image.shape}")
        if not np.isfinite(image).all():
            raise RuntimeError(f"Non-finite pixels in frame {index}.")

        path = output_dir / f"output_{index:03d}.png"
        image = np.clip(image, 0, 255).astype(np.uint8)
        if not cv2.imwrite(str(path), image):
            raise RuntimeError(f"Could not save: {path}")

    print(f"Passed: {len(results)} frames, {len(errors)} error maps.")
    print(f"Total time including initialization: "
          f"{time.perf_counter() - started:.3f}s")
    print("Output folder:", output_dir)


if __name__ == "__main__":
    main()
