"""CPU-only checks for the alternate-backend readiness diagnostic's oracle."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import diagnose_reezsynth_torch_backend as audit


class TorchBackendAuditTests(unittest.TestCase):
    def arrays(self, size=(19, 17), value=127, error=585225):
        return (np.full((*size[::-1], 3), value, np.uint8),
                np.full(size[::-1], error, np.float32),
                np.full((*size[::-1], 2), 4, np.int32))

    def test_constant_cost_oracle_covers_modulation_and_ncc(self):
        for modulation, cost, error in ((None, 'ssd', 585225), (255, 'ssd', 585225),
                                       (128, 'ssd', 293760), (0, 'ssd', 0), (0, 'ncc', 3)):
            with self.subTest(modulation=modulation, cost=cost):
                result = audit.evaluate_result(*self.arrays(error=error), modulation=modulation, cost=cost)
                self.assertTrue(result['passed'], result)

    def test_ignored_modulation_and_darkened_constant_are_failures(self):
        self.assertFalse(audit.evaluate_result(*self.arrays(), modulation=0)['passed'])
        self.assertFalse(audit.evaluate_result(*self.arrays(), modulation=128)['passed'])
        result = audit.evaluate_result(*self.arrays(value=19))
        self.assertFalse(result['checks']['constant_style_preserved'])
        self.assertEqual(result['max_constant_error'], 108)

    def test_retargeting_and_nonfinite_or_wrong_grid_errors(self):
        result = audit.evaluate_result(*self.arrays(size=(23, 21)), target_size=(23, 21))
        self.assertTrue(result['passed'])
        self.assertFalse(audit.evaluate_result(*self.arrays(), target_size=(23, 21))['passed'])
        result = audit.evaluate_result(*self.arrays(error=float('inf')))
        self.assertFalse(result['passed'])
        self.assertIsNone(result['mean_error'])
        json.dumps(result, allow_nan=False)

    def test_nnf_must_have_target_shape_and_valid_source_patch_centers(self):
        image, error, nnf = self.arrays()
        for invalid in (nnf[:1], nnf[..., :1], np.zeros_like(nnf), np.full_like(nnf, 18)):
            self.assertFalse(audit.evaluate_result(image, error, invalid)['checks']['valid_nnf'])

    def test_native_exceptions_are_retained_and_do_not_skip_remaining_cases(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # Minimal hashable runtime inventory; the renderer itself is mocked.
            (root / 'ezsynth/engines').mkdir(parents=True)
            (root / 'ezsynth/config.py').touch()
            (root / 'ezsynth/engines/synthesis_engine.py').touch()
            output = root / 'report.json'
            with patch.object(audit, 'prepare_runtime', return_value={'source': str(root)}), \
                 patch.object(audit, 'activate_fuoum'), \
                 patch.object(audit, 'CASES', (('retarget', {}), ('constant', {}))), \
                 patch.object(audit, 'render_case', side_effect=[RuntimeError('wrong grid'), {'passed': True}]):
                self.assertEqual(audit.child('torch', output), 1)
            report = json.loads(output.read_text())
            self.assertFalse(report['passed'])
            self.assertEqual(report['cases'][0]['exception'], 'wrong grid')
            self.assertTrue(report['cases'][1]['passed'])
            self.assertTrue(report['source_sha256'])


if __name__ == '__main__':
    unittest.main()
