# Security policy

## Reporting a vulnerability

Please do not publish exploit details, credentials, private paths, or sensitive
logs in a public issue. Use **Security > Report a vulnerability** on the GitHub
repository when that option is available. If it is unavailable, open a minimal
issue asking the maintainer to establish a private contact channel; omit the
sensitive details until that channel exists.

Include the affected version or commit, the smallest safe reproduction, likely
impact, and any suggested mitigation. Reports about upstream EbSynth, Ezsynth,
FuouM/ReEzSynth, RAFT, NeuFlow, or another dependency may need to be coordinated
with that project's maintainer as well.

There is no formal response-time guarantee while this community project is under
active development. Confirmed issues that could put users at risk should be fixed
or documented before a public release containing the affected code.

## Supported versions

Security fixes currently target the latest commit on `main`. No stable binary
release is published or supported yet.

## Security evidence

The automated and release checks are described in [SECURITY_CHECKS.md](SECURITY_CHECKS.md).
Passing them is evidence against known classes of defects and supply-chain
tampering; it is not a mathematical proof that software is harmless.
