"""Commands and display text for GUI engine checks and maintenance."""
import sys
from pathlib import Path

from reezsynth_engines import (FUOUM_REVISION, LEGACY_REVISION, ROOT,
                               default_runtime)


def configured_runtime(application):
    defaults = default_runtime()
    source = Path(application.get("fuoum_source") or defaults["fuoum_source"]).expanduser().resolve()
    python = Path(application.get("fuoum_python") or defaults["fuoum_python"]).expanduser().resolve()
    return source, python


def version_summary(application):
    source, python = configured_runtime(application)
    return (f"Supported Trentonom0r3/Ezsynth revision: {LEGACY_REVISION}\n"
            f"Supported FuouM/ReEzSynth revision: {FUOUM_REVISION}\n"
            f"GUI Python: {Path(sys.executable).resolve()}\n"
            f"FuouM source: {source}\nFuouM worker: {python}")


def readiness_command(application):
    source, python = configured_runtime(application)
    script = ROOT / "check_reezsynth_engines.py"
    return sys.executable, ["-B", str(script), "--fuoum-source", str(source),
                            "--fuoum-python", str(python)]


def rebuild_command(component, application):
    if component == "legacy":
        return sys.executable, ["-B", str(ROOT / "build_reezsynth_corr.py"), "--install"]
    if component == "fuoum":
        source, python = configured_runtime(application)
        return str(python), ["-B", str(ROOT / "build_fuoum_engine.py"),
                             "--source", str(source), "--force"]
    raise ValueError("Unknown engine maintenance component.")
