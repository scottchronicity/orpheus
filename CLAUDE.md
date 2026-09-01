# Claude Code instructions for Orpheus

**Read [`AGENTS.md`](./AGENTS.md) — it's the canonical entry point for
all AI coding agents in this repo (Claude, Copilot, Cursor, etc.).**

`AGENTS.md` is short by design. It contains:

1. The non-negotiable rules (deliberately not counted here — AGENTS.md's
   numbered list is canonical and guardrails-checked; every rule is tied
   to a past incident where a coding agent broke something — read them
   before doing anything else).
2. A navigation map to themed deep-dive files in
   [`docs/agent-instructions/`](./docs/agent-instructions/) (tooling,
   testing, git, CI/CD, architecture, schema, recipes, deployment,
   gotchas).

The long-form comprehensive guide at
[`CODING_AGENT_CONTEXT.md`](./CODING_AGENT_CONTEXT.md) is still
present as a reference for context that spans multiple themed files;
the themed files supersede it for "I need to do X" lookups.

This file is a plain-text redirect (not a symlink) so it loads
correctly on Windows checkouts, GitHub's web UI, and every agent's
auto-loader.
