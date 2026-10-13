"""Unit tests for the direct-CLI benchmark setup; no renderer or GPU."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import reezsynth_cli_benchmark as benchmark


class CliBenchmarkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="reezsynth_cli_benchmark_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_latest_completed_job_uses_final_complete_record(self):
        first = self.root / "first"
        final = self.root / "final"
        first.mkdir()
        final.mkdir()
        (first / "job.json").write_text("{}", encoding="utf-8")
        (final / "job.json").write_text("{}", encoding="utf-8")
        log = self.root / "session.log"
        log.write_text("[Key 1] COMPLETE: keyframe 1, 2 frames -> " + str(first) + "\n"
                       "[Key 2] COMPLETE: keyframe 2, 2 frames -> " + str(final) + "\n", encoding="utf-8")
        self.assertEqual(benchmark.latest_completed_job(log), (final / "job.json").resolve())

    def test_copy_preserves_settings_and_reserves_new_sibling(self):
        original = self.root / "out_081"
        original.mkdir()
        source = original / "job.json"
        source_data = {"key": 81, "output": str(original), "quality": "Standard",
                       "processing_size": [1920, 1080], "guide_weights": {"img_wgt": 6}}
        source.write_text(json.dumps(source_data), encoding="utf-8")
        destination = benchmark.benchmark_destination(original)
        copied, copied_data = benchmark.copy_benchmark_job(source, destination)
        self.assertEqual(destination.name, "out_081_cli_benchmark_001")
        self.assertEqual(copied, destination / "job.json")
        self.assertEqual(copied_data["output"], str(destination.resolve()))
        self.assertEqual({key: value for key, value in copied_data.items() if key != "output"},
                         {key: value for key, value in source_data.items() if key != "output"})
        self.assertEqual(json.loads(source.read_text(encoding="utf-8")), source_data)
        self.assertEqual(benchmark.benchmark_destination(original).name, "out_081_cli_benchmark_002")

    def test_dry_run_writes_no_render_log(self):
        destination = self.root / "result"
        destination.mkdir()
        self.assertEqual(benchmark.run_benchmark(self.root / "job.json", destination, dry_run=True), 0)
        self.assertFalse((destination / "cli-benchmark.log").exists())

    def test_unreserved_destination_does_not_create_a_folder(self):
        original = self.root / "out_081"
        original.mkdir()
        proposed = benchmark.benchmark_destination(original, reserve=False)
        self.assertFalse(proposed.exists())

    def test_fuoum_timing_summary_does_not_imply_failure(self):
        summary = benchmark.timing_summary(
            '[Timing] FuouM frame 1/2: 1.000s\n[Timing] FuouM frame 2/2: 1.500s\n',
            exit_code=0, completed=True)
        self.assertIn('Render completed', summary)
        self.assertIn('2 synthesis calls', summary)
        self.assertIn('2.500s (1.250s/call)', summary)
        self.assertIn('include preview/progress', summary)
        self.assertNotIn('native EbSynth', summary)

    def test_successful_image_without_timings_is_not_a_failure(self):
        summary = benchmark.timing_summary('', exit_code=0, completed=True)
        self.assertIn('Render completed', summary)
        self.assertIn('No matching synthesis timing', summary)
        self.assertNotIn('failed', summary)

    def test_partial_timings_preserve_failure(self):
        summary = benchmark.timing_summary('[Timing] FuouM frame 1/2: 1.000s\n',
                                           exit_code=17, completed=False)
        self.assertIn('Render failed (exit code 17)', summary)
        self.assertIn('timings may be partial', summary)

    def verify_process_result(self, marker, exit_code, expected):
        destination = self.root / 'process_result'
        destination.mkdir()
        job = destination / 'job.json'
        job.write_text(json.dumps({'engine_runtime': {'python': 'selected-python.exe'}}), encoding='utf-8')
        if marker:
            (destination / 'COMPLETE.txt').write_text('ok', encoding='utf-8')
        process = SimpleNamespace(stdout=io.StringIO('done\n'), wait=lambda: exit_code)
        with patch.object(benchmark.subprocess, 'Popen', return_value=process) as launch, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(benchmark.run_benchmark(job, destination), expected)
        self.assertEqual(launch.call_args.args[0][0], 'selected-python.exe')
        return (destination / 'cli-benchmark.log').read_text(encoding='utf-8')

    def test_zero_exit_without_completion_marker_is_unsuccessful(self):
        self.assertIn('Completion marker missing', self.verify_process_result(False, 0, 1))

    def test_completed_image_process_succeeds(self):
        self.assertIn('Render completed', self.verify_process_result(True, 0, 0))

    def test_nonzero_exit_with_marker_remains_failure(self):
        self.assertIn('Render failed (exit code 17)', self.verify_process_result(True, 17, 17))

    def test_timing_summary_matches_renderer_lines(self):
        output = benchmark.timing_summary(
            "[Timing] Frame 1/2 key=1 frame=0 backward: between calls (flow/guides/blending) 0.200s; EbSynth 1.000s\n"
            "[Timing] Frame 2/2 key=1 frame=2 forward: between calls (flow/guides/blending) 0.400s; EbSynth 1.200s\n"
            "[Timing] Synthesis loop 2.900s; native EbSynth 2.200s; preview capture 0.030s\n"
        )
        self.assertIn("2 synthesis frames", output)
        self.assertIn("1.450s/frame", output)
        self.assertIn("1.100s/frame", output)
        self.assertIn("0.300s/frame", output)


if __name__ == "__main__":
    unittest.main()
