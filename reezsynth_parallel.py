"""Opt-in bounded parallel queue using independent isolated QProcess workers."""
import codecs
import json
import sys

from PySide6.QtCore import QObject, QProcess, QTimer
from reezsynth_jobs import PREFIX


class ParallelQueue(QObject):
    def __init__(self, window, records, script, limit):
        super().__init__(window)
        self.w = window
        self.pending = list(records)
        self.script = script
        self.limit = limit or len(records)
        self.active = {}
        self.cancelled = False
        self.failed = False
        self.running = True
        self.generation = window.queue_generation

    def valid(self):
        return self.running and self.w.parallel_queue is self and self.generation == self.w.queue_generation

    def start(self):
        if not self.valid():
            return
        while self.pending and len(self.active) < self.limit and not self.cancelled and not self.failed:
            record = self.pending.pop(0)
            process = QProcess(self)
            record = dict(record, percent=0, buffers={"out": "", "err": ""},
                decoders={name: codecs.getincrementaldecoder("utf-8")(errors="replace") for name in ("out", "err")},
                error=False)
            self.active[process] = record
            record["row"]["state"].setText("Starting")
            process.setWorkingDirectory(str(self.script.parent))
            process.readyReadStandardOutput.connect(lambda p=process: self.read(p, "out"))
            process.readyReadStandardError.connect(lambda p=process: self.read(p, "err"))
            process.errorOccurred.connect(lambda error, p=process: self.error(p, error))
            process.finished.connect(lambda code, status, p=process: self.finished(p, code, status))
            process.start(sys.executable, ["-X", "utf8", "-u", str(self.script), str(record["job_path"])])
        self.finish_if_idle()

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
        process.deleteLater()
        success = code == 0 and status == QProcess.ExitStatus.NormalExit and not record["error"] and (record["output"] / "COMPLETE.txt").is_file()
        if success:
            record["row"]["state"].setText("Complete")
            record["row"]["bar"].setValue(100)
            self.w.completed_work += record["weight"]
            self.w.options.notify(each=True)
        elif self.cancelled or self.failed:
            record["row"]["state"].setText("Stopped")
        else:
            record["row"]["state"].setText("Failed")
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
