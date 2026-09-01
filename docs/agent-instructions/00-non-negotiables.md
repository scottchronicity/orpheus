# 00 — Non-negotiables

The 12 rules from `AGENTS.md` at the repo root, expanded with the
incident that motivated each.

If you're reading this file alone, **the AGENTS.md at the repo root
is the canonical entry point** — read it first.

## 1. Use `make` targets

Never `pytest` / `ruff` / `npm test` / `vite build` directly when a
`make` target exists. CI uses `make`; you must too.

**Incident**: Agent ran `venv/bin/ruff check src/ tests/` and saw 0
errors. Pushed. CI ran `make lint-audio-events` (the agent's stricter
pyproject.toml) and found 21 errors. Round-trip wasted.

**The fix**: `make lint-<component>` and `make test-<component>` for
everything you touched. From the repo root, the same effect:
`make lint && make test-all`.

Detail: [`10-tooling.md`](10-tooling.md).

## 2. Run lint + tests before push

Before opening a PR or pushing to one, run the equivalent of what CI
will run. If you can't reproduce CI failure locally, that's itself a
problem — don't push "try fix" commits to debug.

Detail: [`13-ci-cd.md`](13-ci-cd.md).

## 3. Stage in batches, not file-by-file

Make the working tree look how you want it (no junk, no stray
artifacts). Then run `git status` ONCE to sanity-check. Then
`git add -A && git commit`. Skip the 10-round per-file dance — it
wastes tokens and obscures intent.

The `.gitignore` Python `lib/` rule has silently caught new frontend
`src/lib/*` files. `git add` errors but `git add -A` will silently
skip them. So you ALSO need to actually look at the post-add state
and verify all your intended new files made it in.

**Incident**: `speciesLinks.ts` was created locally, imported from
two pages, tested via vitest, BUT silently `.gitignore`'d. CI failed
with `Failed to resolve import "../lib/speciesLinks"`. Wasted CI run.

**The pattern**:
```bash
# Build / fix things
... do work ...

# Look at what's there. Is the directory in the state you want?
ls path/you/edited

# One git status to sanity check
git status

# If anything new shows up that you DIDN'T expect, investigate
# (gitignore? real new file? leftover scratch?).
git check-ignore -v <file>   # if you suspect ignore

# Batch-add and commit
git add -A
git commit -m "..."
```

Detail: [`99-gotchas.md`](99-gotchas.md), [`12-git-and-lfs.md`](12-git-and-lfs.md).

## 4. Never `git push` without explicit user permission

Either the user asks you to push, or you ask first. Local commits are
free; pushes trigger CI, which costs money. Past Claude sessions have
called "let me push" at points 1/10 to 1/20th of the way to what the
user considers shippable. Stop guessing about "natural shipping
points" — they aren't yours to declare.

**Incident**: Repeated pushing during the cross-classifier-identity
work caused multiple CI runs per session-day, including some that
re-ran the entire matrix to fix one missed file in a previous push.
User explicitly called this out.

**The rule**: Commit locally freely. Push only when (a) the user
explicitly asks ("push it," "open the PR," "ship it") or (b) you
ask permission first ("Want me to push?"). Default is to keep
commits local.

## 5. Adding a new agent touches a dozen files across the repo

`make install` won't install the agent. CI won't test it. Dashboard
won't show its status. None of this is warned. All silent.

`make guardrails` now catches the mechanical half of this — a new agent
missing from the Makefile build set, its systemd unit, or the CI workflow
fails the check (it also runs in CI). It can't verify the dashboard/config
wiring, so the recipe is still the source of truth.

Detail: [`30-recipes-adding-agent.md`](30-recipes-adding-agent.md).

## 6. Adding a schema field updates 9+ places

A missed step is a silent persistence bug — you save successfully,
read back returns None.

Detail: [`31-recipes-schema-changes.md`](31-recipes-schema-changes.md).

## 7. Don't invent AudioSet mids

Look them up in
`agents/orpheus-agent-audio-events/src/orpheus_agent_audio_events/data/panns_class_labels_indices.csv`.

**Incident**: Curated AudioSet CSV had wrong indices for 40/45
entries because someone built it from a different revision. PANNs
emits Crow at index 117; the CSV said 67. `post_process()` filtered
EVERY corvid detection silently because `allowed_class_indices`
didn't match. Same bug pattern in `BIRD_LIKE_AUDIOSET_MIDS` (Bird
Correlation dashboard) — three mids wrong, one didn't exist.

**The fix**: every AudioSet mid in code must be verified against the
canonical CSV. If you find a mid in a comment, README, or PANNs doc,
double-check.

## 8. Use `$ORPHEUS_DATA_ROOT`

Never hardcode `~/...` or `/data/orpheus`. Code runs on Jetson (where
`/data/orpheus`) and Mac dev (where `~/data/orpheus`) — must work
on both.

Large model files (>1MB) go in `artifacts/` and get auto-tracked by
LFS via `.gitattributes`.

## 9. No `--no-verify`, no force-push to shared branches, no `git reset --hard`

Without explicit user confirmation. Don't delete user work to clear
an obstacle.

"Shared" means `main` AND any branch that exists on the remote — even
your own feature branch. Add commits ON TOP of the remote branch;
never rewrite its history. Rebase-then-force-push is reserved for
branches that have never been pushed. Before starting dev, `git
fetch` and check the remote branch state so local work never diverges
from commits the owner may have pushed.

**Incident**: an agent developed on a stale local copy of a working
branch and overwrote the remote. Owner: "absolutely dont overwrite
the remote branch. you should be adding ON TOP OF IT. you should have
checked before you started dev."

Detail: [`12-git-and-lfs.md`](12-git-and-lfs.md).

## 10. One PR per branch

Branch's work = one PR with many commits. The PR number is just the
next available number; doesn't imply multiple PRs for the same work.

## 11. Read this directory at session start

Don't skim. The user's prior session cost was paid because past
agents skimmed. If you remember nothing else from this list, at least
remember to come back to this directory when you're confused.

## 12. Document every feature in the Operator's Manual / User Guide

**Motivating reality:** the docs site grew an Operator's Manual and a User
Guide *after* a pile of features had already shipped, so it had to be
back-filled — exactly the drift this rule exists to prevent. Treat the docs
as part of the feature, not a follow-up.

When you add or change a feature, update — in the SAME change — the
[Operator's Manual](../operator-manual/index.md) and/or the
[User Guide](../user-guide/index.md):

- **Operator's Manual** — anything about installing, configuring, deploying,
  running, monitoring, or troubleshooting a deployment (incl. every runbook).
- **User Guide** — anything an end-user sees or does in the dashboard (pages,
  panels, filters, charts, interactions).

Most features touch one; some touch both. Both live in the in-repo docs site
(MkDocs Material, `mkdocs.yml`) — build it with `make docs-build`. A feature is
**not done** until its docs land with it. Architecture/ADR/design docs are for
*contributors* and do **not** substitute for the operator/user docs a real
deployer or user reads.

The recipes encode this per change-type: [adding an agent](30-recipes-adding-agent.md)
and [adding a frontend page](32-recipes-frontend-page.md) each end with the doc step.

## See also

The rest of [`docs/agent-instructions/`](.). Each file is themed; the
README at the repo root (`AGENTS.md`) is the navigation map.
