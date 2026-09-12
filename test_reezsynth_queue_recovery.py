import json
from pathlib import Path
import tempfile
import unittest

from reezsynth_queue_recovery import (audit_journal, create_journal, input_changes,
                                      snapshot_inputs, update_journal)


class QueueRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reezsynth recovery ')
        self.addCleanup(self.temp.cleanup)
        self.batch = Path(self.temp.name).resolve()
        self.input = self.batch / 'input.png'
        self.input.write_bytes(b'input')
        self.output = self.batch / 'out'
        self.output.mkdir()
        self.job_path = self.output / 'job.json'
        self.job = dict(key=0, style=str(self.input), frames=[[0, str(self.input)]],
                        output=str(self.output), padding=3, quality='Preview')
        self.job_path.write_text(json.dumps(self.job), encoding='utf-8')
        self.row = {'key': 0, 'label': 'Keyframe 0'}
        self.record = dict(job_path=self.job_path, output=self.output, key=0,
                           weight=1, python='python', row=self.row)

    def test_input_snapshot_detects_changed_and_missing_files(self):
        snapshot = snapshot_inputs(self.job, self.job_path)
        self.assertEqual(input_changes(snapshot), [])
        self.input.write_bytes(b'changed input')
        self.assertEqual(input_changes(snapshot), [str(self.input)])
        self.input.unlink()
        self.assertEqual(input_changes(snapshot), [str(self.input)])

    def test_atomic_journal_tracks_state_and_completed_marker(self):
        path = create_journal(self.batch, [self.record], 'shared', 'reezsynth_shared_worker.py')
        update_journal(path, self.job_path, 'running')
        self.assertEqual(audit_journal(path)['entries'][0]['entry']['state'], 'running')
        (self.output / 'COMPLETE.txt').write_text('done', encoding='utf-8')
        audited = audit_journal(path)['entries'][0]
        self.assertTrue(audited['complete'])
        self.assertFalse(audited['recoverable'])
        update_journal(path, self.job_path, 'complete', overall='complete')
        self.assertEqual(audit_journal(path)['data']['state'], 'complete')

    def test_partial_outputs_are_preserved_and_classified(self):
        path = create_journal(self.batch, [self.record], 'isolated', 'reezsynth_jobs.py')
        (self.output / '100.png').write_bytes(b'partial')
        audited = audit_journal(path)['entries'][0]
        self.assertTrue(audited['partial'])
        self.assertTrue(audited['recoverable'])
        self.assertEqual((self.output / '100.png').read_bytes(), b'partial')

    def test_job_or_input_changes_block_recovery(self):
        path = create_journal(self.batch, [self.record], 'parallel', 'reezsynth_jobs.py', 2)
        self.input.write_bytes(b'changed')
        audited = audit_journal(path)['entries'][0]
        self.assertFalse(audited['recoverable'])
        self.assertIn(str(self.input), audited['changed'])
        self.job_path.write_text('{}', encoding='utf-8')
        audited = audit_journal(path)['entries'][0]
        self.assertIn(str(self.job_path), audited['changed'])

    def test_journal_rejects_paths_outside_batch(self):
        outside = self.batch.parent / f'{self.batch.name}-outside-job.json'
        outside.write_text(json.dumps(self.job), encoding='utf-8')
        self.addCleanup(outside.unlink)
        record = dict(self.record, job_path=outside)
        with self.assertRaisesRegex(ValueError, 'inside the batch'):
            create_journal(self.batch, [record], 'shared', 'worker.py')
        path = create_journal(self.batch, [self.record], 'shared', 'worker.py')
        data = json.loads(path.read_text(encoding='utf-8'))
        data['entries'][0]['job'] = '..\\' + outside.name
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            audit_journal(path)


if __name__ == '__main__':
    unittest.main()
