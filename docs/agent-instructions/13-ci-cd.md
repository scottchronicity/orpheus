# 13 — CI/CD: how `.github/workflows/pr-tests.yml` is structured

## The workflow at a glance

The active workflow files in `.github/workflows/`:

| File | Triggers | What it does |
|---|---|---|
| `pr-tests.yml` | PRs + push to main | Lint + test every component (selective via path filter) |
| `codeql.yml` | PRs + push to main | CodeQL security scan |
| `release.yml` | tags | Release pipeline |
| `scorecard.yml` | scheduled | OSSF Scorecard |
| `docs.yml` | PRs + push to main | Builds the MkDocs site; deploys to Pages only from the public repo's `main`. `pr-tests.yml` also has a `docs-build` job gated on the `docs` filter — the two overlap, and `docs.yml` is the one that publishes. |
| `stale.yml` | scheduled | Mark stale issues |

For day-to-day agent work, only `pr-tests.yml` matters.

## `pr-tests.yml` structure

The workflow is built around a per-component selective-execution
pattern using `dorny/paths-filter`. Flow:

1. **`changes` job** — runs the path filter. Outputs one boolean per
   component: was anything in that component's directory changed?
2. **`check-dependencies` job** — runs if ANY component changed.
   Verifies the dependency-pin files are consistent across components.
3. **Per-component test jobs** — each one runs IF that component
   changed OR `common` changed OR `workflow` changed OR `root-config`
   changed. Each is gated by `needs: [changes, check-dependencies]`
   so the path filter runs first.
4. **`ci-complete` aggregator** — at the very end. Lists every
   test job as a dependency; succeeds only if all required jobs
   passed or were legitimately skipped.

There is also a standalone **`guardrails` job** that runs on every PR
(NOT gated on changed paths — a pure-docs PR must still be checked). It
runs `make guardrails` (`scripts/check_guardrails.py`, stdlib-only), which
statically enforces the mechanically-checkable non-negotiables: every
`agents/orpheus-agent-*` is wired into the Makefile build set + a systemd
unit + this workflow (#5), every `docs/designs/*` and `docs/adr/*` is in
`mkdocs.yml` so it can't 404 (#12-adjacent), and the "N non-negotiables"
count agrees across `AGENTS.md` and `00-non-negotiables.md` (#11). Run it
locally with `make guardrails` before you push. If a design doc is
deliberately not a page, add it to `NAV_EXEMPT` in the script.

## When you add a new component

You MUST touch every place in the list below. Missing any one of them
silently breaks the workflow for your component.

1. **`env:` block** — add a `COVERAGE_THRESHOLD_<NAME>` constant.
2. **`changes` job `outputs:` block** — add `<name>: ${{
   steps.filter.outputs.<name> }}`.
3. **`changes` job `filters:`** — add:
   ```yaml
   <name>:
     - 'agents/orpheus-agent-<name>/**'
   ```
   (or the path glob for your component).
4. **`check-dependencies` job `if:` condition** — add `needs.changes.outputs.<name> == 'true' ||`.
5. **A new `test-orpheus-agent-<name>` job** — copy from an existing
   sibling. Adjust:
   - `name`
   - `if:` condition
   - `make install-<name>` / `make lint-<name>` / `make
     coverage-<name>` commands
   - `flags:` for Codecov
   - artifact `name` and `path`
6. **`ci-complete` aggregator `needs:` list** — add
   `- test-orpheus-agent-<name>`.

See [`30-recipes-adding-agent.md`](30-recipes-adding-agent.md) for the
complete cross-file checklist when adding an agent.

## CodeQL status

CodeQL workflow runs on PRs but currently requires "Code scanning"
to be enabled in the GitHub repo settings (Security → Code security
and analysis → enable Code Scanning). When it's not enabled, the
`Analyze (python)` and `Analyze (javascript-typescript)` checks
report "Code scanning is not enabled" and fail. This is a settings
issue, not a code issue. Don't try to fix it from code.

## Frontend tests in CI

The orpheus_ui test job runs BOTH the Python backend's pytest AND the
frontend's vitest — but CI calls the two halves separately, as
`make -C backend coverage` and `make -C frontend test-coverage`, plus
`make build-frontend` and `make test-e2e`. Locally,
`make -C services/orpheus_ui test` runs the two unit suites but neither
the e2e leg nor the coverage gates. If you change frontend code without backend changes, the
job still runs (because `ui` filter matches `services/orpheus_ui/**`).

`make build-frontend` does run in CI, as the setup step for the Playwright
end-to-end suite (`make test-e2e`), so a build break is caught. Running
`make -C services/orpheus_ui/frontend build` locally is still the faster way to
find one.

## Codecov

Each component uploads its `coverage.xml`. The `flags:` field tags
the upload by component, so the Codecov dashboard can show per-component
coverage trends. Don't change flag names — historical data is keyed
by them.

`fail_ci_if_error: false` — Codecov upload failures don't fail CI.
Codecov is observability, not gate.

## Don't push to debug CI

When CI fails, reproduce locally first:

1. Find what command failed (the log shows the failing `make ...`
   command).
2. Run that exact command locally.
3. Fix it.
4. Re-run locally to verify.
5. Push once.

Pushing a "try this" commit per fix attempt costs the user real
money in compute time and your time in waiting. See [`10-tooling.md`](10-tooling.md)
for the "use make targets" rule that makes local-equals-CI possible.
