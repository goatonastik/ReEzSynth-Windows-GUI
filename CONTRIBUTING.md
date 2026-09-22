# Contributing to ReEzSynth

Contributions that improve reliability, accessibility, documentation, testing,
performance, or rendering quality are welcome. Start with an issue for changes
that alter the user workflow or the relationship with an upstream engine. Small
fixes may go directly to a pull request.

## Licensing and attribution

The repository is licensed under the GNU Affero General Public License version 3.
By submitting a contribution, you agree that it may be distributed under that
license. You retain copyright in your contribution; this project does not require
copyright assignment.

Only submit work you have the right to contribute. Identify copied or adapted
code, model weights, artwork, test media, and other assets in the pull request,
including their source, exact revision, and license. Preserve upstream copyright
and license notices. Do not describe ReEzSynth as an official EbSynth,
Trentonom0r3/Ezsynth, or FuouM/ReEzSynth release.

Do not commit credentials, personal render data, generated outputs, local engine
environments, caches, or diagnostic logs. Test media needs explicit redistribution
permission, not merely permission to use it privately.

## Development checks

1. Create a topic branch from `main`.
2. Keep the change focused and update relevant documentation.
3. Run `python -B run_maintained_tests.py` in the supported Python 3.11 environment.
4. Run the checks in [SECURITY_CHECKS.md](SECURITY_CHECKS.md) when the change affects
   setup, subprocess execution, downloads, dependencies, or release packaging.
5. Open a pull request describing the behavior change, validation performed, and
   any third-party material introduced or changed.

Pull requests run maintained tests, CodeQL, Bandit, dependency review, and a
known-vulnerability audit. A passing result does not override the release gates
in [RELEASE_AUDIT.md](RELEASE_AUDIT.md).
