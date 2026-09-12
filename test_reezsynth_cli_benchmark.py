"""Unit tests for the direct-CLI benchmark setup; no renderer or GPU."""
import json
import tempfile
import unittest
from pathlib import Path

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
