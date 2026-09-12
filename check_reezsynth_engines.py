"""Read-only readiness checks for both engines included by standard setup."""
import argparse
from pathlib import Path
import subprocess
import sys

from reezsynth_engines import FUOUM_REVISION, LEGACY_REVISION, ROOT


def run(command):
    print("\n> " + subprocess.list2cmdline([str(value) for value in command]), flush=True)
    result = subprocess.run([str(value) for value in command], cwd=ROOT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fuoum-source", required=True)
    parser.add_argument("--fuoum-python", required=True)
    args = parser.parse_args(argv)
    source = Path(args.fuoum_source).expanduser().resolve()
    worker = Path(args.fuoum_python).expanduser().resolve()
    environment = worker.parent.parent
    print(f"Supported Trentonom0r3/Ezsynth revision: {LEGACY_REVISION}")
    print(f"Supported FuouM/ReEzSynth revision: {FUOUM_REVISION}")
    print(f"Configured FuouM source: {source}")
    print(f"Configured FuouM worker: {worker}")
    legacy = run([sys.executable, "-X", "utf8", ROOT / "check_reezsynth.py",
                  "--cuda", "--native", "--raft-extension"])
    fuoum = run([sys.executable, "-B", "-X", "utf8", ROOT / "setup_fuoum.py",
                 "--source", source, "--venv", environment, "--check-only", "--neuflow"])
    if legacy or fuoum:
        print(f"\nIncluded engine checks failed (Legacy={legacy}, FuouM={fuoum}).")
        return 1
    print("\nBoth included synthesis engines passed readiness checks. No render was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
