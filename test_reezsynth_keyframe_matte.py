"""Native-pixel matte restoration, with no models or GPU usage."""
import unittest
from io import BytesIO

import numpy as np
from PIL import Image

from reezsynth_keyframe_matte import opaque_model_input,compose_matted_output
from reezsynth_keyframe_protection import AlphaPolicy,EditIntent
from reezsynth_comfy_qwen import QwenSettings,plan_qwen


class MatteTests(unittest.TestCase):
    def test_identity_preserves_every_alpha_level_and_hidden_rgb(self):
        rng = np.random.default_rng(123)
        drawing = rng.integers(0,256,(257,29,4),dtype=np.uint8)
        drawing[...,3] = np.arange(257,dtype=np.uint16)[:,None] % 256
        edit = np.full(drawing.shape[:2],255,dtype=np.uint8)
        protect = np.zeros_like(edit)
        for background in ((0,0,0),(255,255,255),(51,102,153)):
            with self.subTest(background=background):
                matte = opaque_model_input(drawing,background=background)
                result,qc = compose_matted_output(drawing,matte,matte,edit,protect,background=background)
                np.testing.assert_array_equal(result,drawing)
                self.assertEqual(qc.clipped_reconstruction_pixels,0)
                self.assertEqual(qc.protection.changed_pixels,0)
                self.assertFalse(np.shares_memory(result,drawing))

    def test_half_alpha_does_not_apply_background_or_alpha_twice(self):
        drawing = np.array([[[20,40,60,128]]],dtype=np.uint8)
        background = (255,255,255)
        matte = opaque_model_input(drawing,background=background)
        np.testing.assert_array_equal(matte,[[[137,147,157]]])
        raw = matte+10
        result,qc = compose_matted_output(drawing,raw,matte,np.array([[255]],dtype=np.uint8),
                                         np.array([[0]],dtype=np.uint8),background=background)
        np.testing.assert_array_equal(result,[[[40,60,80,128]]])
        self.assertEqual(qc.translucent_edit_pixels,1)
        soft,_ = compose_matted_output(drawing,raw,matte,np.array([[128]],dtype=np.uint8),
                                      np.array([[0]],dtype=np.uint8),background=background)
        np.testing.assert_array_equal(soft,[[[30,50,70,128]]])

    def test_opaque_full_edit_adopts_model_rgb_exactly(self):
        rng = np.random.default_rng(4)
        drawing = rng.integers(0,256,(5,9,4),dtype=np.uint8)
        drawing[...,3] = 255
        raw = rng.integers(0,256,(5,9,3),dtype=np.uint8)
        matte = opaque_model_input(drawing,background=(70,90,120))
        edit = np.full((5,9),255,dtype=np.uint8)
        result,qc = compose_matted_output(drawing,raw,matte,edit,np.zeros_like(edit),background=(70,90,120))
        np.testing.assert_array_equal(result[...,:3],raw)
        self.assertEqual(qc.clipped_reconstruction_pixels,0)

    def test_protection_no_edit_and_zero_alpha_remain_byte_exact(self):
        rng = np.random.default_rng(6)
        drawing = rng.integers(0,256,(137,19,4),dtype=np.uint8)
        drawing[:,0,3] = 0
        edit = rng.integers(0,256,(137,19),dtype=np.uint8)
        edit[:,1] = 0
        protection = np.zeros_like(edit)
        protection[:,2] = 1
        raw = rng.integers(0,256,(137,19,3),dtype=np.uint8)
        matte = opaque_model_input(drawing,background=(255,255,255))
        inputs = [a.copy() for a in (drawing,raw,matte,edit,protection)]
        result,qc = compose_matted_output(drawing,raw,matte,edit,protection,background=(255,255,255))
        np.testing.assert_array_equal(result[:,:3],drawing[:,:3])
        np.testing.assert_array_equal(result[...,3],drawing[...,3])
        self.assertEqual(qc.protection.protected_mismatches,0)
        self.assertEqual(qc.protection.alpha_changed_pixels,0)
        for before,after in zip(inputs,(drawing,raw,matte,edit,protection)):
            np.testing.assert_array_equal(before,after)
        stream = BytesIO()
        Image.fromarray(result).save(stream,format="PNG")
        stream.seek(0)
        np.testing.assert_array_equal(np.array(Image.open(stream)),result)

    def test_clipping_reports_eligible_pixels_once_before_soft_blend(self):
        drawing = np.array([[[100,100,100,1],[100,100,100,1],[100,100,100,0]]],dtype=np.uint8)
        matte = opaque_model_input(drawing,background=(255,255,255))
        raw = np.zeros((1,3,3),dtype=np.uint8)
        edit = np.array([[128,255,255]],dtype=np.uint8)
        protect = np.array([[0,1,0]],dtype=np.uint8)
        result,qc = compose_matted_output(drawing,raw,matte,edit,protect,background=(255,255,255))
        self.assertEqual(qc.clipped_reconstruction_pixels,1)
        self.assertEqual(qc.translucent_edit_pixels,1)
        np.testing.assert_array_equal(result[0,0],[50,50,50,1])
        np.testing.assert_array_equal(result[0,1:],drawing[0,1:])

    def test_wrong_baseline_dimensions_types_and_background_are_rejected(self):
        drawing = np.full((2,3,4),128,dtype=np.uint8)
        matte = opaque_model_input(drawing,background=(255,255,255))
        mask = np.zeros((2,3),dtype=np.uint8)
        bad = matte.copy()
        bad[0,0,0] ^= 1
        for raw,baseline,background in ((matte,bad,(255,255,255)),
                                       (matte[:1],matte,(255,255,255)),
                                       (matte.astype(np.float32),matte,(255,255,255)),
                                       (matte,matte,(0,0,0)),(matte,matte,(256,0,0))):
            with self.subTest(background=background),self.assertRaises(ValueError):
                compose_matted_output(drawing,raw,baseline,mask,mask,background=background)

    def test_planner_input_round_trip_restores_native_drawing(self):
        rng = np.random.default_rng(7)
        drawing = rng.integers(0,256,(17,19,4),dtype=np.uint8)
        source = np.full_like(drawing,255)
        edit = np.full((17,19),255,dtype=np.uint8)
        protect = np.zeros_like(edit)
        settings = QwenSettings("modify","Refine strokes",1,20,4,0.5,
                                intent=EditIntent.REFINE_STROKES,alpha_policy=AlphaPolicy.PRESERVE,
                                background=(96,96,96),allow_vision_preprocessing=True)
        plan = plan_qwen(settings,source,drawing=drawing,edit_mask=edit,protection_mask=protect)
        with Image.open(BytesIO(dict(plan.snapshots)["inference.png"])) as image:
            matte = np.array(image)[:17,:19].copy()
        result,qc = compose_matted_output(drawing,matte,matte,edit,protect,background=settings.background)
        np.testing.assert_array_equal(result,drawing)
        self.assertEqual(qc.protection.changed_pixels,0)


if __name__ == "__main__":
    unittest.main()
