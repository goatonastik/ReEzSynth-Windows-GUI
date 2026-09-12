"""Render metadata checks without loading engines, checkpoints or CUDA."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from reezsynth_engines import FUOUM, LEGACY, engine_revision, write_engine_manifest
from reezsynth_provenance import effective_settings


class EffectiveSettingsTests(unittest.TestCase):
    def test_defaults_normalization_and_inactive_legacy_fields(self):
        job = dict(quality='Preview', frames=[[0, 'a'], [1, 'b']],
                   render_options=dict(fuoum_cost_function='ncc', feather=7),
                   guide_weights=dict(key_wgt=2, img_wgt=8, mask_wgt=9))
        original = copy.deepcopy(job)
        result = effective_settings(job)
        self.assertEqual(result['render_options']['patchsize'], 5)
        self.assertEqual(result['normalized_guide_weights']['img_wgt'], 4)
        self.assertNotIn('mask_wgt', result['normalized_guide_weights'])
        self.assertNotIn('feather', result['render_options'])
        self.assertFalse(any(name.startswith('fuoum_') for name in result['render_options']))
        self.assertEqual(job, original)

    def test_fuoum_active_model_sparse_toggle_and_legacy_solver_migration(self):
        result = effective_settings(dict(type='grouped_video', frames=[[0, 'a'], [1, 'b']],
            render_options=dict(engine=FUOUM, fuoum_flow_engine='NeuFlow', sparse_features=False),
            blend_options=dict(use_lsqr=False, poisson_maxiter=13)))
        options = result['render_options']
        self.assertEqual(options['fuoum_neuflow_model'], 'neuflow_sintel')
        for field in ('flow_model', 'fuoum_raft_model', 'fuoum_sparse_anchor_weight'):
            self.assertNotIn(field, options)
        self.assertNotIn('sparse_anchor_weight', result['normalized_guide_weights'])
        self.assertEqual(result['blend_options']['fuoum_poisson_solver'], 'lsmr')
        self.assertEqual(result['blend_options']['poisson_maxiter'], 13)
        self.assertNotIn('use_lsqr', result['blend_options'])

    def test_solver_dependent_settings(self):
        job = dict(type='grouped_video', render_options=dict(engine=FUOUM),
                   blend_options=dict(fuoum_poisson_solver='amg'))
        self.assertEqual(effective_settings(job)['blend_options']['poisson_maxiter'], 100)
        job['blend_options']['fuoum_poisson_solver'] = 'disabled'
        self.assertEqual(effective_settings(job)['blend_options'],
                         dict(only_mode='none', fuoum_poisson_solver='disabled'))
        job['blend_options']['only_mode'] = 'forward'
        self.assertEqual(effective_settings(job)['blend_options'], dict(only_mode='forward'))
        job.update(render_options=dict(engine=LEGACY), blend_options=dict(poisson_maxiter=13))
        self.assertNotIn('poisson_maxiter', effective_settings(job)['blend_options'])

    def test_image_and_keyframe_copy_only_report_used_settings(self):
        result = effective_settings(dict(type='image_synthesis',
            render_options=dict(memory_efficient_raft=True),
            image_synthesis=dict(source_weight=8, key_weight=2,
                                 guides=[dict(source='a', target='b', weight=3)])))
        self.assertEqual(result['normalized_guide_weights'], [4, 1.5])
        self.assertNotIn('memory_efficient_raft', result['render_options'])
        self.assertNotIn('blend_options', result)
        result = effective_settings(dict(frames=[[0, 'a']], render_options=dict(do_mask=True, feather=7)))
        self.assertEqual(result['kind'], 'keyframe_copy')
        self.assertEqual(result['render_options'], dict(do_mask=True, feather=7))


class ManifestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='reezsynth_manifest_test_')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.output = self.root / 'output'
        self.source.mkdir()
        self.output.mkdir()

    def asset(self, relative, data=b'fixture'):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def manifest(self, options, **extra):
        engine = options.get('engine', LEGACY)
        job = dict(output=str(self.output), frames=[[0, 'a'], [1, 'b']], render_options=options,
                   engine_runtime=dict(engine=engine, revision=engine_revision(engine),
                                       source=str(self.source), python='worker.exe'))
        job.update(extra)
        with contextlib.redirect_stdout(io.StringIO()):
            result = write_engine_manifest(job)
        self.assertEqual(result, json.loads((self.output / 'engine_manifest.json').read_text(encoding='utf-8')))
        self.assertEqual(result['version'], 2)
        return result

    def test_selected_checkpoint_for_each_legacy_architecture(self):
        for arch, model, relative in (
            ('RAFT', 'kitti', 'models/raft-kitti.pth'),
            ('EF_RAFT', 'ours_sintel', 'ef_raft_models/ours_sintel.pth'),
            ('FLOW_DIFF', 'FlowDiffuser-things', 'flow_diffusion_models/FlowDiffuser-things.pth')):
            with self.subTest(architecture=arch):
                relative = 'ezsynth/utils/flow_utils/' + relative
                self.asset(relative, arch.encode())
                result = self.manifest(dict(flow_arch=arch, flow_model=model))
                self.assertEqual(result['source_sha256'][relative], hashlib.sha256(arch.encode()).hexdigest())
                self.assertEqual([name for name in result['source_sha256'] if name.endswith('.pth')], [relative])

    def test_selected_fuoum_neuflow_checkpoint(self):
        relative = 'models/neuflow/neuflow_mixed.pth'
        self.asset(relative)
        result = self.manifest(dict(engine=FUOUM, fuoum_flow_engine='NeuFlow', fuoum_neuflow_model='neuflow_mixed'))
        self.assertIn(relative, result['source_sha256'])
        self.assertEqual(result['effective_settings']['render_options']['fuoum_neuflow_model'], 'neuflow_mixed')

    def test_flowdiffuser_manifest_includes_checkpoint_and_offline_backbones(self):
        names = ('FlowDiffuser-things.pth', 'twins_svt_large.pth', 'twins_svt_small.pth')
        for name in names:
            self.asset('ezsynth/utils/flow_utils/flow_diffusion_models/' + name, name.encode())
        result = self.manifest(dict(flow_arch='FLOW_DIFF', flow_model='FlowDiffuser-things'))
        recorded = {Path(name).name for name in result['source_sha256'] if name.endswith('.pth')}
        self.assertEqual(recorded, set(names))

    def test_compiled_extension_binary_and_adapter_hashes_without_torch_import(self):
        binary = self.asset('custom/alt_cuda_corr.pyd', b'custom-build')
        with patch.dict(sys.modules, {'torch': None, 'alt_cuda_corr': SimpleNamespace(__file__=str(binary))}):
            result = self.manifest(dict(memory_efficient_raft=True))
        self.assertEqual(result['runtime_components']['alt_cuda_corr'],
                         dict(available=True, path=str(binary.resolve()), sha256=hashlib.sha256(b'custom-build').hexdigest()))
        self.assertIn('reezsynth_raft.py', result['adapter_sha256'])
        self.assertIn('reezsynth_provenance.py', result['adapter_sha256'])

    def test_images_and_single_frame_copies_do_not_hash_unused_flow(self):
        self.asset('ezsynth/utils/flow_utils/models/raft-sintel.pth')
        for extra in (dict(type='image_synthesis'), dict(frames=[[0, 'a']])):
            with self.subTest(extra=extra):
                result = self.manifest(dict(memory_efficient_raft=True), **extra)
                self.assertNotIn('alt_cuda_corr', result['runtime_components'])
                self.assertFalse(any(name.endswith('.pth') for name in result['source_sha256']))


if __name__ == '__main__':
    unittest.main()
