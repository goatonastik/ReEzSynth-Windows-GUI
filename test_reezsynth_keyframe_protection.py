"""Pixel-level generator contracts, independent of inference and GPU availability."""

import io
import unittest

import numpy as np
from PIL import Image

from reezsynth_keyframe_protection import (
    AlphaPolicy, EditIntent, NativeCanvas, compose_modified,
    propose_dark_strokes, protection_band,
)


class ProtectionTests(unittest.TestCase):
    def test_proposal_uses_alpha_and_does_not_claim_color_accent_protection(self):
        drawing = np.array([[[0, 0, 0, 0], [0, 0, 0, 1], [255, 255, 255, 255],
                             [150, 0, 0, 255], [25, 25, 25, 128]]], dtype=np.uint8)
        np.testing.assert_array_equal(propose_dark_strokes(drawing), [[0, 255, 0, 0, 255]])
        self.assertEqual(len(EditIntent), 3)

    def test_square_band_keeps_antialiased_seed_and_clips_at_border(self):
        mask = np.zeros((5, 7), dtype=np.uint8)
        mask[0, 0] = 1
        expected = np.zeros_like(mask)
        expected[:3, :3] = 255
        np.testing.assert_array_equal(protection_band(mask, 2), expected)
        self.assertEqual(mask[0, 0], 1)
        self.assertEqual(np.count_nonzero(protection_band(mask, 0)), 1)
        with self.assertRaises(ValueError):
            protection_band(mask, -1)

    def test_band_matches_brute_square_neighborhoods(self):
        rng = np.random.default_rng(8)
        for shape in ((1, 9), (9, 1), (7, 11)):
            mask = (rng.random(shape) > .8).astype(np.uint8)
            for radius in (0, 1, 2, 3, 4, 8, 16, 32, 64):
                expected = np.zeros(shape, dtype=np.uint8)
                for y in range(shape[0]):
                    for x in range(shape[1]):
                        window = mask[max(0, y-radius):y+radius+1,
                                      max(0, x-radius):x+radius+1]
                        expected[y, x] = 255 if window.any() else 0
                with self.subTest(shape=shape, radius=radius):
                    np.testing.assert_array_equal(protection_band(mask, radius), expected)

    def test_protection_wins_and_originals_are_not_mutated(self):
        rng = np.random.default_rng(72)
        drawing = rng.integers(0, 256, (17, 29, 4), dtype=np.uint8)
        candidate = rng.integers(0, 256, drawing.shape, dtype=np.uint8)
        edit = rng.integers(0, 256, drawing.shape[:2], dtype=np.uint8)
        edit[0] = 0
        protect = np.zeros_like(edit)
        protect[:, ::3] = 1
        untouched = (edit == 0) | (protect > 0)
        original = drawing.copy()
        raw = candidate.copy()
        for policy in AlphaPolicy:
            result, qc = compose_modified(drawing, candidate, edit, protect, alpha_policy=policy)
            np.testing.assert_array_equal(result[untouched], drawing[untouched])
            self.assertFalse(np.shares_memory(result, drawing))
            self.assertEqual(qc.protected_mismatches, 0)
            self.assertEqual(qc.editable_pixels + qc.protected_pixels, edit.size)
            self.assertEqual(qc.changed_pixels, np.any(result != drawing, axis=2).sum())
        np.testing.assert_array_equal(drawing, original)
        np.testing.assert_array_equal(candidate, raw)

    def test_preserve_alpha_keeps_hidden_rgb_and_does_not_use_hidden_candidate_color(self):
        drawing = np.array([[[17, 23, 61, 0], [0, 0, 0, 128], [12, 34, 56, 255]]], dtype=np.uint8)
        candidate = np.array([[[255, 0, 0, 255], [255, 255, 255, 128], [200, 0, 0, 0]]], dtype=np.uint8)
        mask = np.full((1, 3), 255, dtype=np.uint8)
        result, qc = compose_modified(drawing, candidate, mask, np.zeros_like(mask),
                                      alpha_policy=AlphaPolicy.PRESERVE)
        np.testing.assert_array_equal(result, [[[17, 23, 61, 0], [128, 128, 128, 128],
                                                [12, 34, 56, 255]]])
        self.assertEqual(qc.alpha_changed_pixels, 0)

    def test_edit_alpha_uses_premultiplied_mix_without_hidden_rgb_halo(self):
        drawing = np.array([[[255, 0, 0, 0], [0, 0, 255, 255]]], dtype=np.uint8)
        candidate = np.array([[[0, 0, 255, 255], [255, 0, 0, 0]]], dtype=np.uint8)
        edit = np.full((1, 2), 128, dtype=np.uint8)
        result, _ = compose_modified(drawing, candidate, edit, np.zeros_like(edit),
                                     alpha_policy=AlphaPolicy.EDIT)
        np.testing.assert_array_equal(result, [[[0, 0, 255, 128], [0, 0, 255, 127]]])

    def test_full_edit_and_empty_edit_have_exact_endpoint_semantics(self):
        drawing = np.array([[[10, 20, 30, 0], [80, 90, 100, 128]]], dtype=np.uint8)
        candidate = np.array([[[30, 40, 50, 0], [11, 22, 33, 1]]], dtype=np.uint8)
        empty = np.zeros((1, 2), dtype=np.uint8)
        for amount, expected in ((0, drawing), (255, candidate)):
            result, _ = compose_modified(drawing, candidate, np.full_like(empty, amount), empty,
                                         alpha_policy=AlphaPolicy.EDIT)
            np.testing.assert_array_equal(result, expected)
            with io.BytesIO() as stream:
                Image.fromarray(result).save(stream, format="PNG")
                stream.seek(0)
                np.testing.assert_array_equal(np.array(Image.open(stream)), expected)

    def test_invalid_inputs_are_rejected_instead_of_resized_or_coerced(self):
        image = np.zeros((2, 3, 4), dtype=np.uint8)
        mask = np.zeros((2, 3), dtype=np.uint8)
        for wrong in (np.zeros((2, 2), dtype=np.uint8), mask.astype(float), image):
            with self.assertRaises(ValueError):
                compose_modified(image, image, wrong, mask, alpha_policy=AlphaPolicy.EDIT)
        with self.assertRaises(ValueError):
            compose_modified(image, image[:, :2], mask, mask, alpha_policy=AlphaPolicy.EDIT)
        with self.assertRaises(ValueError):
            compose_modified(image, image, mask, mask, alpha_policy="guess")
        for wrong in (image.astype(np.uint16), image[..., :3]):
            with self.assertRaises(ValueError):
                compose_modified(wrong, image, mask, mask, alpha_policy=AlphaPolicy.EDIT)
        for radius in (65, 1.5, True):
            with self.assertRaises(ValueError):
                protection_band(mask, radius)


class CanvasTests(unittest.TestCase):
    def test_native_grid_and_rgba_round_trip_without_resize(self):
        canvas = NativeCanvas(19, 13, 8)
        self.assertEqual(canvas.padded_size, (24, 16))
        image = np.arange(19 * 13 * 4, dtype=np.uint8).reshape(13, 19, 4)
        padded = canvas.pad(image)
        np.testing.assert_array_equal(padded[:13, :19], image)
        np.testing.assert_array_equal(padded[-1, -1], image[-1, -1])
        np.testing.assert_array_equal(canvas.crop(padded), image)
        self.assertEqual(NativeCanvas(1900, 1060, 8).padded_size, (1904, 1064))
        with self.assertRaises(ValueError):
            canvas.crop(image)
        with self.assertRaises(ValueError):
            NativeCanvas(True, 4, 8)


if __name__ == "__main__":
    unittest.main()
