"""Opt-in bounded parallel queue using independent isolated QProcess workers."""
import codecs
import json
import sys

from PySide6.QtCore import QObject, QProcess, QTimer
from reezsynth_jobs import PREFIX
from reezsynth_resources import (estimate_job_vram, format_mib, gpu_snapshot,
                                 safety_reserve_mib)


class ParallelQueue(QObject):
    def __init__(self, window, records, script, limit):
        super().__init__(window)
        self.w = window
        self.pending = list(records)
        self.script = script
        self.limit = limit
        self.active = {}
        self.cancelled = False
        self.failed = False
        self.running = True
        self.generation = window.queue_generation
        self.gpu = gpu_snapshot()
        self.reserve_mib = safety_reserve_mib(self.gpu) if self.gpu else 0
        self.capacity_mib = (self.gpu["free_mib"] - self.reserve_mib) if self.gpu else None
        for record in self.pending:
            try:
                record["resources"] = estimate_job_vram(record["job_path"])
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                record["resources"] = dict(estimated_mib=4096, width=0, height=0,
                                            engine="unknown", basis="fallback estimate")
        self.describe_policy()

    def valid(self):
        return self.running and self.w.parallel_queue is self and self.generation == self.w.queue_generation

    def start(self):
        if not self.valid():
            return
        snapshot = gpu_snapshot()
        if snapshot and self.gpu and snapshot["index"] == self.gpu["index"]:
            active_reserved = sum(item["resources"]["estimated_mib"] for item in self.active.values())
            current_capacity = snapshot["free_mib"] + active_reserved - self.reserve_mib
            self.capacity_mib = max(0, min(self.capacity_mib, current_capacity))
            self.gpu = snapshot
        hard_limit = self.limit or (len(self.pending) + len(self.active) if self.gpu else 1)
        while self.pending and len(self.active) < hard_limit and not self.cancelled and not self.failed:
            candidate = self.pending[0]
            active_reserved = sum(item["resources"]["estimated_mib"] for item in self.active.values())
            estimate = candidate["resources"]["estimated_mib"]
            if self.capacity_mib is not None and active_reserved + estimate > self.capacity_mib and self.active:
                candidate["row"]["state"].setText("Waiting for GPU memory")
                candidate["row"]["state"].setToolTip(
                    f"Estimated {format_mib(estimate)}; {format_mib(active_reserved)} reserved by active workers.")
                break
            record = self.pending.pop(0)
            if self.capacity_mib is not None and estimate > self.capacity_mib and not self.active:
                self.w.log.appendPlainText(
                    f"[Parallel resources] Key {record['row']['key']} estimate "
                    f"{format_mib(estimate)} exceeds the safe available budget "
                    f"{format_mib(self.capacity_mib)}; admitting it alone so the queue can make progress.")
            if not self.w.journal_state(record, 'running'):
                record['row']['state'].setText('Failed')
                self.failed = True
                self.w.log.appendPlainText('[Parallel queue] Recovery journal update failed; no worker was started.')
                break
            process = QProcess(self)
            record = dict(record, percent=0, buffers={"out": "", "err": ""},
                decoders={name: codecs.getincrementaldecoder("utf-8")(errors="replace") for name in ("out", "err")},
                error=False)
            self.active[process] = record
            self.w.preview_window.activate(record)
            record["row"]["state"].setText("Starting")
            process.setWorkingDirectory(str(self.script.parent))
            process.readyReadStandardOutput.connect(lambda p=process: self.read(p, "out"))
            process.readyReadStandardError.connect(lambda p=process: self.read(p, "err"))
            process.errorOccurred.connect(lambda error, p=process: self.error(p, error))
            process.finished.connect(lambda code, status, p=process: self.finished(p, code, status))
            process.started.connect(lambda p=process: self.worker_started(p))
            process.start(record.get('python', sys.executable), ["-X", "utf8", "-u", str(self.script), str(record["job_path"])])
        self.finish_if_idle()

    def describe_policy(self):
        cap = self.limit or "automatic"
        if self.gpu:
            self.w.log.appendPlainText(
                f"[Parallel resources] GPU {self.gpu['index']} {self.gpu['name']}: "
                f"{format_mib(self.gpu['free_mib'])} free of {format_mib(self.gpu['total_mib'])}; "
                f"safety reserve {format_mib(self.reserve_mib)}; worker cap {cap}.")
        else:
            fallback = "one worker" if not self.limit else f"explicit cap {self.limit}"
            self.w.log.appendPlainText(
                f"[Parallel resources] NVIDIA telemetry unavailable; using estimates with {fallback}.")

    def worker_started(self, process):
        record = self.active.get(process)
        if record is None:
            return
        resources = record["resources"]
        record["worker_pid"] = process.processId()
        gpu = f"GPU {self.gpu['index']}" if self.gpu else "GPU telemetry unavailable"
        detail = (f"PID {record['worker_pid']} | {gpu} | estimated peak "
                  f"{format_mib(resources['estimated_mib'])} at "
                  f"{resources['width']}x{resources['height']} ({resources['engine']})")
        record["row"]["state"].setToolTip(detail)
        self.w.log.appendPlainText(f"[Parallel worker key {record['row']['key']}] {detail}")

    def read(self, process, name, final=False):
        record = self.active.get(process)
        if record is None:
            return
        getter = process.readAllStandardOutput if name == "out" else process.readAllStandardError
        record["buffers"][name] += record["decoders"][name].decode(bytes(getter()), final=final).replace("\r", "\n")
        lines = record["buffers"][name].split("\n")
        record["buffers"][name] = lines.pop()
        if final and record["buffers"][name]:
            lines.append(record["buffers"][name])
            record["buffers"][name] = ""
        for line in lines:
            if not line.strip():
                continue
            self.w.check_gpu_memory_error(line)
            if name == "out" and line.startswith(PREFIX) and not self.cancelled and not self.failed:
                try:
                    message = json.loads(line[len(PREFIX):])
                    percent = max(record["percent"], min(99, max(0, int(message["percent"]))))
                    record["percent"] = percent
                    record["row"]["bar"].setValue(percent)
                    record["row"]["state"].setText(str(message["stage"]))
                    self.w.preview_window.receive(message.get('preview'), record)
                    self.progress()
                    continue
                except (ValueError, KeyError, TypeError, OverflowError):
                    pass
            self.w.log.appendPlainText(f"[Key {record['row']['key']}] {line}")

    def progress(self):
        work = self.w.completed_work + sum(r["weight"] * r["percent"] / 100 for r in self.active.values())
        self.w.overall.setValue(min(99, int(100 * work / max(1, self.w.total_work))))

    def error(self, process, error):
        if process not in self.active:
            return
        self.active[process]["error"] = True
        self.w.log.appendPlainText(f"[Parallel worker] {process.errorString()}")
        if error == QProcess.ProcessError.FailedToStart:
            self.finished(process, -1, QProcess.ExitStatus.CrashExit)
        elif error != QProcess.ProcessError.Crashed:
            process.kill()

    def finished(self, process, code, status):
        record = self.active.get(process)
        if record is None:
            return
        self.read(process, "out", True)
        self.read(process, "err", True)
        del self.active[process]
        snapshot = gpu_snapshot()
        resources = record["resources"]
        finish_gpu = (f"; GPU {snapshot['index']} now {format_mib(snapshot['free_mib'])} free"
                      if snapshot else "")
        self.w.log.appendPlainText(
            f"[Parallel worker key {record['row']['key']}] PID {record.get('worker_pid', 'unknown')} exited; "
            f"reserved estimate {format_mib(resources['estimated_mib'])}{finish_gpu}.")
        self.w.preview_window.finish(record)
        process.deleteLater()
        success = code == 0 and status == QProcess.ExitStatus.NormalExit and not record["error"] and (record["output"] / "COMPLETE.txt").is_file()
        if success:
            record["row"]["state"].setText("Complete")
            record["row"]["bar"].setValue(100)
            self.w.journal_state(record, 'complete')
            self.w.completed_work += record["weight"]
            self.w.options.notify(each=True)
        elif self.cancelled or self.failed:
            record["row"]["state"].setText("Stopped")
            self.w.journal_state(record, 'interrupted')
        else:
            record["row"]["state"].setText("Failed")
            self.w.journal_state(record, 'failed')
            self.failed = True
            self.w.log.appendPlainText("[Parallel queue] Render failed; stopping other workers.")
            self.kill_active()
        self.progress()
        if not self.cancelled and not self.failed:
            QTimer.singleShot(0, self.start)
        self.finish_if_idle()

    def kill_active(self):
        for process in list(self.active):
            process.kill()

    def stop(self):
        self.cancelled = True
        self.w.cancelled = True
        self.w.stop.setEnabled(False)
        self.w.status.setText("Stopping parallel queue - waiting for all workers to exit...")
        self.kill_active()
        self.finish_if_idle()

    def finish_if_idle(self):
        if self.active or (self.pending and not self.cancelled and not self.failed) or not self.running:
            return
        for record in self.pending:
            record["row"]["state"].setText("Not run")
        self.pending.clear()
        self.running = False
        self.w.parallel_queue = None
        if self.cancelled:
            message = "Queue stopped - all parallel workers exited"
        elif self.failed:
            message = "Parallel queue failed - all workers exited. See log."
        else:
            self.w.overall.setValue(100)
            message = "Queue complete - all parallel workers exited"
        self.w.end_queue(message)
        self.deleteLater()
