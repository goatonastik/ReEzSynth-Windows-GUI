"""CPU-only ownership and GUI admission tests for shared GPU work."""

import threading
import unittest
from unittest.mock import MagicMock, patch

from reezsynth_gpu_gate import GpuAdmission, GpuBusy
from test_reezsynth_gui import GuiFixture


class GateTests(unittest.TestCase):
    def test_owner_token_prevents_stale_release(self):
        gate = GpuAdmission()
        old = gate.acquire("render batch")
        with self.assertRaises(GpuBusy):
            gate.acquire("keyframe generation")
        self.assertEqual(gate.owner, "render batch")
        self.assertFalse(gate.release(None))
        self.assertTrue(gate.release(old))
        current = gate.acquire("keyframe generation")
        self.assertFalse(gate.release(old))
        self.assertEqual(gate.owner, "keyframe generation")
        self.assertTrue(gate.release(current))
        self.assertIsNone(gate.owner)

    def test_simultaneous_claims_have_one_owner(self):
        gate = GpuAdmission()
        barrier = threading.Barrier(2)
        results = []
        tokens = []

        def claim(label):
            barrier.wait(timeout=5)
            try:
                token = gate.acquire(label)
                tokens.append(token)
                results.append("claimed")
            except GpuBusy:
                results.append("busy")

        threads = [threading.Thread(target=claim, args=(str(index),)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(results, ["claimed", "busy"])
        self.assertTrue(gate.release(tokens[0]))


class GuiAdmissionTests(GuiFixture):
    def test_render_start_rejected_while_generation_reserves_gate(self):
        window = self.window()
        token = window.gpu_gate.acquire("keyframe generation")
        window.start_records([], self.root, False, False, self.root / "unused.py", {})
        self.assertFalse(window.busy)
        self.assertEqual(window.gpu_gate.owner, "keyframe generation")
        self.assertIn("keyframe generation", window.status.text())
        self.assertFalse((self.root / ".reezsynth-queue.json").exists())
        self.assertTrue(window.gpu_gate.release(token))

    def test_render_preparation_stops_before_creating_jobs(self):
        window = self.window()
        token = window.gpu_gate.acquire("keyframe generation")
        window.run_rows([])
        self.assertIn("keyframe generation", window.status.text())
        self.assertFalse(window.busy)
        self.assertFalse((self.root / ".reezsynth-queue.json").exists())
        self.assertTrue(window.gpu_gate.release(token))

    def test_empty_render_batch_releases_gate_after_end(self):
        window = self.window()
        window.start_records([], self.root, False, False, self.root / "unused.py", {})
        self.assertIsNone(window.gpu_gate.owner)
        self.assertIsNone(window.queue_gpu_token)

    def test_journal_start_failure_releases_render_lease(self):
        window = self.window()
        with (patch("reezsynth_queue_recovery.create_journal", side_effect=OSError("fixture failure")),
              patch.object(window.status, "setText") as _):
            # The shared GUI fixture rejects unexpected dialogs; override only
            # the expected queue-start warning for this failure path.
            from reezsynth_gui import QMessageBox
            with patch.object(QMessageBox, "warning") as warning:
                window.start_records([], self.root, False, False, self.root / "unused.py", {})
        warning.assert_called_once()
        self.assertIsNone(window.gpu_gate.owner)
        self.assertIsNone(window.queue_gpu_token)

    def test_cancelled_edge_preview_holds_lease_until_worker_exit(self):
        from reezsynth_edge_preview import EdgePreviewWindow
        window = self.window()
        preview = EdgePreviewWindow(window.options)
        self.widgets.append(preview)
        process = MagicMock()
        process.readAllStandardOutput.return_value = b""
        preview.process = process
        preview.gpu_token = window.gpu_gate.acquire("Edge Preview")
        preview.cancel()
        self.assertEqual(window.gpu_gate.owner, "Edge Preview")
        process.terminate.assert_called_once()
        preview.finished(process, -1)
        self.assertIsNone(window.gpu_gate.owner)
        self.assertIsNone(preview.gpu_token)


if __name__ == "__main__":
    unittest.main()
