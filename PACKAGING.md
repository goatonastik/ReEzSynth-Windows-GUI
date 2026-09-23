# Release candidate packaging

ReEzSynth produces two reviewable Windows artifacts from one exact Git commit:

- `ReEzSynth-<version>-source.zip` is the curated source distribution.
- `ReEzSynth-Windows-<version>.exe` installs that same tree for the current user.

Neither packaging command nor workflow publishes a GitHub release. The manual
workflow uploads short-lived candidate artifacts for clean-machine testing. A
public release remains a separate owner-approved action after the release gates
in `RELEASE_AUDIT.md` pass.

The installer copies application files to the current user's local Programs
directory and creates Start-menu shortcuts. It does not require administrator
rights. Engine and Python dependencies are intentionally a separate, visible
setup step because they download several gigabytes and require Git, Conda, the
CUDA 12.8 toolkit, and Visual Studio 2022 C++ build tools. The finish-page setup
choice is unchecked. Uninstalling removes installed application files and
shortcuts; it does not delete separately created Conda environments or user
projects.

## Build locally

Use a clean checkout at the reviewed commit. Inno Setup 6 or 7 is required for
the `.exe`; source-only packaging needs Git and PowerShell:

```powershell
.\build_release.ps1 -Version 0.1.0-preview.1 -Plan
.\build_release.ps1 -Version 0.1.0-preview.1 -SourceOnly
.\build_release.ps1 -Version 0.1.0-preview.1
```

Artifacts and `SHA256SUMS.txt` are written to ignored `dist/`. The builder stops
on a dirty working tree and records the exact 40-character commit in
`RELEASE_MANIFEST.json`. It inspects the source ZIP and rejects local environments,
diagnostic output, project/render folders, `examples/`, and raster-image formats.
This enforces the owner decision that no bundled source frames, keyframes, masks,
or other example media may ship.

## Candidate validation

1. Verify each artifact against `SHA256SUMS.txt`.
2. Inspect `RELEASE_MANIFEST.json` and confirm its commit is the reviewed HEAD.
3. Extract the source ZIP and inspect its file inventory.
4. Install the `.exe` on a clean Windows test account or machine.
5. Run the visible dependency setup and confirm prerequisite failures are clear.
6. Launch the GUI and render one short generated or tester-owned image/video case
   through both engines.
7. Uninstall and confirm user projects and external Conda environments remain.

The candidate currently contains the tracked runtime DLL, RAFT checkpoints and
the platform-specific correlation wheel. Their provenance and notices are recorded
in `RELEASE_AUDIT.md`; public distribution still requires the final asset decision
and clean-machine validation described there. Installed copies retain the third-party
notices under `licenses/` and `third_party/`; reviewers should inspect those along
with the top-level AGPL license.
