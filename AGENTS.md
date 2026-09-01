# AGENTS.md — entry point for AI coding agents

You are an AI coding agent working in the Orpheus repository. **Read this
file completely before doing anything else.** It is short by design.

After reading the non-negotiables below, follow the **navigation map**
to the deep-dive doc relevant to your task. Don't try to memorise
everything — just know where to look.

---

## The 12 non-negotiables

These are not suggestions. Past agents (and probably you, on previous
sessions) have broken every single one and produced bugs that escaped
all the way to CI or production. If you remember nothing else from
this repo, remember these.

1. **Use `make` targets. Never run `pytest`, `ruff`, `npm test`, or
   `vite build` directly when a make target exists.** CI uses make
   targets; if your local invocation doesn't, you're not testing what
   CI tests. See [`docs/agent-instructions/10-tooling.md`](docs/agent-instructions/10-tooling.md).

2. **Before opening or pushing to a PR, run `make lint` and `make
   test-all` from the repo root.** Or at minimum the per-component
   equivalents for every component you touched. If you skip this, you
   are buying CI debugging time with the user's money.

3. **Stage in batches, not file-by-file.** Make the working tree look
   how you want it, run `git status` ONCE to verify nothing weird is
   creeping in, then `git add -A && git commit`. Don't `git add path1
   && git add path2 && ...` across 10 rounds — it wastes tokens and
   obscures intent. Watch for `.gitignore` silently dropping new
   files (see [`docs/agent-instructions/99-gotchas.md`](docs/agent-instructions/99-gotchas.md)).

4. **Never `git push` without explicit user permission.** Either the
   user asks you to push, or you ask first. Local commits are free;
   pushes trigger CI which costs money. Past sessions have called
   "let me push" at points 1/10 to 1/20th of the way to what the user
   considers shippable. Default to committing locally and accumulating.
   Don't guess when a "natural shipping point" has been reached.

5. **When you add a new agent, you MUST update all of these.** A
   missed one will fail silently (CI won't run tests for it; Dashboard
   won't show its status). See
   [`docs/agent-instructions/30-recipes-adding-agent.md`](docs/agent-instructions/30-recipes-adding-agent.md)
   for the complete checklist.

6. **When you add a new schema field, you MUST update all of:** Pydantic
   model, `CREATE TABLE`, `ensure_schema_updates()` migration,
   `save()` / `save_entity()` INSERT, `_row_to_detection()` /
   `_row_to_entity()` SELECT, round-trip tests. See
   [`docs/agent-instructions/31-recipes-schema-changes.md`](docs/agent-instructions/31-recipes-schema-changes.md).

7. **Don't invent AudioSet mids or model parameters.** Look them up.
   `panns_class_labels_indices.csv` (in the audio-events agent's
   `data/` directory) is canonical. The historical curated CSV had
   wrong indices for 40/45 entries because someone guessed.

8. **All persistent paths use `$ORPHEUS_DATA_ROOT`.** Default
   `/data/orpheus` (Jetson), often `~/data/orpheus` on dev. Never
   hardcode `~/...`. Large model files (>1MB) live in `artifacts/`
   tracked by Git LFS.

9. **Don't bypass safety.** Never `--no-verify`. Never force-push to
   `main` — or to ANY branch that exists on the remote: add commits
   ON TOP of a remote branch, never rewrite it, and `git fetch` +
   check the remote branch state before starting dev. Never `git
   reset --hard` without confirming with the user. Don't delete user
   work to "make the obstacle go away."

10. **Each branch is one PR with many commits.** The PR number is just
    the next available number in the repo, not a count of how many PRs
    exist for this work. Don't create a second PR for the same branch.

11. **Read CLAUDE.md / AGENTS.md / project skill instructions at the
    start of every session.** Don't skim. The user's prior session
    cost was paid because past agents skimmed.

12. **When you add or change a feature, you MUST update the docs in the
    same change** — the [Operator's Manual](docs/operator-manual/index.md)
    (install / config / deploy / run / monitor / troubleshoot) and/or the
    [User Guide](docs/user-guide/index.md) (what the user sees + does in the
    dashboard). Most features touch one; some touch both. These two live in the
    in-repo docs site (MkDocs Material — see [`mkdocs.yml`](https://github.com/scottchronicity/orpheus/blob/main/mkdocs.yml)). A feature
    is **not done** until its docs land with it. Operator-facing → Operator's
    Manual; end-user/dashboard-facing → User Guide. (Architecture/ADR/design docs
    are for *contributors*, a separate audience — they don't substitute for the
    operator/user docs an actual deployer or user reads.) Before you write, read
    [voice & audience](docs/contributing/voice-and-audience.md): one reader per
    page, their words not our labels, and link rather than restate.

---

## Navigation map

Start here when you arrive in this repo. Find the topic relevant to your
task, then read that file. Reading order matters: tooling rules trump
architectural understanding which trumps deployment knowledge.

### Tooling and process (read first when joining)

| File | What it covers |
|---|---|
| [`docs/agent-instructions/10-tooling.md`](docs/agent-instructions/10-tooling.md) | Make targets, venvs, lint, test invocation, the "use make always" rule with concrete commands. |
| [`docs/agent-instructions/11-testing.md`](docs/agent-instructions/11-testing.md) | Test conventions, unit vs integration, conftest, OrpheusConfig-singleton-reset fixture. |
| [`docs/agent-instructions/12-git-and-lfs.md`](docs/agent-instructions/12-git-and-lfs.md) | Branch conventions, commit style, LFS-tracked file types, `.gitignore` gotchas (the `lib/` one), how to verify a file is actually staged. |
| [`docs/agent-instructions/13-ci-cd.md`](docs/agent-instructions/13-ci-cd.md) | The pr-tests.yml workflow structure, what to update when adding components, CodeQL status. |

### Architecture (read when the task touches data flow)

| File | What it covers |
|---|---|
| [`docs/agent-instructions/20-architecture.md`](docs/agent-instructions/20-architecture.md) | Holonic-agents model, monorepo layout, where each component lives, what platforms run what. |
| [`docs/agent-instructions/21-event-bus-and-data-flow.md`](docs/agent-instructions/21-event-bus-and-data-flow.md) | Event-bus topic conventions (NATS/JetStream via the EventBus abstraction), event flow (audio.motion → species.detected → entity), Layer 1/2/3 of the cross-classifier-identity stack. |
| [`docs/agent-instructions/22-schema-and-migrations.md`](docs/agent-instructions/22-schema-and-migrations.md) | Detection / Entity / TaxonomyRef / Equivalence models, additive-migrations pattern, additive-column rules. |

### Recipes (read when adding new things)

| File | What it covers |
|---|---|
| [`docs/agent-instructions/30-recipes-adding-agent.md`](docs/agent-instructions/30-recipes-adding-agent.md) | Step-by-step: every file you must update to add a new orpheus-agent-X. |
| [`docs/agent-instructions/31-recipes-schema-changes.md`](docs/agent-instructions/31-recipes-schema-changes.md) | Step-by-step: every spot you must update when adding a schema field. |
| [`docs/agent-instructions/32-recipes-frontend-page.md`](docs/agent-instructions/32-recipes-frontend-page.md) | Step-by-step: adding a new page or panel to the React UI. |

### Deployment

| File | What it covers |
|---|---|
| [`docs/agent-instructions/40-deployment.md`](docs/agent-instructions/40-deployment.md) | Jetson deploy procedure (points at the operator runbook with cross-referenced details). |
| [`docs/runbooks/cross-classifier-identity-deploy.md`](docs/runbooks/cross-classifier-identity-deploy.md) | The full operator runbook for the current major change. |

### Changes that reach the field station

Every change lands additively so it can be reverted without a migration:
additive schema columns, defaulted config keys, new behavior behind a flag
that defaults off. A change that cannot be backed out by checking out the
previous commit is not ready. See
[`docs/agent-instructions/22-schema-and-migrations.md`](docs/agent-instructions/22-schema-and-migrations.md)
for the schema half and the [runbooks](docs/runbooks/) for the deploy half.

### Gotchas (read when you hit weird behavior)

| File | What it covers |
|---|---|
| [`docs/agent-instructions/99-gotchas.md`](docs/agent-instructions/99-gotchas.md) | Known landmines: `panns_inference`'s hardcoded `~/panns_data/` path, the `.gitignore` `lib/` rule eating frontend files, frame-duration constants people get wrong, etc. Read this BEFORE adding workarounds for "weird library behavior." |

---

## Other documentation in this repo (FYI, not required reading)

**One tree, two audiences.** The `docs/` tree is the documentation — for people and
for you. There is no separate agent doc set to keep in sync: this file holds what is
genuinely agent-specific (the non-negotiables, gates, recipes, tooling rules) and
points at the shared docs for everything else. When you need behavior, config, or
architecture, read the doc a human would read rather than a restatement here.

- **Writing documentation?** Read
  [`docs/contributing/voice-and-audience.md`](docs/contributing/voice-and-audience.md)
  FIRST — who each page is written for, the funnel rule (arrive → orient → jump),
  and where a new page goes. `make guardrails` enforces the nav entry for `docs/designs/` and `docs/adr/`
   only. Every other page is on you — MkDocs logs an omitted page at INFO, which
   `--strict` does not catch.
- **What this release added:** [`docs/whats-new.md`](docs/whats-new.md) — the feature
  list plus which doc explains each one.
- **Humans:** all of the below is browsable as a searchable site —
  `make docs-serve` (local preview); once the owner wires the portal's nginx
  `/docs/` location (owner-gated, not yet deployed) it will be served there too.
  It renders this same `docs/` tree, so **agents keep reading the raw files**
  linked here; this list stays canonical.
- [`CODING_AGENT_CONTEXT.md`](./CODING_AGENT_CONTEXT.md) — the
  comprehensive (640-line) legacy agent guide. Covers the same ground
  as the themed files but in a single long document. Use as a
  reference when you want context that spans multiple themed files;
  the themed files are preferred for "I need to do X" lookups.
- `docs/designs/` — design documents for in-progress / recently-completed
  features (e.g. `cross-classifier-identity.md`, `audio-events-agent.md`).
  Read these when working on the feature in question.
- `docs/adr/` — architectural decision records. Read when proposing
  architectural changes.
- `docs/backlog.json` — the seed for GitHub Issues: outstanding work only,
  with labels, themed milestones, and success criteria. GitHub Issues is where
  work is tracked and discussed; this file is how issues get created and kept
  in step. Don't record finished or abandoned work here. There is one stream:
  anything worth doing in this repo belongs here and becomes a public issue —
  there is no separate internal list. Stories only; where one genuinely blocks
  another, say so with `depends_on`.
- `docs/runbooks/` — operator-facing deployment + tuning procedures.
- `docs/copilot-workspace-instructions/` — auto-loaded by GitHub Copilot
  for file-pattern-matched edits. Different mechanism; Claude / general
  agents should follow this file's navigation map instead.
- Per-agent `README.md` files — component-specific details.

## If something doesn't fit any of the above

Look in `docs/`. If it isn't there, ask the user before assuming.

If you find that an instruction is wrong, broken, or out of date, fix
the doc as part of your work. Future agents will thank you. The user
explicitly wants you to maintain this directory.
