import cv2
import numpy as np
import tqdm
from reezsynth_sequence import array_sequence

from .aux_classes import PositionalGuide, RunConfig
from .utils._ebsynth import ebsynth
from .utils.blend.blender import Blend
from .utils.flow_utils.OpticalFlow import RAFT_flow
from .utils.flow_utils.warp import Warp
from .sequences import EasySequence


def _weighted_transition(base, forward, backward, forward_weight, backward_weight):
    """Mix motion-propagated candidates, preserving straight-alpha edge color."""
    total = forward_weight + backward_weight
    if total > 1.0:
        forward_weight /= total
        backward_weight /= total
        base_weight = 0.0
    else:
        base_weight = 1.0 - total
    frames = (np.asarray(base), np.asarray(forward), np.asarray(backward))
    weights = (base_weight, forward_weight, backward_weight)
    if frames[0].shape[2] != 4:
        value = sum(frame.astype(np.float32) * weight for frame, weight in zip(frames, weights))
        return np.clip(np.rint(value), 0, 255).astype(np.uint8)

    alpha = sum(frame[..., 3:4].astype(np.float32) * weight
                for frame, weight in zip(frames, weights))
    premultiplied = sum(frame[..., :3].astype(np.float32) * (frame[..., 3:4] / 255.0) * weight
                        for frame, weight in zip(frames, weights))
    color = np.zeros_like(premultiplied)
    np.divide(premultiplied, alpha / 255.0, out=color, where=alpha > 0)
    return np.concatenate((np.clip(np.rint(color), 0, 255),
                           np.clip(np.rint(alpha), 0, 255)), axis=2).astype(np.uint8)


def apply_transition_aware_handoff(blends, style_fwd, style_bwd, radius=2):
    """Favor each key's propagated candidate near a blend boundary."""
    count = len(blends)
    full_count = len(style_fwd)
    for index in range(1, count):
        left_distance = index
        right_distance = full_count - 1 - index
        left = ((radius + 1 - left_distance) / (radius + 1)
                if 1 <= left_distance <= radius else 0.0)
        right = ((radius + 1 - right_distance) / (radius + 1)
                 if 1 <= right_distance <= radius else 0.0)
        if left or right:
            blends[index] = _weighted_transition(
                blends[index], style_fwd[index], style_bwd[index], left, right)
    return blends


def run_a_pass(
    seq: EasySequence,
    seq_mode: str,
    img_frs_seq: list[np.ndarray],
    style: np.ndarray,
    edge: list[np.ndarray],
    cfg: RunConfig,
    rafter: RAFT_flow,
    eb: ebsynth,
):
    stylized_frames = array_sequence([style])
    err_list = array_sequence()
    ORIGINAL_SIZE = img_frs_seq[0].shape[1::-1]

    start, end, step, is_forward = (
        get_forward(seq) if seq_mode == EasySequence.MODE_FWD else get_backward(seq)
    )
    rgba = style.shape[2] == 4
    if rgba:
        from reezsynth_alpha import synthesize_keyframe
        seed, _ = synthesize_keyframe(style, img_frs_seq[start], edge[start], eb,
                                     {name: getattr(cfg, name) for name in
                                      ('edg_wgt', 'img_wgt', 'pos_wgt', 'wrp_wgt')})
        stylized_frames[0] = seed
    warp = Warp(img_frs_seq[start])
    print(f"{'Forward' if is_forward else 'Reverse'} mode. {start=}, {end=}, {step=}")
    flows = array_sequence()
    first_poster = None
    pos_guider = PositionalGuide()

    for i in tqdm.tqdm(range(start, end, step), "Generating"):
        flow = get_flow(img_frs_seq, rafter, step, is_forward, i)
        flows.append(flow)

        poster = pos_guider.create_from_flow(flow, ORIGINAL_SIZE, warp)
        if first_poster is None:
            first_poster = poster
        warped_img = get_warped_img(stylized_frames, ORIGINAL_SIZE, step, warp, flow)

        stylized_img, err = eb.run(
            style,
            guides=[
                (edge[start], edge[i + step], cfg.edg_wgt),  # Slower with premask
                (img_frs_seq[start], img_frs_seq[i + step], cfg.img_wgt),
                (first_poster, poster, cfg.pos_wgt),
                (np.ascontiguousarray(style[..., :3]) if rgba else style,
                 np.ascontiguousarray(warped_img[..., :3]) if rgba else warped_img,
                 cfg.wrp_wgt),  # Alpha remains a style/output channel, not a guide.
            ],
        )
        stylized_frames.append(stylized_img)
        err_list.append(err)

    if not is_forward:
        stylized_frames = stylized_frames[::-1]
        err_list = err_list[::-1]
        flows = flows[::-1]

    return stylized_frames, err_list, flows


def get_warped_img(
    stylized_frames: list[np.ndarray], ORIGINAL_SIZE, step: int, warp: Warp, flow
):
    stylized_img = stylized_frames[-1] / 255.0
    warped_img = warp.run_warping(stylized_img, flow * (-step))
    if warped_img is None:
        raise RuntimeError('Frame warp failed before resizing the synthesized image.')
    warped_img = cv2.resize(warped_img, ORIGINAL_SIZE)
    return warped_img


def get_flow(
    img_frs_seq: list[np.ndarray],
    rafter: RAFT_flow,
    step: int,
    is_forward: bool,
    i: int,
):
    if is_forward:
        flow = rafter._compute_flow(img_frs_seq[i], img_frs_seq[i + step])
    else:
        flow = rafter._compute_flow(img_frs_seq[i + step], img_frs_seq[i])
    return flow


def run_scratch(
    seq: EasySequence,
    img_frs_seq: list[np.ndarray],
    style_frs: list[np.ndarray],
    edge: list[np.ndarray],
    cfg: RunConfig,
    rafter: RAFT_flow,
    eb: ebsynth,
):
    if seq.mode == EasySequence.MODE_BLN and cfg.only_mode != EasySequence.MODE_NON:
        print(f"{cfg.only_mode} Only")
        stylized_frames, err_list, flow = run_a_pass(
            seq,
            cfg.only_mode,
            img_frs_seq,
            style_frs[seq.style_idxs[0]]
            if cfg.only_mode == EasySequence.MODE_FWD
            else style_frs[seq.style_idxs[1]],
            edge,
            cfg,
            rafter,
            eb,
        )
        return stylized_frames, err_list, flow

    if seq.mode != EasySequence.MODE_BLN:
        stylized_frames, err_list, flow = run_a_pass(
            seq,
            seq.mode,
            img_frs_seq,
            style_frs[seq.style_idxs[0]],
            edge,
            cfg,
            rafter,
            eb,
        )
        return stylized_frames, err_list, flow

    print("Blending mode")

    style_fwd, err_fwd, flow_fwd = run_a_pass(
        seq,
        EasySequence.MODE_FWD,
        img_frs_seq,
        style_frs[seq.style_idxs[0]],
        edge,
        cfg,
        rafter,
        eb,
    )

    style_bwd, err_bwd, _ = run_a_pass(
        seq,
        EasySequence.MODE_REV,
        img_frs_seq,
        style_frs[seq.style_idxs[1]],
        edge,
        cfg,
        rafter,
        eb,
    )

    return run_blend(img_frs_seq, style_fwd, style_bwd, err_fwd, err_bwd, flow_fwd, cfg)


def run_blend(
    img_frs_seq: list[np.ndarray],
    style_fwd: list[np.ndarray],
    style_bwd: list[np.ndarray],
    err_fwd: list[np.ndarray],
    err_bwd: list[np.ndarray],
    flow_fwd: list[np.ndarray],
    cfg: RunConfig,
):
    blender = Blend(**cfg.get_blender_cfg())

    err_masks = blender._create_selection_mask(err_fwd, err_bwd)

    # Keep the legacy boundary-mask policy, including its existing warp.  Every
    # later mask is already expressed on its output frame: forward error i - 1
    # and backward error i describe that same frame.
    warped_masks = blender._warping_masks(img_frs_seq[0], flow_fwd[:1], err_masks[:1])
    if len(err_masks) > 1:
        warped_masks.extend(
            blender._create_selection_mask(err_fwd[:-1], err_bwd[1:])
        )

    hist_blends = blender._hist_blend(style_fwd, style_bwd, warped_masks)

    blends = blender._reconstruct(style_fwd, style_bwd, warped_masks, hist_blends)

    if not cfg.skip_blend_style_last:
        blends.append(style_bwd[-1])

    if getattr(cfg, 'keyframe_preservation', 'Current behavior') == 'Transition-aware':
        blends = apply_transition_aware_handoff(blends, style_fwd, style_bwd)

    return blends, warped_masks, flow_fwd


def get_forward(seq: EasySequence):
    start = seq.fr_start_idx
    end = seq.fr_end_idx
    step = 1
    is_forward = True
    return start, end, step, is_forward


def get_backward(seq: EasySequence):
    start = seq.fr_end_idx
    end = seq.fr_start_idx
    step = -1
    is_forward = False
    return start, end, step, is_forward
