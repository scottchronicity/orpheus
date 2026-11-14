# Agent architecture reference

The canonical entry point for every coding agent is [AGENTS.md](https://github.com/scottchronicity/orpheus/blob/main/AGENTS.md)
at the repository root (rendered in the site as [Agent entry point](agents-index.md)).
Read it completely before work. This legacy path remains a redirect so existing
links reach the same contracts instead of a second, drifting instruction set.

- [Architecture contract](ARCHITECTURE.md#architecture-contract): capability,
  model, backend, IPC, runtime and resource ownership; domain invariants.
- [ADR 0020](adr/0020-portable-capabilities-and-runtime-boundaries.md): portability
  and independent runtimes; related ADRs preserve their decision history.
- [Agent instructions](agent-instructions/README.md): tooling, tests and recipes.
- [Shared development and independent review](agent-instructions/12-git-and-lfs.md#shared-development-and-independent-review):
  shared history, hardware validation evidence and draft PR checkpoints.
- [Operator's Manual](operator-manual/index.md): configuration and deployment.

Python compatibility is per component. Read the changed package's metadata,
constraints and Makefile; the Jetson PANNs CUDA runtime does not set Orpheus's
Python version. No platform-wide sensor count or scheduler is implied.
