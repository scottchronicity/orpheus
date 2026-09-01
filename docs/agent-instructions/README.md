# Agent instructions

Themed deep-dives for anyone changing Orpheus, human or coding agent. Start at
[`AGENTS.md`](../agents-index.md) for the rules that apply to every change; these
pages are what it routes to. Numbered by theme, not by reading order — open the
one that matches the work.

| Page | Read it when |
|---|---|
| [00 — Non-negotiables](00-non-negotiables.md) | Before anything else. Twelve rules, most tied to a specific past incident |
| [10 — Tooling](10-tooling.md) | You are about to run a command. Which make target, which venv, and why never the raw tool |
| [11 — Testing conventions](11-testing.md) | Writing a test. Layout, the auto-skip pattern, and where the coverage floors really live |
| [12 — Git and LFS](12-git-and-lfs.md) | Staging, committing, or adding a large file |
| [13 — CI/CD](13-ci-cd.md) | Adding a component, or working out why a job did not run |
| [20 — Architecture](20-architecture.md) | Orientation: what the components are and which constraints are hard |
| [21 — Event bus and data flow](21-event-bus-and-data-flow.md) | Publishing or subscribing to anything |
| [22 — Schema and migrations](22-schema-and-migrations.md) | Touching the database or a persisted model |
| [30 — Recipe: adding an agent](30-recipes-adding-agent.md) | Adding an agent. A checklist, not a guide — every missed entry breaks something |
| [31 — Recipe: schema changes](31-recipes-schema-changes.md) | Adding a field that has to survive a restart |
| [32 — Recipe: frontend page](32-recipes-frontend-page.md) | Adding a dashboard page or panel |
| [40 — Deployment](40-deployment.md) | Orientation for deploy work; the runbooks own the procedures |
| [99 — Gotchas](99-gotchas.md) | Something behaved strangely and you suspect the environment rather than your change |
