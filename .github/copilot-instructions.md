# GitHub Copilot instructions for Orpheus

**Read [`../AGENTS.md`](../AGENTS.md) — it's the canonical entry point
for all AI coding agents in this repo (Claude, Copilot, Cursor, etc.).**

`AGENTS.md` is short by design. It contains:

1. The 11 non-negotiable rules (every one tied to a past incident
   where a coding agent broke something — read these before doing
   anything else).
2. A navigation map to themed deep-dive files in
   [`../docs/agent-instructions/`](../docs/agent-instructions/)
   (tooling, testing, git, CI/CD, architecture, schema, recipes,
   deployment, gotchas).

A critical hard rule: this project is locked to **Python 3.9.5** for
Jetson hardware compatibility. Do not suggest Python 3.10+ syntax
(`match/case`, `X | None` union syntax, etc.). Each component has
ruff configured with `target-version = "py39"` to back this up.

This file is a plain-text redirect (not a symlink) so it loads
correctly on Windows checkouts, GitHub's web UI, and Copilot's
auto-loader.

## Component-specific instructions

The directory `../docs/copilot-workspace-instructions/` contains
file-pattern-scoped instructions that Copilot auto-loads when you
edit files matching their `applyTo` patterns. They're quick-reference
cards; the full guidance lives in `../docs/agent-instructions/`.
