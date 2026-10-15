# Support tools

`diagnostics/` contains optional rendering, quality, memory, and release checks.
These tools can create renders or use the GPU; run them deliberately, separately
from the maintained unit tests. Reports remain under the application root's
ignored `diagnostic_outputs/` directory.

From the repository or installed application folder, for example:

```powershell
python -B tools/diagnostics/diagnose_reezsynth_engines.py --help
python -B tools/diagnostics/diagnose_reezsynth_stability.py --plan
```

Direct execution by absolute path also works from another working directory.
See [the main guide](../README.md) for individual diagnostic commands and
[the documentation index](../docs/README.md) for feature-specific checks.

`build/` holds the inherited native EbSynth build scripts. They are preserved
unchanged and expect the upstream native source checkout (`src/`, `include/`,
and output directories) as the working directory. They are not the standard
ReEzSynth installer or engine-setup workflow; see the Windows setup guide for that.
