"""Run a bounded or overnight alternating-engine GPU stability campaign."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

from reezsynth_config import atomic_json
from reezsynth_engines import ROOT


STYLES = ("painting", "poster", "flat")


def used_mib(value):
    try:
        return int(str(value).split(",", 1)[0].strip())
    except (ValueError, TypeError):
        return None


def case_command(engine, style, args):
    command = [sys.executable, "-B", str(ROOT / "diagnose_reezsynth_release.py"),
               "--engine", engine, "--frames", str(args.frames), "--repeats", "1",
               "--style", style, "--quality", args.quality,
               "--size", str(args.size[0]), str(args.size[1])]
    if args.extended:
        command.append("--extended")
    if args.images:
        command.append("--images")
    return command


def planned_cases(args):
    engines = ("legacy", "fuoum") if args.engine == "both" else (args.engine,)
    return [(engine, style) for engine in engines for style in STYLES]


def newest_output(engine, before):
    candidates = set((ROOT / "diagnostic_outputs").glob(f"release_{engine}_*")) - before
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("legacy", "fuoum", "both"), default="both")
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--cycles", type=int, default=0,
                        help="Complete campaign cycles; zero runs until --hours.")
    parser.add_argument("--frames", type=int, default=33)
    parser.add_argument("--quality", choices=("Preview", "Standard", "Highest"), default="Standard")
    parser.add_argument("--size", nargs=2, type=int, default=(384, 216), metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--extended", action="store_true")
    parser.add_argument("--images", action="store_true")
    parser.add_argument("--case-timeout", type=int, default=1800)
    parser.add_argument("--max-gpu-drift-mib", type=int, default=2048,
                        help="Fail if post-exit device use rises this far above baseline; zero disables.")
    parser.add_argument("--plan", action="store_true", help="Print the campaign without writes or renders.")
    args = parser.parse_args(argv)
    if args.hours <= 0 or args.cycles < 0 or args.frames < 3 or min(args.size) < 128:
        parser.error("Use positive hours, nonnegative cycles, at least 3 frames and dimensions >= 128.")
    cases = planned_cases(args)
    plan = dict(engine=args.engine, hours=args.hours, cycles=args.cycles or "until deadline",
                frames=args.frames, quality=args.quality, size=args.size,
                cases=[dict(engine=e, style=s, command=case_command(e, s, args)) for e, s in cases])
    if args.plan:
        print(json.dumps(plan, indent=2))
        return 0

    from diagnose_reezsynth_engines import gpu_memory
    base = ROOT / "diagnostic_outputs" / ("stability_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    base.mkdir(parents=True)
    baseline = gpu_memory()
    report = dict(**plan, started=datetime.now().isoformat(), gpu_baseline=baseline,
                  runs=[], passed=False, interrupted=False)
    atomic_json(base / "report.json", report)
    deadline = time.monotonic() + args.hours * 3600
    cycle = 0
    try:
        while (args.cycles == 0 or cycle < args.cycles) and time.monotonic() < deadline:
            for engine, style in cases:
                if time.monotonic() >= deadline and report["runs"]:
                    break
                before = set((ROOT / "diagnostic_outputs").glob(f"release_{engine}_*"))
                started = time.monotonic()
                result = subprocess.run(case_command(engine, style, args), cwd=ROOT,
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=args.case_timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                output = newest_output(engine, before)
                child = None
                if output and (output / "report.json").is_file():
                    child = json.loads((output / "report.json").read_text(encoding="utf-8"))
                after = gpu_memory()
                drift = None
                if used_mib(baseline) is not None and used_mib(after) is not None:
                    drift = used_mib(after) - used_mib(baseline)
                passed = bool(result.returncode == 0 and child and child.get("passed"))
                if args.max_gpu_drift_mib and drift is not None and drift > args.max_gpu_drift_mib:
                    passed = False
                entry = dict(cycle=cycle + 1, engine=engine, style=style,
                    seconds=time.monotonic() - started, exit_code=result.returncode,
                    output=str(output) if output else None, gpu_after=after,
                    gpu_drift_mib=drift, passed=passed,
                    stdout_tail=result.stdout[-4000:], stderr_tail=result.stderr[-4000:])
                report["runs"].append(entry)
                atomic_json(base / "report.json", report)
                print(json.dumps({key: entry[key] for key in
                    ("cycle", "engine", "style", "seconds", "gpu_drift_mib", "passed")}), flush=True)
                if not passed:
                    raise RuntimeError(f"Stability case failed; see {base / 'report.json'}")
            cycle += 1
        report["passed"] = bool(report["runs"])
    except KeyboardInterrupt:
        report["interrupted"] = True
    finally:
        report["finished"] = datetime.now().isoformat()
        report["gpu_after"] = gpu_memory()
        atomic_json(base / "report.json", report)
    print("PASS:" if report["passed"] else "STOPPED:", base)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
