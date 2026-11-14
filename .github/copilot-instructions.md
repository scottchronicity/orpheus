# GitHub Copilot instructions for Orpheus

**Read [`../AGENTS.md`](../AGENTS.md) — it's the canonical entry point
for all AI coding agents in this repo (Claude, Copilot, Cursor, etc.).**

`AGENTS.md` is short by design. It contains:

1. The non-negotiable rules (every one tied to a past incident
   where a coding agent broke something — read these before doing
   anything else).
2. A navigation map to themed deep-dive files in
   [`../docs/agent-instructions/`](../docs/agent-instructions/)
   (tooling, testing, git, CI/CD, architecture, schema, recipes,
   deployment, gotchas).

Before architecture, configuration, runtime or deployment changes, read the
[architecture contract](../docs/ARCHITECTURE.md#architecture-contract) and
[ADR 0020](../docs/adr/0020-portable-capabilities-and-runtime-boundaries.md).
Python/dependency compatibility belongs to each component: currently most agents
use 3.9, the isolated Jetson PANNs worker 3.8, and shared IPC supports 3.8+.
Follow the package metadata and its Ruff target, not a global Python constraint.
Use the [independent review workflow](../docs/agent-instructions/12-git-and-lfs.md#shared-development-and-independent-review);
tests and self-review are not independent acceptance.

This file is a plain-text redirect (not a symlink) so it loads
correctly on Windows checkouts, GitHub's web UI, and Copilot's
auto-loader.

## Component-specific instructions

The directory `../docs/copilot-workspace-instructions/` contains
file-pattern-scoped instructions that Copilot auto-loads when you
edit files matching their `applyTo` patterns. They're quick-reference
cards; the full guidance lives in `../docs/agent-instructions/`.
