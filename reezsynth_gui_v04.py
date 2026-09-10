import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from reezsynth_jobs import ROOT
from reezsynth_gui_v03 import APP_NAME, THEME
from reezsynth_gui_v031 import UpdatedMainWindow, EXTRA_THEME


SESSION_PREFIX = "@@REEZSYNTH_SESSION@@"
SHUTDOWN_TIMEOUT_MS = 30_000


class SharedWorkerWindow(UpdatedMainWindow):
    def __init__(self):
        # These exist before the parent calls overridable methods.
        self.shared_this_run = False
        self.shared_exit_handled = True
        self.session_closing = False
        self.session_error = None
        self.job_sent = False
        self.queue_started_at = None

        super().__init__()

        self.setWindowTitle(APP_NAME + " - v0.4")
        self.preferences = QSettings("ReEzSynth", APP_NAME)

        self.shutdown_timer = QTimer(self)
        self.shutdown_timer.setSingleShot(True)
        self.shutdown_timer.setInterval(SHUTDOWN_TIMEOUT_MS)
        self.shutdown_timer.timeout.connect(
            self.worker_shutdown_timeout
        )

        settings_page = QWidget()
        settings_layout = QVBoxLayout(settings_page)

        self.reuse_worker = QCheckBox(
            "Reuse worker between renders (recommended)"
        )
        self.reuse_worker.setChecked(
            self.preferences.value(
                "reuse_queue_worker", True, type=bool
            )
        )
        self.reuse_worker.setStyleSheet(
            "QCheckBox::indicator { width: 20px; height: 20px; }"
        )
        self.reuse_worker.toggled.connect(
            lambda enabled: self.preferences.setValue(
                "reuse_queue_worker", enabled
            )
        )

        description = QLabel(
            "Speeds up queued renders while initializing the engine "
            "for each job. The worker exits when the queue ends to "
            "release memory.\n\n"
            "Disable to start a fresh worker for each render if memory "
            "usage grows or renders become unstable."
        )
        description.setWordWrap(True)

        settings_layout.addWidget(self.reuse_worker)
        settings_layout.addWidget(description)
        settings_layout.addStretch()

        self.tabs.addTab(settings_page, "Settings")
        self.locked.append(self.reuse_worker)

        self.process.started.connect(self.worker_started)

    def run_rows(self, rows):
        if self.busy:
            return

        self.shutdown_timer.stop()

        self.shared_this_run = self.reuse_worker.isChecked()
        self.shared_exit_handled = False
        self.session_closing = False
        self.session_error = None
        self.job_sent = False

        super().run_rows(rows)

    def set_busy(self, busy):
        was_busy = getattr(self, "busy", False)

        if busy and not was_busy:
            self.queue_started_at = time.perf_counter()

        super().set_busy(busy)

        if (
            not busy
            and was_busy
            and self.queue_started_at is not None
        ):
            elapsed = time.perf_counter() - self.queue_started_at
            mode = "shared" if self.shared_this_run else "isolated"

            self.log.appendPlainText(
                f"\n[Timing] Worker queue ({mode}): {elapsed:.3f}s\n"
                f"[Timing] Result: {self.status.text()}"
            )
            self.queue_started_at = None

    def start_next(self):
        if not self.shared_this_run:
            return super().start_next()

        if (
            not self.busy
            or self.cancelled
            or self.session_closing
            or self.shared_exit_handled
        ):
            return

        # Do not start another job while one is already active.
        if self.current is not None:
            return

        if not self.pending:
            self.session_closing = True
            self.status.setText(
                "Renders complete — releasing worker resources..."
            )
            self.log.appendPlainText(
                "[Session] All renders complete. "
                "Requesting cleanup and waiting for worker exit."
            )

            if self.process.state() != QProcess.ProcessState.Running:
                self.fail_session(
                    "Shared worker ended before shutdown."
                )
                return

            payload = (
                json.dumps({"action": "quit"}) + "\n"
            ).encode("utf-8")

            if self.process.write(payload) != len(payload):
                self.fail_session(
                    "Could not send the worker shutdown command."
                )
                return

            # QProcess sends buffered data before closing the channel.
            self.process.closeWriteChannel()
            self.shutdown_timer.start()
            return

        self.current = self.pending.pop(0)
        self.job_sent = False

        row = self.current["row"]
        row["state"].setText("Starting")
        self.status.setText(f"Starting keyframe {row['key']}")

        self.log.appendPlainText(
            f"\n=== Keyframe {row['key']} - shared worker ===\n"
            f"Output: {self.current['output']}"
        )

        state = self.process.state()

        if state == QProcess.ProcessState.NotRunning:
            self.reset_streams()
            self.shared_exit_handled = False
            self.process.setWorkingDirectory(str(ROOT))
            self.process.start(
                sys.executable,
                [
                    "-X",
                    "utf8",
                    "-u",
                    str(ROOT / "reezsynth_shared_worker.py"),
                ],
            )
            # The started signal sends the first job.

        elif state == QProcess.ProcessState.Running:
            self.send_current_job()

        else:
            self.fail_session(
                "Shared worker is in an unexpected startup state."
            )

    def worker_started(self):
        if not self.shared_this_run:
            return

        if self.cancelled:
            self.process.kill()
            return

        self.send_current_job()

    def send_current_job(self):
        if (
            self.current is None
            or self.job_sent
            or self.cancelled
            or self.session_closing
        ):
            return

        command = {
            "action": "run",
            "job": str(self.current["job_path"].resolve()),
        }
        payload = (
            json.dumps(command) + "\n"
        ).encode("utf-8")

        if self.process.write(payload) != len(payload):
            self.fail_session(
                "Could not send the job to the shared worker."
            )
            return

        self.job_sent = True

    def consume_line(self, name, line):
        if (
            self.shared_this_run
            and name == "out"
            and line.startswith(SESSION_PREFIX)
        ):
            if self.cancelled:
                return

            try:
                message = json.loads(
                    line[len(SESSION_PREFIX):]
                )

                if not isinstance(message, dict):
                    raise ValueError(
                        "Invalid shared-worker event."
                    )

                if message.get("event") != "job_done":
                    raise ValueError(
                        "Unknown shared-worker event."
                    )

                if self.current is None:
                    raise ValueError(
                        "Received completion without an active job."
                    )

                reported = Path(message["job"]).resolve()
                expected = self.current["job_path"].resolve()

                if reported != expected:
                    raise ValueError(
                        "Worker completed an unexpected job."
                    )

                marker = (
                    self.current["output"] / "COMPLETE.txt"
                )
                if not marker.is_file():
                    raise ValueError(
                        "Worker did not write the completion marker."
                    )

            except (
                ValueError,
                TypeError,
                KeyError,
                OSError,
            ) as exc:
                self.fail_session(str(exc))
                return

            record = self.current
            record["row"]["state"].setText("Complete")
            record["row"]["bar"].setValue(100)

            self.completed_work += record["weight"]
            self.current = None
            self.update_overall()

            # Keep the same process and stream decoders.
            QTimer.singleShot(0, self.start_next)
            return

        super().consume_line(name, line)

    def fail_session(self, message):
        self.shutdown_timer.stop()
        self.session_error = message
        self.log.appendPlainText(
            "[Session error] " + message
        )

        if self.process.state() != QProcess.ProcessState.NotRunning:
            # job_finished() confirms process exit before ending
            # the queue.
            self.process.kill()

        elif not self.shared_exit_handled:
            self.shared_exit_handled = True

            if self.current is not None:
                self.current["row"]["state"].setText("Failed")

            self.end_queue(
                "Shared-worker queue failed. See log."
            )
            self.tabs.setCurrentWidget(self.log)

    def worker_shutdown_timeout(self):
        if (
            not self.shared_this_run
            or not self.session_closing
            or self.shared_exit_handled
        ):
            return

        if self.process.state() == QProcess.ProcessState.NotRunning:
            return

        seconds = SHUTDOWN_TIMEOUT_MS // 1000
        self.session_error = (
            f"Worker shutdown exceeded {seconds} seconds; "
            "forced termination was required."
        )

        self.log.appendPlainText(
            "[Session warning] " + self.session_error
        )
        self.status.setText(
            "Cleanup timed out — terminating worker..."
        )

        # Forced termination may skip Python cleanup.
        # Wait for job_finished() to confirm process exit.
        self.process.kill()

    def job_finished(self, exit_code, exit_status):
        if not self.shared_this_run:
            return super().job_finished(
                exit_code, exit_status
            )

        self.shutdown_timer.stop()

        # This signal means the entire shared process ended,
        # not merely that one keyframe finished.
        if self.shared_exit_handled:
            return

        self.shared_exit_handled = True

        self.read_stream("out", final=True)
        self.read_stream("err", final=True)
        self.streams_closed = True

        successful = (
            exit_code == 0
            and exit_status == QProcess.ExitStatus.NormalExit
            and self.session_closing
            and self.session_error is None
            and self.current is None
            and not self.pending
        )

        if self.cancelled:
            self.log.appendPlainText(
                "[Session] Worker exited after cancellation."
            )

            if self.current is not None:
                self.current["row"]["state"].setText(
                    "Stopped"
                )

            self.end_queue(
                "Queue stopped - output may be incomplete"
            )

        elif successful:
            self.log.appendPlainText(
                "[Session] Worker exited normally. "
                "Queue cleanup complete."
            )
            self.overall.setValue(100)
            self.status.setText(
                "Queue complete — worker exited"
            )
            self.set_busy(False)

        elif (
            self.session_closing
            and self.current is None
            and not self.pending
        ):
            # All jobs reported completion, but the worker
            # did not shut down normally.
            self.log.appendPlainText(
                "[Session warning] Renders completed, but "
                "worker shutdown was abnormal. "
                "The worker has now exited."
            )
            self.overall.setValue(100)
            self.status.setText(
                "Renders complete — worker shutdown warning. "
                "See log."
            )
            self.set_busy(False)
            self.tabs.setCurrentWidget(self.log)

        else:
            if self.current is not None:
                self.current["row"]["state"].setText(
                    "Failed"
                )

            self.end_queue(
                "Shared worker failed or exited early. "
                "See log."
            )
            self.tabs.setCurrentWidget(self.log)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(THEME + EXTRA_THEME)

    window = SharedWorkerWindow()
    window.show()

    sys.exit(app.exec())