# Release candidate packaging

ReEzSynth produces two reviewable Windows artifacts from one exact Git commit:

- `ReEzSynth-<version>-source.zip` is the curated source distribution.
- `ReEzSynth-Windows-<version>.exe` installs that same tree for the current user.

Neither packaging command nor workflow publishes a GitHub release. The manual
workflow uploads short-lived candidate artifacts for clean-machine testing. A
public release remains a separate owner-approved action after the release gates
in `RELEASE_AUDIT.md` pass.

The latest locally compiled candidate is `0.1.0-preview.2`, bound to reviewed
commit `ff4dcbd2c419e45431229228eed08cb147fbf809`. Its source ZIP SHA-256 is
`acaeac7270eb8d562e8f7d8d6dae7464da6be6748ca97c9f1ac3167d58945bc6`; its
Windows installer SHA-256 is
`bf126d8ad6a7d5ba656a5f42946f65e791269000bccb3a2ce98e87f64e3ff12b`.
These are local testing artifacts, not a published release.

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

The complete external-tester procedure is in `CLEAN_MACHINE_TEST.md`.

1. Verify each artifact against `SHA256SUMS.txt`.
2. Inspect `RELEASE_MANIFEST.json` and confirm its commit is the reviewed HEAD.
3. Extract the source ZIP and inspect its file inventory.
4. Install the `.exe` on a clean Windows test account or machine.
5. Run the visible dependency setup and confirm prerequisite failures are clear.
6. Launch the GUI and render one short generated or tester-owned image/video case
   through both engines.
7. Uninstall and confirm user projects and external Conda environments remain.

The candidate contains the retained, hash-locked runtime DLL, required RAFT
Sintel/Kitti checkpoints and the platform-specific correlation wheel. The unused
RAFT Small checkpoint is excluded. Their accepted stability-first distribution
decision and provenance are recorded in `RELEASE_AUDIT.md`; public distribution
still requires clean-machine validation. Installed
copies retain `THIRD_PARTY_NOTICES.md`, the third-party licenses under `licenses/`
and `third_party/`, and the top-level AGPL license.
