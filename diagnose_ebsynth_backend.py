import sys
import time
from pathlib import Path

import cv2
import numpy as np

from ezsynth.utils._ebsynth import ebsynth


def main() -> int:
    backend = sys.argv[1].lower() if len(sys.argv) > 1 else "cpu"

    if backend not in {"cpu", "cuda", "auto"}:
        print("Usage: python diagnose_ebsynth_backend.py [cpu|cuda|auto]")
        return 2

    root = Path(__file__).resolve().parent
    example = root / "examples" / "texbynum"

    style = cv2.imread(str(example / "source_photo.png"))
    source_guide = cv2.imread(str(example / "source_segment.png"))
    target_guide = cv2.imread(str(example / "target_segment.png"))

    if any(image is None for image in (style, source_guide, target_guide)):
        raise FileNotFoundError("Could not read the texbynum example images.")

    engine = ebsynth(
        uniformity=1000.0,
        patchsize=3,
        pyramidlevels=3,
        searchvoteiters=2,
        patchmatchiters=2,
        extrapass3x3=False,
        backend=backend,
    )

    engine.runner.initialize_libebsynth()

    print(f"Requested backend: {backend}")
    print(f"Style dimensions: {style.shape}")
    print(f"Target dimensions: {target_guide.shape}")

    started = time.perf_counter()

    output, error = engine.run(
        style,
        guides=[
            (source_guide, target_guide, 1.0),
        ],
    )

    elapsed = time.perf_counter() - started

    output_path = root / f"diagnostic_{backend}.png"
    error_path = root / f"diagnostic_{backend}_error.png"

    cv2.imwrite(str(output_path), output)

    error_normalized = cv2.normalize(
        error,
        None,
        0,
        255,
        cv2.NORM_MINMAX,
    ).astype(np.uint8)

    cv2.imwrite(str(error_path), error_normalized)

    print(f"Completed in {elapsed:.3f} seconds")
    print(f"Output: {output_path}")
    print(f"Error map: {error_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())