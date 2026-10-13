# Clean Windows candidate test

Use this procedure on a Windows machine or test account that has never run this
ReEzSynth checkout. Do not use private footage; the diagnostics generate their own
inputs. Record Windows, GPU, driver and installed prerequisite versions with the
result.

## 1. Verify the candidate

Keep the installer, `SHA256SUMS.txt`, and `RELEASE_MANIFEST.json` together.

1. Confirm that the manifest's commit is the reviewed candidate commit and that
   `release_published` is `false`.
2. Calculate the installer's SHA-256 with `Get-FileHash` and compare it with
   `SHA256SUMS.txt`.
3. Check the installer with Windows Security or the organization's normal malware
   scanner. Record the product/version and result; a scan is evidence, not proof
   that arbitrary software is safe.

## 2. Install without dependencies

1. Run the installer as a normal user. It should install below the current user's
   local Programs directory without requesting administrator privileges.
2. Clear the checked large dependency-install option on the finish page for this
   initial missing-dependency launch test.
3. Confirm that the Start-menu application, dependency setup, documentation and
   uninstall shortcuts exist.
4. Launch ReEzSynth. It should report missing dependencies clearly rather than
   downloading or modifying an engine silently.

## 3. Install and verify dependencies

Follow `INSTALL_WINDOWS.md` and use the Start-menu prerequisite/dependency setup
shortcut. Confirm it installs or preserves, in order, Git, Miniforge/Conda, Visual
Studio 2022 C++ tools and the CUDA 12.8 toolkit before installing the two engine
environments. It can download several gigabytes and can request administrator
approval for system prerequisites.

After setup completes, run from the installed directory:

```powershell
.\run_reezsynth.bat check_reezsynth.py --gui-smoke --cuda --native
.\run_reezsynth.bat check_reezsynth_engines.py --fuoum-source engine_sources\fuoum_reezsynth --fuoum-python .engine_envs\fuoum\Scripts\python.exe
```

For Legacy tests that require the supplied transparent RGBA keyframe to appear
pixel-exactly at its numbered output frame, explicitly choose **Exact output** under
Legacy keyframe preservation. **Current behavior** remains the compatibility default
and is expected to retain the original blend assembly rather than guarantee this
acceptance condition.

Both commands must pass. Confirm that the runtime-asset check reports the expected
DLL, Sintel/Kitti checkpoints and correlation wheel without a hash mismatch.

## 4. Exercise both engines

1. Run a short generated image diagnostic through Legacy and FuouM.
2. Run a short generated video diagnostic through Legacy and FuouM at native
   generated resolution.
3. Verify completion markers, output frame count and dimensions, exact styled-key
   landings, previews, and video export when enabled.
4. Cancel one running job, restart the application, and confirm the queue remains
   coherent. Do not recover or overwrite a job without the normal confirmation.
5. Close the application after work completes and confirm that workers exit.

Record failures with the command, engine, selected backend, output manifest and
log. Do not share generated queue records without checking them for absolute local
paths.

## 5. Paths, restart and uninstall

1. Repeat one short job using project and output paths that contain spaces.
2. Restart Windows, launch ReEzSynth again, and rerun the read-only engine check.
3. Create a disposable project outside the installation directory.
4. Uninstall ReEzSynth. Confirm that application files and shortcuts are removed,
   while the external project, separately created Conda environments, and shared
   prerequisites remain.

## Acceptance

The candidate passes only if installation, both engine checks, both short renders,
restart, paths with spaces and uninstall all succeed without corrupting external
projects or replacing a pre-existing environment. Report the exact candidate hash
and manifest commit. Clean-machine success does not publish or authorize a release.
