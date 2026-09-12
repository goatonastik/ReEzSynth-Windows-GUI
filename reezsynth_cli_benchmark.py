"""Render the most recent GUI job through the direct command-line entry point.

The benchmark copies a completed GUI job's JSON configuration to a new sibling
output directory, then launches ``reezsynth_jobs.py job.json`` in a fresh Python
process. Inputs and all rendering settings are retained; existing outputs are
never reused or overwritten.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_LOG = ROOT / "reezsynth-session.log"
COMPLETED_OUTPUT = re.compile(r"^(?:\[[^\]]+\]\s+)?COMPLETE: .* -> (.+)$", re.MULTILINE)
FRAME_TIMING = re.compile(
    r"\[Timing\] Frame \d+/\d+.*?: between calls \(flow/guides/blending\) ([\d.]+)s; EbSynth ([\d.]+)s"
)
LOOP_TIMING = re.compile(
    r"\[Timing\] Synthesis loop ([\d.]+)s; native EbSynth ([\d.]+)s; preview capture ([\d.]+)s"
)


def latest_completed_job(log_path=DEFAULT_LOG):
    """Return the job JSON for the final completed GUI render in a session log."""
    log_path = Path(log_path)
    if not log_path.is_file():
        raise ValueError(f"No GUI session log found: {log_path}")
    matches = COMPLETED_OUTPUT.findall(log_path.read_text(encoding="utf-8", errors="replace"))
    if not matches:
        raise ValueError("The session log contains no completed render to benchmark.")
    job_path = Path(matches[-1].strip()) / "job.json"
    if not job_path.is_file():
        raise ValueError(f"The latest completed job JSON is unavailable: {job_path}")
    return job_path.resolve()


def benchmark_destination(source_output, reserve=True):
    """Find or reserve a new sibling output folder without overwriting results."""
    source_output = Path(source_output)
    for index in range(1, 10000):
        candidate = source_output.parent / f"{source_output.name}_cli_benchmark_{index:03d}"
        if not candidate.exists():
            if reserve:
                candidate.mkdir()
            return candidate.resolve()
    raise RuntimeError(f"Could not create a unique benchmark directory beside {source_output}")


def copy_benchmark_job(source_job, destination):
    source_job = Path(source_job).resolve()
    job = json.loads(source_job.read_text(encoding="utf-8"))
    source_output = Path(job["output"]).resolve()
    if source_output == Path(destination).resolve():
        raise ValueError("Benchmark output must differ from the original job output.")
    job["output"] = str(Path(destination).resolve())
    target = Path(destination) / "job.json"
    target.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return target, job


def timing_summary(text):
    """Return compact averages from the renderer's timing lines, if it completed."""
    frames = [(float(preparation), float(ebsynth))
              for preparation, ebsynth in FRAME_TIMING.findall(text)]
    loop = LOOP_TIMING.findall(text)
    if not frames or not loop:
        return "[Benchmark] Renderer timing summary unavailable (the render did not complete).\n"
    loop_seconds, native_seconds, preview_seconds = map(float, loop[-1])
    count = len(frames)
    preparation = sum(item[0] for item in frames)
    native = sum(item[1] for item in frames)
    return (
        f"[Benchmark] Renderer timing summary: {count} synthesis frames; "
        f"loop {loop_seconds:.3f}s ({loop_seconds / count:.3f}s/frame); "
        f"EbSynth {native_seconds:.3f}s ({native_seconds / count:.3f}s/frame); "
        f"between-call work {preparation:.3f}s ({preparation / count:.3f}s/frame); "
        f"preview capture {preview_seconds:.3f}s.\n"
    )


def run_benchmark(job_path, destination, dry_run=False, source_job=None):
    metadata_path = Path(source_job) if dry_run and source_job is not None else Path(job_path)
    metadata = json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.is_file() else {}
    python = metadata.get('engine_runtime', {}).get('python', sys.executable)
    command = [python, "-X", "utf8", "-u", str(ROOT / "reezsynth_jobs.py"), str(job_path)]
    log_path = Path(destination) / "cli-benchmark.log"
    print("=" * 96)
    print("CLI BENCHMARK")
    if source_job is not None:
        print(f"Original GUI job: {source_job}")
    print(f"Job passed to direct CLI: {job_path}")
    print(f"Benchmark output: {destination}")
    print("Command: " + subprocess.list2cmdline(command))
    print("=" * 96)
    if dry_run:
        return 0

    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        log.write("CLI benchmark command:\n" + subprocess.list2cmdline(command) + "\n\n")
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True,
                                   encoding="utf-8", errors="replace", bufsize=1)
        assert process.stdout is not None
        captured = []
        for line in process.stdout:
            print(line, end="")
            log.write(line)
            captured.append(line)
        result = process.wait()
        elapsed = time.perf_counter() - started
        summary = timing_summary("".join(captured))
        print(summary, end="")
        log.write(summary)
        summary = f"[Benchmark] Direct CLI wall time: {elapsed:.3f}s; exit code: {result}\n"
        print(summary, end="")
        log.write(summary)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", nargs="?", type=Path,
                        help="Existing GUI job.json. Defaults to the final completed job in reezsynth-session.log.")
    parser.add_argument("--session-log", type=Path, default=DEFAULT_LOG,
                        help="GUI session log used when no job is supplied.")
    parser.add_argument("--dry-run", action="store_true", help="Show the cloned job and command without rendering.")
    args = parser.parse_args(argv)

    source_job = args.job.resolve() if args.job else latest_completed_job(args.session_log)
    if not source_job.is_file():
        raise ValueError(f"Job JSON does not exist: {source_job}")
    source_data = json.loads(source_job.read_text(encoding="utf-8"))
    if "output" not in source_data:
        raise ValueError("Job JSON has no output folder.")
    destination = benchmark_destination(source_data["output"], reserve=not args.dry_run)
    if args.dry_run:
        print(f"Exact render settings copied: quality={source_data.get('quality')}; "
              f"processing_size={source_data.get('processing_size')}; "
              f"render_options={json.dumps(source_data.get('render_options', {}), sort_keys=True)}")
        return run_benchmark(destination / "job.json", destination, dry_run=True, source_job=source_job)
    benchmark_job, job = copy_benchmark_job(source_job, destination)
    print(f"Exact render settings copied: quality={job.get('quality')}; "
          f"processing_size={job.get('processing_size')}; "
          f"render_options={json.dumps(job.get('render_options', {}), sort_keys=True)}")
    return run_benchmark(benchmark_job, destination, source_job=source_job)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"CLI benchmark failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
