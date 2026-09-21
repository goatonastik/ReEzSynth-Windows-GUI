import cv2
import numpy as np
import tqdm
from reezsynth_sequence import array_sequence, copy_number


def apply_mask(image: np.ndarray, mask: np.ndarray):
    masked_image = cv2.bitwise_and(image, image, mask=mask)
    return copy_number(masked_image.astype(np.uint8), image)


def apply_masks(images: list[np.ndarray], masks: list[np.ndarray]):
    len_img = len(images)
    len_msk = len(masks)
    if len_img != len_msk:
        raise ValueError(f"[{len_img=}], [{len_msk=}]")

    masked_images = array_sequence()
    for i in range(len_img):
        masked_images.append(apply_mask(images[i], masks[i]))

    return masked_images


def apply_masks_idxes(
    images: list[np.ndarray], masks: list[np.ndarray], img_idxes: list[int]
):
    masked_images = array_sequence()
    for i, idx in enumerate(img_idxes):
        masked_images.append(apply_mask(images[i], masks[idx]))
    return masked_images


def apply_masked_back(
    original: np.ndarray, processed: np.ndarray, mask: np.ndarray, feather_radius=0
):
    if processed.shape[2] == 4 and original.shape[2] == 3:
        from reezsynth_alpha import as_bgra
        original = as_bgra(original)
    if feather_radius > 0:
        mask = cv2.GaussianBlur(mask, (feather_radius, feather_radius), 0)

    coverage = np.expand_dims(mask.astype(np.float32) / 255.0, axis=-1)
    if processed.shape[2] == 4:
        foreground_alpha = processed[..., 3:4].astype(np.float32) / 255.0
        background_alpha = original[..., 3:4].astype(np.float32) / 255.0
        effective_alpha = coverage * foreground_alpha
        output_alpha = effective_alpha + background_alpha * (1.0 - effective_alpha)
        premultiplied = (
            processed[..., :3].astype(np.float32) * effective_alpha
            + original[..., :3].astype(np.float32)
            * background_alpha * (1.0 - effective_alpha)
        )
        output_rgb = np.zeros_like(premultiplied)
        np.divide(premultiplied, output_alpha, out=output_rgb, where=output_alpha > 0)
        result = np.concatenate((output_rgb, output_alpha * 255.0), axis=2)
        return np.clip(np.rint(result), 0, 255).astype(np.uint8)
    else:
        # Preserve the historical RGB truncation; rounding here changes legacy output.
        result = original * (1.0 - coverage) + processed * coverage

    return np.clip(result, 0, 255).astype(np.uint8)


def apply_masked_back_seq(
    img_frs_seq: list[np.ndarray],
    styled_msk_frs: list[np.ndarray],
    mask_frs_seq: list[np.ndarray],
    feather=0,
):
    len_img = len(img_frs_seq)
    len_stl = len(styled_msk_frs)
    len_msk = len(mask_frs_seq)

    if not (len_img == len_stl == len_msk):
        raise ValueError(f"Lengths not match. [{len_img=}, {len_stl=}, {len_msk=}]")

    backed_seq = array_sequence()

    for i in tqdm.tqdm(range(len_img), desc="Adding masked back"):
        backed_seq.append(
            apply_masked_back(
                img_frs_seq[i], styled_msk_frs[i], mask_frs_seq[i], feather
            )
        )

    return backed_seq
