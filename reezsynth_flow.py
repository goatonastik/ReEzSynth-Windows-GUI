"""Explicit pixel-space flow semantics shared by diagnostics and the FuouM adapter."""
import cv2
import numpy as np


def pull_warp(image, target_to_source):
    """Sample source at (x+dx,y+dy) for each pixel on the target frame's grid."""
    h, w = image.shape[:2]
    flow = np.asarray(target_to_source, dtype=np.float32)
    if flow.shape != (h, w, 2) or not np.isfinite(flow).all():
        raise ValueError('Pull warping requires finite HxWx2 flow on the target grid.')
    y, x = np.mgrid[:h, :w].astype(np.float32)
    return cv2.remap(np.asarray(image, dtype=np.float32), x + flow[..., 0], y + flow[..., 1],
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def run_bidirectional_pass(pipeline, seq, style_img, is_forward, content_frames):
    """Carry style, NNF and keyframe coordinates with independently estimated pull flow."""
    h, w = content_frames[0].shape[:2]
    key = seq.start_frame if is_forward else seq.end_frame
    step = 1 if is_forward else -1
    source_indices = range(key, seq.end_frame if is_forward else seq.start_frame, step)
    xx, yy = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
    coords = np.stack((xx, yy, np.zeros_like(xx)), axis=-1).astype(np.float32)
    source_pos = (coords * 255).astype(np.uint8)
    images, errors, flows, nnfs = [style_img], [], [], []
    previous_nnf = None
    propagate = pipeline.config.pipeline.use_temporal_nnf_propagation
    for source in source_indices:
        target = source + step
        # Forward synthesis pulls with backward flow; reverse synthesis pulls
        # with forward flow. Each field is evaluated on the destination grid.
        flow = pipeline._bwd_flows[source] if is_forward else pipeline._fwd_flows[target]
        coords = pull_warp(coords, flow)
        warped_style = np.clip(pull_warp(images[-1], flow), 0, 255).astype(np.uint8)
        guides = pipeline._prepare_guides_for_frame(
            keyframe_idx=key, target_idx=target, style_img=style_img,
            warped_previous_style=warped_style, source_pos_guide=source_pos,
            target_pos_guide=np.clip(coords * 255, 0, 255).astype(np.uint8),
            content_frames=content_frames)
        initial = None if previous_nnf is None else pull_warp(previous_nnf, flow).astype(np.int32)
        result = pipeline.synthesis_engine.run(style_img, guides=guides,
            initial_nnf=initial, output_nnf=propagate)
        images.append(result[0])
        errors.append(result[1])
        flows.append(flow)
        if propagate:
            previous_nnf = result[2]
            nnfs.append(previous_nnf)
    if not is_forward:
        for values in (images, errors, flows, nnfs):
            values.reverse()
    return images, errors, flows, nnfs
