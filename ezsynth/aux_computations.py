import tqdm
import numpy as np
from .edge_detection import EdgeDetector
from reezsynth_sequence import array_sequence


def precompute_edge_guides(
    img_frs_seq: list[np.ndarray], edge_method: str, edge_settings=None
) -> list[np.ndarray]:
    edge_detector = EdgeDetector(edge_method)
    from reezsynth_edges import compute_tuned_edge
    edge_maps = array_sequence()
    for img_fr in tqdm.tqdm(img_frs_seq, desc="Calculating edge maps"):
        edge_maps.append(compute_tuned_edge(edge_detector, img_fr, edge_method, edge_settings))
    return edge_maps
