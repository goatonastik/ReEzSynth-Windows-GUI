"""Lightweight regression tests for the ReEzSynth persistent worker.

Run:
    python test_reezsynth_worker.py

These tests:
- Do not initialize the rendering engine or GPU.
- Do not modify project files or render outputs.
- Run a temporary copy of the real shared-worker script.
- Replace only the renderer dependency with a small test stand-in.

They test the worker command protocol and shutdown behavior.
They do not test GUI lifecycle handling or actual render quality.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKER_SOURCE = ROOT / "reezsynth_shared_worker.py"
SESSION_PREFIX = "@@REEZSYNTH_SESSION@@"
PROCESS_TIMEOUT_SECONDS = 15


FAKE_RENDERER = textwrap.dedent(
    """\
    from pathlib import Path


    def render_job(job_path):
        job_path = Path(job_path)

        if job_path.name == "fail.json":
            raise RuntimeError("Intentional test render failure")

        print(
            f"[Test renderer] Rendered {job_path.name}",
            flush=True,
        )
    """
)


class SharedWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not WORKER_SOURCE.is_file():
            raise FileNotFoundError(
                "Place this test file beside "
                f"reezsynth_shared_worker.py. Expected: {WORKER_SOURCE}"
            )

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(
            prefix="reezsynth_worker_test_"
        )
        self.addCleanup(temporary.cleanup)

        self.workspace = Path(temporary.name)
        self.worker = self.workspace / "reezsynth_shared_worker.py"

        shutil.copy2(WORKER_SOURCE, self.worker)

        (self.workspace / "reezsynth_jobs.py").write_text(
            FAKE_RENDERER,
            encoding="utf-8",
        )

    def run_worker(self, commands=None, raw_input=None):
        if raw_input is None:
            raw_input = "".join(
                json.dumps(command) + "\n"
                for command in (commands or [])
            )

        # subprocess.run closes stdin after sending input.
        # On timeout, it kills and waits for the child process.
        return subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-u",
                str(self.worker),
            ],
            input=raw_input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.workspace),
            encoding="utf-8",
            errors="replace",
            timeout=PROCESS_TIMEOUT_SECONDS,
            check=False,
        )

    def events(self, result):
        messages = []

        for line in result.stdout.splitlines():
            if line.startswith(SESSION_PREFIX):
                messages.append(
                    json.loads(line[len(SESSION_PREFIX):])
                )

        return messages

    def diagnostic(self, result):
        return (
            f"\nExit code: {result.returncode}"
            f"\n--- stdout ---\n{result.stdout}"
            f"\n--- stderr ---\n{result.stderr}"
        )

    def assert_cleanup_ran(self, result):
        self.assertIn(
            "[Session] Shutdown cleanup starting.",
            result.stdout,
            self.diagnostic(result),
        )
        self.assertIn(
            "[Session] Cleanup pass finished; worker exiting.",
            result.stdout,
            self.diagnostic(result),
        )

    def test_two_jobs_then_clean_shutdown(self):
        first = self.workspace / "first.json"
        second = self.workspace / "second.json"

        result = self.run_worker(
            [
                {"action": "run", "job": str(first)},
                {"action": "run", "job": str(second)},
                {"action": "quit"},
            ]
        )

        self.assertEqual(
            result.returncode, 0, self.diagnostic(result)
        )
        self.assertEqual(
            self.events(result),
            [
                {
                    "event": "job_done",
                    "job": str(first.resolve()),
                },
                {
                    "event": "job_done",
                    "job": str(second.resolve()),
                },
            ],
            self.diagnostic(result),
        )
        self.assertIn(
            "Queue finished; shutdown requested.",
            result.stdout,
            self.diagnostic(result),
        )
        self.assert_cleanup_ran(result)

    def test_input_closure_runs_cleanup(self):
        job = self.workspace / "eof.json"

        # No quit command: closing stdin must still run cleanup.
        result = self.run_worker(
            [{"action": "run", "job": str(job)}]
        )

        self.assertEqual(
            result.returncode, 0, self.diagnostic(result)
        )
        self.assertEqual(
            len(self.events(result)), 1, self.diagnostic(result)
        )
        self.assertIn(
            "Command input closed; shutting down.",
            result.stdout,
            self.diagnostic(result),
        )
        self.assert_cleanup_ran(result)

    def test_render_failure_exits_without_starting_next_job(self):
        failed_job = self.workspace / "fail.json"
        next_job = self.workspace / "must_not_run.json"

        result = self.run_worker(
            [
                {"action": "run", "job": str(failed_job)},
                {"action": "run", "job": str(next_job)},
                {"action": "quit"},
            ]
        )

        self.assertNotEqual(
            result.returncode, 0, self.diagnostic(result)
        )
        self.assertEqual(
            self.events(result), [], self.diagnostic(result)
        )
        self.assertIn(
            "Intentional test render failure",
            result.stderr,
            self.diagnostic(result),
        )
        self.assertNotIn(
            "[Test renderer] Rendered must_not_run.json",
            result.stdout,
            self.diagnostic(result),
        )
        self.assert_cleanup_ran(result)

    def test_unknown_command_runs_cleanup_and_fails(self):
        result = self.run_worker(
            [{"action": "not-a-valid-action"}]
        )

        self.assertNotEqual(
            result.returncode, 0, self.diagnostic(result)
        )
        self.assertEqual(
            self.events(result), [], self.diagnostic(result)
        )
        self.assertIn(
            "Unknown worker command",
            result.stderr,
            self.diagnostic(result),
        )
        self.assert_cleanup_ran(result)

    def test_invalid_json_runs_cleanup_and_fails(self):
        result = self.run_worker(
            raw_input="this is not JSON\n"
        )

        self.assertNotEqual(
            result.returncode, 0, self.diagnostic(result)
        )
        self.assertEqual(
            self.events(result), [], self.diagnostic(result)
        )
        self.assertIn(
            "JSONDecodeError",
            result.stderr,
            self.diagnostic(result),
        )
        self.assert_cleanup_ran(result)

    def test_empty_queue_can_shut_down(self):
        result = self.run_worker(
            [{"action": "quit"}]
        )

        self.assertEqual(
            result.returncode, 0, self.diagnostic(result)
        )
        self.assertEqual(
            self.events(result), [], self.diagnostic(result)
        )
        self.assert_cleanup_ran(result)

    def test_new_worker_can_run_another_queue(self):
        for index in range(2):
            with self.subTest(queue=index + 1):
                job = self.workspace / f"queue_{index}.json"

                result = self.run_worker(
                    [
                        {"action": "run", "job": str(job)},
                        {"action": "quit"},
                    ]
                )

                self.assertEqual(
                    result.returncode,
                    0,
                    self.diagnostic(result),
                )
                self.assertEqual(
                    self.events(result),
                    [
                        {
                            "event": "job_done",
                            "job": str(job.resolve()),
                        }
                    ],
                    self.diagnostic(result),
                )
                self.assert_cleanup_ran(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)