"""Native interchange validation, mappings and confirmation-first GUI contracts."""
import ast
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from reezsynth_native_yaml import DEFAULTS, import_settings, export_project, read_native_yaml, write_native_yaml
from reezsynth_config import validate_render, validate_weights
from reezsynth_engines import FUOUM
from reezsynth_serialization import write_document
from tests.test_reezsynth_gui import GuiFixture


def native_document():
    data = copy.deepcopy(DEFAULTS)
    data['project'].update(content_dir='D:/source', style_path=['D:/keys/key001.png', 'D:/keys/key003.png'],
        style_indices=[0, 2], output_dir='D:/native-output')
    return data


class NativeYamlTests(unittest.TestCase):
    def test_defaults_and_independent_snapshots(self):
        settings, notes = import_settings(native_document())
        self.assertEqual(settings['render_options']['engine'], FUOUM)
        self.assertEqual(settings['render_options']['pyramidlevels'], 1)
        self.assertFalse(settings['render_options']['temporal_nnf'])
        self.assertFalse(settings['render_options']['sparse_features'])
        self.assertFalse(settings['render_options']['extrapass3x3'])
        self.assertTrue(any('NOT applied' in note for note in notes))
        settings['render_options']['patchsize'] = 9
        self.assertEqual(import_settings(native_document())[0]['render_options']['patchsize'], 7)

    def test_all_mapped_fields(self):
        data = native_document()
        data['precomputation'].update(flow_engine='NeuFlow', flow_model='neuflow_mixed', edge_method='PAGE')
        data['ebsynth_params'].update(patch_size=9, uniformity=12, backend='torch', vote_mode='plain',
            cost_function='ncc', search_vote_iters=8, patch_match_iters=2, extra_pass_3x3=True,
            stop_threshold=7, search_pruning_threshold=17, sparse_anchor_weight=3,
            edge_weight=4, image_weight=5, pos_weight=6, warp_weight=7)
        data['project']['force_recompute_edge'] = True
        data['pipeline'].update(pyramid_levels=8, use_temporal_nnf_propagation=True, use_sparse_feature_guide=True)
        data['blending'].update(poisson_solver='LSMR', poisson_maxiter=25, poisson_grad_weight_l=8, poisson_grad_weight_ab=2)
        settings, notes = import_settings(data)
        render = settings['render_options']
        self.assertEqual((render['fuoum_flow_engine'], render['fuoum_neuflow_model']), ('NeuFlow', 'neuflow_mixed'))
        self.assertEqual((render['patchsize'], render['fuoum_backend'], render['fuoum_cost_function']), (9, 'torch', 'ncc'))
        self.assertEqual(settings['guide_weights']['wrp_wgt'], 7)
        self.assertEqual(settings['blend_options']['fuoum_poisson_solver'], 'lsmr')
        self.assertFalse(settings['blend_options']['use_lsqr'])
        self.assertTrue(any('caches are not overwritten' in note for note in notes))

    def test_unsupported_reported(self):
        data = native_document()
        data['pipeline']['use_residual_transfer'] = False
        data['pipeline']['final_pass']['enabled'] = True
        data['pipeline']['future'] = 12
        data['future_section'] = {}
        _, notes = import_settings(data)
        text = '\n'.join(notes)
        for field in ('use_residual_transfer', 'final_pass', 'pipeline.future', 'future_section'):
            self.assertIn(field, text)

    def test_precision_reported(self):
        data = native_document()
        data['ebsynth_params']['image_weight'] = .123456789
        settings, notes = import_settings(data)
        self.assertEqual(settings['guide_weights']['img_wgt'], .123457)
        self.assertTrue(any('six decimal' in note for note in notes))

    def test_malformed_values_rejected(self):
        cases = [('ebsynth_params', 'patch_size', 4), ('ebsynth_params', 'uniformity', float('nan')),
            ('project', 'force_recompute_flow', 'false'), ('pipeline', 'pyramid_levels', -1),
            ('pipeline', 'alpha', 2), ('project', 'style_indices', [0, 0]),
            ('precomputation', 'flow_model', 'wrong')]
        for section, field, value in cases:
            data = native_document(); data[section][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                import_settings(data)
        with self.assertRaises(ValueError):
            import_settings({'format': 'ReEzSynth-Windows-GUI'})

    def test_safe_yaml(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'native.yaml'
            write_document(path, native_document())
            self.assertEqual(import_settings(read_native_yaml(path))[0]['guide_weights']['img_wgt'], 6)
            for text in ('project: {}\nproject: {}', 'a: &x [*x]', 'a: !!python/object/apply:os.system [echo unsafe]', 'a: 2026-09-26'):
                path.write_text(text, encoding='utf-8')
                with self.subTest(text=text), self.assertRaises(ValueError):
                    read_native_yaml(path)

    def test_exported_comments_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'native.yaml'
            data = native_document()
            write_native_yaml(path, data, ['NOT represented: custom edge guides', 'Two lines\nStill a comment'])
            self.assertIn('# NOT represented', path.read_text(encoding='utf-8'))
            self.assertEqual(read_native_yaml(path), data)
            self.assertFalse(path.with_suffix('.yaml.tmp').exists())

    def fixture(self, root):
        source, keys_dir = root / 'source', root / 'keys'
        source.mkdir(); keys_dir.mkdir()
        video, keys = {}, {}
        for n in (100, 101, 102):
            path = source / f'frame{n:03}.png'; Image.new('RGB', (128, 128)).save(path)
            video[n] = path
        for n in (100, 102):
            path = keys_dir / f'key{n:03}.png'; Image.new('RGB', (128, 128)).save(path)
            keys[n] = path
        return video, keys

    def test_export_ordinals_and_weight_normalization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); video, keys = self.fixture(root)
            render = validate_render(dict(engine=FUOUM, pyramidlevels=-1, fuoum_sparse_anchor_weight=8))
            weights = validate_weights(dict(key_wgt=2, img_wgt=10))
            data, notes = export_project(video, keys, {}, render, weights, {}, root / 'native-output')
            self.assertEqual(data['project']['style_indices'], [0, 2])
            self.assertEqual(data['pipeline']['pyramid_levels'], 32)
            self.assertTrue(any('fixed maximum of 32' in note for note in notes))
            self.assertEqual(data['ebsynth_params']['image_weight'], 5)
            self.assertEqual(data['ebsynth_params']['sparse_anchor_weight'], 4)
            self.assertEqual(import_settings(data)[0]['guide_weights']['key_wgt'], 1)
            self.assertTrue(any('divided' in note for note in notes))
            self.assertFalse((root / 'native-output').exists())
            self.assertFalse((root / 'native-output_cache').exists())

    def test_export_range_cache_and_order_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); video, keys = self.fixture(root)
            render = validate_render(dict(engine=FUOUM))
            (root / 'existing').mkdir()
            with self.assertRaisesRegex(ValueError, 'new native output'):
                export_project(video, keys, {}, render, {}, {}, root / 'existing')
            (root / 'fresh_cache').mkdir()
            with self.assertRaisesRegex(ValueError, 'cache folder already'):
                export_project(video, keys, {}, render, {}, {}, root / 'fresh')
            # A valid subrange with its own two keys is still not representable.
            keys[101] = keys[100]
            with self.assertRaisesRegex(ValueError, 'whole content folder'):
                export_project(video, keys, {'start': 100, 'end': 101, 'keyframes': [100, 101]}, render, {}, {}, root / 'out')
            (root / 'source' / 'frame103.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'contents changed'):
                export_project(video, keys, {}, render, {}, {}, root / 'out')

    def test_export_omissions_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); video, keys = self.fixture(root)
            render = validate_render(dict(engine=FUOUM, fuoum_bidirectional_flow=True,
                searchvote_schedule=[5], custom_edge_guides=True))
            _, notes = export_project(video, keys, {}, render, {}, {'only_mode': 'forward'}, root / 'out', context={'processing_size': [256, 256]})
            text = '\n'.join(notes)
            for name in ('fuoum_bidirectional_flow', 'searchvote_schedule', 'custom_edge_guides', 'processing resize', 'forward/reverse'):
                self.assertIn(name, text)

    def test_native_sort_disagreement_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); video, keys = self.fixture(root)
            replacement = video[101].with_name('Frame101.png')
            video[101].rename(replacement); video[101] = replacement
            with self.assertRaisesRegex(ValueError, 'frame ordering'):
                export_project(video, keys, {}, {'engine': FUOUM}, {}, {}, root / 'out')

    def test_one_key_native_project_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); video, keys = self.fixture(root)
            data, _ = export_project(video, {100: keys[100]}, {}, {'engine': FUOUM}, {}, {}, root / 'out')
            self.assertEqual(data['project']['style_indices'], [0])

    def test_transparent_styles_cannot_be_exported_to_alpha_discarding_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); video, keys = self.fixture(root)
            Image.new('RGBA', (128, 128), (0, 0, 0, 128)).save(keys[100])
            original = keys[100].read_bytes()
            for mode in ('Transparent artwork', 'Composite onto source'):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'discards style alpha'):
                    export_project(video, keys, {}, dict(engine=FUOUM, fuoum_alpha_mask_mode=mode),
                                   {}, {}, root / 'out')
                self.assertFalse((root / 'out').exists())
                self.assertFalse((root / 'out_cache').exists())
                self.assertEqual(keys[100].read_bytes(), original)

    def test_opaque_rgba_styles_remain_native_export_compatible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); video, keys = self.fixture(root)
            Image.new('RGBA', (128, 128), (0, 0, 0, 255)).save(keys[100])
            data, _ = export_project(video, keys, {}, dict(engine=FUOUM), {}, {}, root / 'out')
            self.assertEqual(data['project']['style_indices'], [0, 2])

    def test_schema_fields_match_pinned_checkout_when_available(self):
        path = Path(__file__).resolve().parents[1] / 'engine_sources/fuoum_reezsynth/ezsynth/config.py'
        if not path.is_file():
            self.skipTest('Pinned checkout is optional for dependency-light tests.')
        classes = {node.name: node for node in ast.parse(path.read_text()).body if isinstance(node, ast.ClassDef)}
        for section, name in [('project', 'ProjectConfig'), ('precomputation', 'PrecomputationConfig'),
            ('pipeline', 'PipelineConfig'), ('blending', 'BlendingConfig'), ('ebsynth_params', 'EbsynthParamsConfig'), ('debug', 'DebugConfig')]:
            fields = {node.target.id for node in classes[name].body if isinstance(node, ast.AnnAssign)}
            self.assertEqual(set(DEFAULTS[section]), fields)


class NativeYamlGuiTests(GuiFixture):
    def test_apply_preserves_inputs_queue_and_application(self):
        from reezsynth_native_yaml_controls import apply_import
        window = self.window()
        window.video_dir.setEditText('D:/existing-inputs')
        window.options.widgets['render']['fuoum_bidirectional_flow'].setChecked(True)
        before_dirs = window.options.snapshot('directories')
        before_app = window.options.application()
        before_group = window.grouped.selection()
        settings, _ = import_settings(native_document())
        with patch.object(window, 'run_rows') as run, patch.object(window.options, 'maybe_start'):
            apply_import(window, settings)
        self.assertEqual(window.options.snapshot('directories'), before_dirs)
        self.assertEqual(window.options.application(), before_app)
        self.assertEqual(window.grouped.selection(), before_group)
        self.assertEqual(window.options.render()['engine'], FUOUM)
        self.assertFalse(window.options.render()['fuoum_bidirectional_flow'])
        self.assertEqual(window.options.render()['pyramidlevels'], 1)
        self.assertFalse(window.options.auto_armed)
        self.assertFalse(window.loading_project)
        run.assert_not_called()

    def test_invalid_or_busy_import_does_not_mutate(self):
        from reezsynth_native_yaml_controls import apply_import
        window = self.window()
        before = window.options.snapshot('render')
        settings, _ = import_settings(native_document())
        settings['guide_weights']['key_wgt'] = 0
        with self.assertRaises(ValueError):
            apply_import(window, settings)
        self.assertEqual(window.options.snapshot('render'), before)
        window.busy = True
        try:
            with self.assertRaises(ValueError):
                apply_import(window, import_settings(native_document())[0])
        finally:
            window.busy = False
        self.assertEqual(window.options.snapshot('render'), before)

    def test_cancel_confirmation_keeps_state(self):
        from reezsynth_native_yaml_controls import import_native
        window = self.window()
        path = self.root / 'native.yaml'; write_document(path, native_document())
        before = window.options.snapshot('render')
        with patch('reezsynth_native_yaml_controls.QFileDialog.getOpenFileName', return_value=(str(path), '')), \
                patch('reezsynth_native_yaml_controls.confirm', return_value=False):
            import_native(window)
        self.assertEqual(window.options.snapshot('render'), before)

    def test_mid_apply_failure_restores_groups(self):
        from reezsynth_native_yaml_controls import apply_import
        window = self.window()
        before = {group: window.options.snapshot(group) for group in ('render', 'weights', 'grouped')}
        original = window.options.apply
        failed = False
        def apply(group, data, **kwargs):
            nonlocal failed
            if group == 'weights' and not failed:
                failed = True
                raise RuntimeError('simulated widget failure')
            return original(group, data, **kwargs)
        with patch.object(window.options, 'apply', side_effect=apply):
            with self.assertRaisesRegex(RuntimeError, 'simulated'):
                apply_import(window, import_settings(native_document())[0])
        for group, expected in before.items():
            self.assertEqual(window.options.snapshot(group), expected)
        self.assertFalse(window.loading_project)
        self.assertFalse(window.options.auto_armed)

    def test_export_cancel_preserves_document_and_state(self):
        from reezsynth_native_yaml_controls import export_native
        window = self.window()
        source, keys_dir = self.root / 'source', self.root / 'keys'
        source.mkdir(); keys_dir.mkdir()
        for n in (0, 1, 2):
            Image.new('RGB', (128, 128)).save(source / f'frame{n:03}.png')
        for n in (0, 2):
            Image.new('RGB', (128, 128)).save(keys_dir / f'key{n:03}.png')
        window.video_dir.setEditText(str(source)); window.keyframe_dir.setEditText(str(keys_dir))
        self.assertTrue(window.rebuild_queue())
        window.options.widgets['render']['engine'].setCurrentText(FUOUM)
        before = window.options.snapshot('render')
        document = self.root / 'native.yaml'; document.write_text('existing document', encoding='utf-8')
        with patch('reezsynth_native_yaml_controls.QFileDialog.getSaveFileName', return_value=(str(document), '')), \
                patch('reezsynth_native_yaml_controls.QInputDialog.getText', return_value=(str(self.root / 'new-out'), True)), \
                patch('reezsynth_native_yaml_controls.confirm', return_value=False):
            export_native(window)
        self.assertEqual(document.read_text(encoding='utf-8'), 'existing document')
        self.assertEqual(window.options.snapshot('render'), before)
        self.assertFalse((self.root / 'new-out').exists())
