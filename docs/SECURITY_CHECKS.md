# Security checks and release evidence

No automated scanner can prove that a program is harmless. ReEzSynth instead
collects independent, repeatable evidence and states what each check can and
cannot establish.

## Checks on every relevant change

- **Maintained tests** exercise the supported GUI and worker behavior on a clean
  GitHub-hosted Windows runner.
- **CodeQL** analyzes Python source and GitHub Actions for known security and
  correctness patterns, using the extended security query set.
- **Bandit** scans every tracked Python file for medium-or-higher severity findings
  with medium-or-higher confidence. Ignored environments and local diagnostics are
  excluded by deriving the input list from Git.
- **Dependency review** blocks pull requests that introduce dependencies with a
  known vulnerability rated moderate or higher.
- **pip-audit** checks the pinned CPU test dependency set against published Python
  vulnerability records. PyTorch and torchvision are installed separately from
  their CPU wheel index and are outside this job, as are the GPU, CUDA, Conda,
  downloaded-model, and native-library dependencies. Those components still
  require the release-specific audit below.
- **OpenSSF Scorecard** reports repository and supply-chain practices. All workflow
  actions are pinned to full commit identifiers, and Dependabot proposes reviewed
  updates to those pins.

These checks detect documented patterns and known vulnerabilities. They do not
prove author intent, find every novel vulnerability, or clear third-party rights.

## Required evidence for a public downloadable release

For the exact archive or installer proposed for publication:

1. Satisfy every provenance and redistribution gate in [RELEASE_AUDIT.md](RELEASE_AUDIT.md).
2. Build from the reviewed commit in a clean, disposable environment. Record the
   commit, tool versions, inputs, and build log.
3. Generate a software bill of materials for the files actually shipped, including
   Python, native, CUDA, model, and bundled FFmpeg components.
4. Publish SHA-256 checksums and a GitHub artifact attestation that binds the
   downloadable artifact and SBOM to the repository, workflow, and commit.
5. Scan the unpacked artifact with an up-to-date Microsoft Defender installation.
   Preserve the engine version, signature version, command, timestamp, and result.
6. Install and run it in a clean Windows Sandbox or virtual machine. Observe
   processes, filesystem writes, persistence changes, and network connections;
   run a short render through each included engine and uninstall or remove it.
7. Have a reviewer compare the packaged inventory with the approved source and
   confirm that it contains no credentials, private paths, render inputs, caches,
   diagnostic evidence, development environments, or unapproved binaries.
8. Publish the checksums, SBOM, attestation-verification instructions, scan summary,
   known limitations, third-party notices, and exact source tag with the release.

An attestation proves where an artifact came from; it does not prove that the
artifact is secure. Malware scanning also cannot replace source review and
clean-machine behavior testing. A public release remains blocked until these
checks pass and the owner explicitly approves publication.
