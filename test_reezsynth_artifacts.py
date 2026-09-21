"""Auxiliary output indexing, preservation, failure and GUI persistence tests."""
import contextlib
import io
import itertools
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import test_reezsynth_render_adapter as adapter
from test_reezsynth_grouped import upstream_engine
from test_reezsynth_lifecycle import LifecycleFixture, gui
from reezsynth_artifacts import artifact_records, save_artifacts, validate_exports
from reezsynth_sequence import DiskSequence, array_sequence, frame_storage
from reezsynth_video_plan import plan_grouped_video


class MappingTests(unittest.TestCase):
    def test_matches_live_upstream_result_order_and_boundary_trimming(self):
        captured = {}
        Engine = upstream_engine(captured)
        ns = Engine.run_sequences_full.__globals__
        ns['get_flow'] = lambda images, raft, step, forward, i: np.full((2, 2, 3), min(i, i + step) + 10, np.uint8)
        ns['flow_to_image'] = lambda value, **kwargs: value
        def aligned_blend(images, forward, backward, errors_f, errors_b, flows, cfg):
            maps = array_sequence(errors_f[:1])
            maps.extend(errors_f[:-1])
            result = forward[:-1]
            if not cfg.skip_blend_style_last:
                result.append(backward[-1])
            return result, maps, flows
        ns['run_blend'] = aligned_blend
        frames = [np.full((2, 2, 3), i + 10, np.uint8) for i in range(6)]
        with contextlib.redirect_stdout(io.StringIO()):
            for length in range(1, 7):
                for size in range(1, length + 1):
                    for keys in itertools.combinations(range(length), size):
                        for mode in ('none', 'forward', 'reverse'):
                            cfg = types.SimpleNamespace(only_mode=mode, do_mask=False,
                                edg_wgt=1, img_wgt=1, pos_wgt=1, wrp_wgt=1)
                            runner = Engine(cfg=cfg, img_frs_seq=frames[:length],
                                style_frs=[frames[i] for i in keys], style_idxes=list(keys))
                            runner.eb.run = lambda style, guides: (style, guides[1][1][:, :, 0].astype(np.float32))
                            _, maps, flows = runner.run_sequences_full(return_flow=True)
                            records = artifact_records(list(range(10, 10 + length)), [k + 10 for k in keys], mode)
                            self.assertEqual(len(records), len(maps), (length, keys, mode))
                            self.assertEqual(len(records), len(flows))
                            for record, values, flow in zip(records, maps, flows):
                                self.assertTrue(np.all(flow == record['flow_from']))
                                # The mock blender returns forward-pass errors as its maps.
                                target = record.get('error_frame', record.get('forward_error_frame'))
                                self.assertTrue(np.all(values == target), (record, values))

    def test_blend_artifacts_label_boundary_offset_and_interior_same_frame(self):
        records = artifact_records([10, 11, 12, 13], [10, 13])
        self.assertEqual(
            [(r['forward_error_frame'], r['backward_error_frame']) for r in records],
            [(11, 10), (11, 11), (12, 12)],
        )

    def test_multisegment_assembly_keeps_boundaries_and_final_append(self):
        Engine = upstream_engine({})
        ns = Engine.run_sequences_full.__globals__
        ns['get_flow'] = lambda *args: np.zeros((2, 3, 2), np.float32)
        ns['flow_to_image'] = lambda value, **kwargs: value

        def aligned_blend(images, forward, backward, errors_f, errors_b, flows, cfg):
            maps = array_sequence(errors_f[:1])
            maps.extend(errors_f[:-1])
            result = forward[:-1]
            if not cfg.skip_blend_style_last:
                result.append(backward[-1])
            return result, maps, flows

        ns['run_blend'] = aligned_blend
        frames = [np.full((2, 3, 3), i, np.uint8) for i in range(5)]
        cfg = types.SimpleNamespace(only_mode='none', do_mask=False,
                                    edg_wgt=1, img_wgt=1, pos_wgt=1, wrp_wgt=1)
        runner = Engine(cfg=cfg, img_frs_seq=frames,
                        style_frs=[frames[i] + 100 for i in (0, 2, 4)],
                        style_idxes=[0, 2, 4])
        runner.eb.run = lambda style, guides: (
            style, guides[1][1][:, :, 0].astype(np.float32))
        with contextlib.redirect_stdout(io.StringIO()):
            outputs, maps, _ = runner.run_sequences_full(return_flow=True)
        self.assertEqual([int(value[0, 0, 0]) for value in outputs],
                         [100, 100, 102, 102, 104])
        self.assertEqual([int(value[0, 0]) for value in maps], [1, 1, 3, 3])
        records = artifact_records(list(range(5)), [0, 2, 4])
        self.assertEqual([(r['forward_error_frame'], r['backward_error_frame'])
                          for r in records], [(1, 0), (1, 1), (3, 2), (3, 3)])

    def test_rejects_unknown_or_nonboolean_settings(self):
        for data in ({'maps': 1}, {'raw_flow': True}, []):
            with self.assertRaises(ValueError):
                validate_exports(data)


class LegacyInteriorAlignmentTests(unittest.TestCase):
    @staticmethod
    def _inputs(frame_count=4):
        width = 6
        images = [np.full((2, width, 3), i, np.uint8) for i in range(frame_count)]
        forward = [np.full((2, width, 3), 10 + i, np.uint8) for i in range(frame_count)]
        backward = [np.full((2, width, 3), 100 + i, np.uint8) for i in range(frame_count)]
        alternating = np.tile([0.0, 9.0], (2, width // 2)).astype(np.float32)
        inverse = np.tile([9.0, 0.0], (2, width // 2)).astype(np.float32)
        errors_f = [alternating, inverse, alternating][:frame_count - 1]
        errors_b = [np.full((2, width), 5.0, np.float32) for _ in range(frame_count - 1)]
        flows = []
        for _ in range(frame_count - 1):
            flow = np.zeros((2, width, 2), np.float32)
            flow[..., 0] = 1.0
            flows.append(flow)
        return images, forward, backward, errors_f, errors_b, flows

    @staticmethod
    def _run(inputs, preservation='Current behavior'):
        from ezsynth import aux_run
        from ezsynth.utils.blend.blender import Blend

        captured = {}

        class ConsumerBlend(Blend):
            def _hist_blend(self, forward, backward, masks):
                captured['consumers'] = [
                    (int(forward[i][0, 0, 0]), int(backward[i][0, 0, 0]),
                     np.asarray(mask).copy())
                    for i, mask in enumerate(masks)
                ]
                return array_sequence(np.asarray(value).copy() for value in forward[:len(masks)])

            def _reconstruct(self, forward, backward, masks, hist_blends):
                return array_sequence(
                    np.where(np.asarray(mask)[..., None] == 0, forward[i], backward[i])
                    for i, mask in enumerate(masks)
                )

        cfg = types.SimpleNamespace(
            get_blender_cfg=lambda: dict(use_gpu=False, use_lsqr=False,
                                         use_poisson_cupy=False, poisson_maxiter=None),
            skip_blend_style_last=False,
            keyframe_preservation=preservation,
        )
        with patch.object(aux_run, 'Blend', ConsumerBlend), \
                contextlib.redirect_stdout(io.StringIO()):
            outputs, masks, returned_flows = aux_run.run_blend(*inputs, cfg)
        return outputs, masks, returned_flows, captured

    def test_real_selection_uses_same_frame_errors_and_actual_style_consumers(self):
        outputs, masks, flows, captured = self._run(self._inputs())
        np.testing.assert_array_equal(masks[0][0], [255, 0, 255, 0, 255, 255])
        np.testing.assert_array_equal(masks[1][0], [0, 1, 0, 1, 0, 1])
        np.testing.assert_array_equal(masks[2][0], [1, 0, 1, 0, 1, 0])
        self.assertEqual([(a, b) for a, b, _ in captured['consumers']],
                         [(10, 100), (11, 101), (12, 102)])
        self.assertEqual(outputs[1][0, :, 0].tolist(), [11, 101, 11, 101, 11, 101])
        self.assertEqual(outputs[2][0, :, 0].tolist(), [102, 12, 102, 12, 102, 12])
        self.assertEqual(int(outputs[-1][0, 0, 0]), 103)

    def test_two_frame_segment_preserves_legacy_boundary_mask_and_output(self):
        inputs = self._inputs(2)
        outputs, masks, returned_flows, captured = self._run(inputs)
        self.assertIs(returned_flows, inputs[-1])
        self.assertEqual(len(masks), 1)
        np.testing.assert_array_equal(masks[0][0], [255, 0, 255, 0, 255, 255])
        self.assertEqual(outputs[0][0, :, 0].tolist(), [100, 10, 100, 10, 100, 100])
        self.assertEqual(int(outputs[1][0, 0, 0]), 101)
        self.assertEqual(captured['consumers'][0][:2], (10, 100))

    def test_real_blend_dispatches_transition_aware_policy_after_reconstruction(self):
        from ezsynth import aux_run

        inputs = self._inputs()
        with patch.object(aux_run, 'apply_transition_aware_handoff',
                          wraps=aux_run.apply_transition_aware_handoff) as handoff:
            transitioned, _, _, _ = self._run(inputs, 'Transition-aware')
        handoff.assert_called_once()
        called_blends, called_forward, called_backward = handoff.call_args.args[:3]
        self.assertIs(called_blends, transitioned)
        self.assertIs(called_forward, inputs[1])
        self.assertIs(called_backward, inputs[2])
        baseline, _, _, _ = self._run(inputs)
        self.assertFalse(np.array_equal(transitioned[1], baseline[1]))
        self.assertFalse(np.array_equal(transitioned[2], baseline[2]))

    def test_disk_backed_alignment_uses_the_same_indices(self):
        with tempfile.TemporaryDirectory(prefix='.legacy-alignment-', dir=Path.cwd()) as directory:
            job = {'output': directory, 'render_options': {'stream_frames': True}}
            with frame_storage(job):
                inputs = tuple(array_sequence(values) for values in self._inputs())
                outputs, masks, _, _ = self._run(inputs)
                self.assertIsInstance(masks, DiskSequence)
                np.testing.assert_array_equal(masks[1][0], [0, 1, 0, 1, 0, 1])
                np.testing.assert_array_equal(masks[2][0], [1, 0, 1, 0, 1, 0])
                self.assertEqual(outputs[1][0, :, 0].tolist(), [11, 101, 11, 101, 11, 101])

    def test_rgb_and_rgba_pass_origins_keep_their_seed_semantics(self):
        from ezsynth import aux_run
        from ezsynth.aux_classes import RunConfig
        from ezsynth.sequences import EasySequence
        import reezsynth_alpha

        images = [np.full((2, 3, 3), i, np.uint8) for i in range(3)]
        edges = [np.zeros((2, 3), np.uint8) for _ in images]
        seq = EasySequence(0, 2, EasySequence.MODE_BLN, [0, 1])
        cfg = RunConfig(use_gpu=False, use_lsqr=False, use_poisson_cupy=False)
        seen_warp_seeds, synthesis_calls = [], []

        def warped(stylized, *args):
            seen_warp_seeds.append(np.asarray(stylized[-1]).copy())
            return np.asarray(stylized[-1])

        def synthesize(style, image, edge, eb, weights):
            synthesis_calls.append((style.copy(), image.copy()))
            return np.full_like(style, 77 + int(image[0, 0, 0]), dtype=np.uint8), np.zeros((2, 3))

        eb = types.SimpleNamespace(run=lambda style, guides: (
            np.asarray(guides[3][1]).copy(), np.zeros((2, 3), np.float32)))
        flow = types.SimpleNamespace(_compute_flow=lambda a, b: np.zeros((2, 3, 2), np.float32))
        rgb = np.full((2, 3, 3), 21, np.uint8)
        rgba_left = np.full((2, 3, 4), 31, np.uint8)
        rgba_right = np.full((2, 3, 4), 41, np.uint8)
        with patch.object(aux_run, 'get_warped_img', warped), \
                patch.object(reezsynth_alpha, 'synthesize_keyframe', synthesize), \
                contextlib.redirect_stdout(io.StringIO()):
            rgb_frames, _, _ = aux_run.run_a_pass(
                seq, EasySequence.MODE_FWD, images, rgb, edges, cfg, flow, eb)
            rgba_fwd, _, _ = aux_run.run_a_pass(
                seq, EasySequence.MODE_FWD, images, rgba_left, edges, cfg, flow, eb)
            rgba_bwd, _, _ = aux_run.run_a_pass(
                seq, EasySequence.MODE_REV, images, rgba_right, edges, cfg, flow, eb)
        np.testing.assert_array_equal(rgb_frames[0], rgb)
        self.assertEqual(len(synthesis_calls), 2)
        self.assertTrue(np.all(rgba_fwd[0] == 77))
        self.assertTrue(np.all(rgba_bwd[-1] == 79))
        np.testing.assert_array_equal(seen_warp_seeds[0], rgb)
        self.assertTrue(np.all(seen_warp_seeds[2] == 77))
        self.assertTrue(np.all(seen_warp_seeds[4] == 79))


class KeyframePreservationTests(unittest.TestCase):
    def test_current_mode_leaves_completed_sequence_unchanged_and_exact_mode_pins_keys(self):
        Engine = upstream_engine({})
        namespace = Engine.run_sequences_full.__globals__
        original = namespace['run_scratch']
        missing = object()
        original_mask_composite = namespace.get('apply_masked_back_seq', missing)
        frames = [np.full((2, 3, 3), index, np.uint8) for index in range(5)]
        styles = [np.full((2, 3, 3), value, np.uint8) for value in (100, 120, 140)]

        def drifted(seq, *args):
            count = seq.fr_end_idx - seq.fr_start_idx + 1
            if args[3].skip_blend_style_last:
                count -= 1
            values = array_sequence(np.full((2, 3, 3), 9, np.uint8) for _ in range(count))
            auxiliaries = array_sequence(np.zeros((2, 3), np.float32) for _ in range(count))
            return values, auxiliaries, auxiliaries

        try:
            namespace['run_scratch'] = drifted
            outputs = {}
            mask_inputs = []
            for mode in ('Current behavior', 'Exact output', 'Transition-aware'):
                masked = mode != 'Current behavior'
                cfg = types.SimpleNamespace(only_mode='none', do_mask=masked, pre_mask=False, feather=0,
                    keyframe_preservation=mode)
                runner = Engine(cfg=cfg, img_frs_seq=frames, style_frs=styles,
                                style_idxes=[0, 2, 4])
                runner.msk_frs_seq = [np.full((2, 3), 255, np.uint8) for _ in frames]
                if masked:
                    def composite_after_pinning(images, results, masks, feather):
                        mask_inputs.extend(np.asarray(frame).copy() for frame in results)
                        return array_sequence(np.asarray(frame) + 1 for frame in results)
                    namespace['apply_masked_back_seq'] = composite_after_pinning
                with contextlib.redirect_stdout(io.StringIO()):
                    outputs[mode], _ = runner.run_sequences()
        finally:
            namespace['run_scratch'] = original
            if original_mask_composite is missing:
                namespace.pop('apply_masked_back_seq', None)
            else:
                namespace['apply_masked_back_seq'] = original_mask_composite

        self.assertEqual([int(frame[0, 0, 0]) for frame in outputs['Current behavior']],
                         [9, 9, 9, 9, 9])
        self.assertEqual([int(frame[0, 0, 0]) for frame in mask_inputs],
                         [100, 9, 120, 9, 140] * 2)
        self.assertEqual([int(frame[0, 0, 0]) for frame in outputs['Exact output']],
                         [101, 10, 121, 10, 141])
        self.assertEqual([int(frame[0, 0, 0]) for frame in outputs['Transition-aware']],
                         [101, 10, 121, 10, 141])

    def test_transition_handoff_favors_motion_propagated_candidates_for_two_frames(self):
        from ezsynth.aux_run import apply_transition_aware_handoff

        base = array_sequence(np.full((1, 1, 3), 50, np.uint8) for _ in range(6))
        forward = array_sequence(np.full((1, 1, 3), 10 + index, np.uint8) for index in range(6))
        backward = array_sequence(np.full((1, 1, 3), 100 + index, np.uint8) for index in range(6))
        result = apply_transition_aware_handoff(base, forward, backward)
        self.assertEqual([int(frame[0, 0, 0]) for frame in result],
                         [50, 24, 37, 68, 86, 50])

    def test_transition_handoff_blends_rgba_in_premultiplied_space(self):
        from ezsynth.aux_run import _weighted_transition

        transparent_red = np.array([[[0, 0, 255, 0]]], np.uint8)
        opaque_blue = np.array([[[255, 0, 0, 255]]], np.uint8)
        result = _weighted_transition(transparent_red, opaque_blue, transparent_red,
                                      2 / 3, 0)
        self.assertEqual(result[0, 0].tolist(), [255, 0, 0, 170])


class ExportAdapterTests(unittest.TestCase):
    setUp = adapter.RenderAdapterTests.setUp
    run_job = adapter.RenderAdapterTests.run_job
    fake_engine = adapter.RenderAdapterTests.fake_engine

    def test_numerical_maps_are_lossless_and_manifest_distinguishes_blending(self):
        records = artifact_records([10, 11, 12], [10, 12])
        values = [np.full((128, 128), 1.234567, np.float32)] * 2
        flows = [np.full((128, 128, 3), 42, np.uint8)] * 2
        save_artifacts(self.output, {'maps': True, 'flow': True}, records, values, flows)
        root = self.output / 'auxiliary'
        manifest = json.loads((root / 'manifest.json').read_text())
        entry = manifest['artifacts'][0]
        self.assertEqual(entry['map_kind'], 'selection_mask')
        self.assertNotIn('error_frame', entry)
        np.testing.assert_array_equal(np.load(root / entry['selection_mask']['file'], allow_pickle=False), values[0])
        self.assertTrue((root / entry['flow']['file']).exists())

    def test_requested_export_failure_prevents_completion_marker(self):
        captured = self.fake_engine()
        engine = sys.modules['ezsynth.main_ez'].EzsynthBase
        def full(runner, return_flow):
            results, _ = runner.run_sequences()
            return results, [], []
        engine.run_sequences_full = full
        self.job['exports'] = {'maps': True}
        with self.assertRaisesRegex(RuntimeError, 'auxiliary maps'):
            self.run_job()
        self.assertFalse((self.output / 'COMPLETE.txt').exists())

    def test_grouped_and_independent_exports_reach_full_api(self):
        self.fake_engine()
        engine = sys.modules['ezsynth.main_ez'].EzsynthBase
        def full(runner, return_flow):
            runner.eb.run()
            if len(runner.frames) > 2:
                for _ in range(3):
                    runner.eb.run()
            count = len(runner.frames) - 1
            return runner.frames, [np.full((128, 128), 12.5, np.float32)] * count, [np.zeros((128, 128, 3), np.uint8)] * count if return_flow else []
        engine.run_sequences_full = full
        for grouped in (False, True):
            if grouped:
                self.job.update(plan_grouped_video({i: self.frames[0][1] for i in range(10, 13)},
                                                   {10: self.job['style'], 12: self.job['style']}))
            self.job['exports'] = {'maps': True, 'flow': True}
            self.run_job()
            manifest = json.loads((self.output / 'auxiliary/manifest.json').read_text())
            self.assertEqual(manifest['artifacts'][0]['map_kind'], 'selection_mask' if grouped else 'synthesis_error')
            self.assertTrue((self.output / 'COMPLETE.txt').exists())

    def test_single_frame_writes_empty_manifest_without_engine(self):
        self.job['frames'] = self.frames[:1]
        self.job['exports'] = {'maps': True, 'flow': True}
        with patch.dict(sys.modules, {'torch': None, 'ezsynth.main_ez': None}):
            self.run_job()
        manifest = json.loads((self.output / 'auxiliary/manifest.json').read_text())
        self.assertEqual(manifest['artifacts'], [])
        self.assertTrue((self.output / 'COMPLETE.txt').exists())

    def test_nonfinite_or_wrong_flow_format_is_rejected(self):
        records = artifact_records([0, 1], [0])
        for values in (np.full((2, 2), np.nan), np.ones((2, 2), np.float32)):
            with self.assertRaises(RuntimeError):
                save_artifacts(self.output, {'flow': True}, records, [], [values])

    def test_numerical_flow_reaches_worker_without_visualization_api(self):
        self.fake_engine()
        self.job['exports'] = {'flow_vectors': True}
        self.run_job()
        root = self.output / 'flow_vectors'
        manifest = json.loads((root / 'manifest.json').read_text())
        self.assertEqual(manifest['units'], 'processed-resolution pixels')
        self.assertEqual(len(manifest['artifacts']), 1)
        item = manifest['artifacts'][0]
        self.assertEqual((item['flow_from'], item['flow_to'], item['grid_frame']), (0, 1, 0))
        np.testing.assert_array_equal(np.load(root / item['file']), np.zeros((128, 128, 2), np.float32))

    def test_numerical_flow_preserves_values_and_deduplicates_each_direction(self):
        from reezsynth_artifacts import FlowVectorWriter
        writer = FlowVectorWriter(self.output, True)
        forward = np.full((2, 3, 2), 1.234567, np.float32)
        reverse = np.full((2, 3, 2), -2.345678, np.float64)
        writer.add(10, 11, forward)
        writer.add(10, 11, forward)
        writer.add(11, 10, reverse)
        writer.finish()
        self.assertEqual(len(writer.records), 2)
        np.testing.assert_array_equal(np.load(writer.root / '10_to_11.npy'), forward)
        np.testing.assert_array_equal(np.load(writer.root / '11_to_10.npy'), reverse)
        with self.assertRaisesRegex(RuntimeError, 'finite'):
            writer.add(11, 12, np.full((2, 3, 2), np.nan))


class ExportGuiTests(LifecycleFixture):
    def test_preset_project_legacy_and_job_serialization(self):
        w = self.w
        self.assertEqual(w.options.snapshot('render')['exports'], {'maps': False, 'flow': False, 'flow_vectors': False})
        w.options.export_widgets['maps'].setChecked(True)
        w.options.export_widgets['flow'].setChecked(True)
        w.options.export_widgets['flow_vectors'].setChecked(True)
        preset = w.options.snapshot('render')
        w.project_file = self.root / 'project.json'
        w.save_project()
        data = json.loads(w.project_file.read_text())
        self.assertEqual(data['exports'], {'maps': True, 'flow': True, 'flow_vectors': True})
        for legacy in (False, True):
            if legacy:
                data.pop('exports')
                w.project_file.write_text(json.dumps(data))
            with patch.object(gui.QFileDialog, 'getOpenFileName', return_value=(str(w.project_file), '')):
                w.open_project()
            self.assertEqual(w.options.export_widgets['maps'].isChecked(), not legacy)
        w.options.apply('render', preset)
        self.run_queue()
        self.until(lambda: not w.busy)
        for path in w.batch.rglob('job.json'):
            self.assertEqual(json.loads(path.read_text())['exports'], {'maps': True, 'flow': True, 'flow_vectors': True})


if __name__ == '__main__':
    unittest.main(verbosity=2)
