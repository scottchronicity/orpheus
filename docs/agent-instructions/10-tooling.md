# 10 — Tooling: make targets, venvs, the "use make" rule

## TL;DR

**Use `make` targets for everything that has a make target. Never run
`pytest`, `ruff`, `npm test`, `vite build`, or `npm run lint` directly
when a make equivalent exists.**

Why: CI uses `make` targets. If you don't, your local checks run with
different rules / different deps / different paths than CI, and you'll
push code that fails CI for reasons your local checks couldn't catch.

This is the #1 source of agent-induced CI churn in this repo. Past
agents have:
- Run `venv/bin/ruff check src/ tests/` and seen 0 errors locally,
  then watched 21 ruff errors blow up in CI because the agent's
  `pyproject.toml` enables strict rule sets (`S`, `PT`, `N`, `PTH`)
  that `ruff` doesn't pick up unless invoked through the agent's
  Makefile.
- Run `npm test` and seen pass locally, then watched the frontend CI
  fail with `Failed to resolve import "../lib/speciesLinks"` because
  the file was `.gitignore`'d.

## The rules

### Pick the right target for your scope

| Scope | Command (from repo root) |
|---|---|
| Run all tests across all components | `make test-all` |
| Run tests for one component | `make test-<component>` (e.g. `make test-audio-events`) |
| Run coverage for one component | `make coverage-<component>` |
| Lint one component | `make lint-<component>` |
| Lint everything | `make lint` |
| Format one component | `make format-<component>` |
| Install all components | `make install` |
| Install one component | `make install-<component>` |

### Per-component make targets

Each component has its own `Makefile` with the same set of targets:

| Target | Does |
|---|---|
| `make install` | Set up venv + install deps |
| `make test` | Run pytest |
| `make coverage` | Run pytest with coverage |
| `make lint` | Run ruff (component's strict rule set) |
| `make format` | Run ruff --fix + ruff format |
| `make clean` | Remove venv + caches |
| `make install-service` | Install the systemd unit (sudo required) |

Invoke either way:
```bash
# From repo root, via top-level Makefile
make test-audio-events

# OR from inside the component, equivalent
cd agents/orpheus-agent-audio-events && make test
```

Both run the same ruff config and the same pytest config. They do **not** all
run the same coverage threshold — see
[Coverage thresholds](11-testing.md#coverage-thresholds), which is stricter
locally than in CI for two components. **Just don't bypass `make`.**

### Pre-PR checklist (the actual sequence)

```bash
# 1. From repo root: run lint + tests for everything you touched
make lint                          # all components
# OR for specific touched components:
make lint-<component> [lint-<other-component> ...]

make test-all                      # all components
# OR:
make test-<component> [test-<other-component> ...]

# 2. For touched UI components:
cd services/orpheus_ui/frontend && npx tsc --noEmit  # type-check too

# 3. Verify nothing is untracked
git status
# If anything new appears here, ask why — .gitignore might be eating
# something you need.

# 4. Verify staged files are what you expect
git diff --cached --stat

# 5. Only THEN commit + push.
```

## Frontend specifics

The frontend has its own test + lint patterns:

```bash
make -C services/orpheus_ui/frontend lint test build
npx tsc --noEmit        # the one acknowledged exception: no make target exists
```

When changing frontend files: `npm test` is necessary but not
sufficient. `tsc --noEmit` catches type errors; `npm run build` catches
"file not found" errors from imports. **Run all three before pushing.**

## CI workflow file

`.github/workflows/pr-tests.yml` defines exactly what runs. To see
what would run on a PR for a given file change, look at the
`changes` job's filter list. If you add a new component, the
`changes` filter needs a new entry — see
[`30-recipes-adding-agent.md`](30-recipes-adding-agent.md).

## When to bypass `make` (rare)

- Quickly running a single test by name during development:
  `cd <component> && venv/bin/pytest tests/test_x.py::TestY -v`.
  Acceptable for fast iteration. Run `make test-<component>` before
  committing.
- Investigating a specific failure: same.

**Do not** bypass `make lint` to avoid fixing a lint failure. CI will
catch it. Just fix the lint.

## See also

- [`11-testing.md`](11-testing.md) for test conventions.
- [`13-ci-cd.md`](13-ci-cd.md) for how the pr-tests.yml workflow is structured.
- [`30-recipes-adding-agent.md`](30-recipes-adding-agent.md) for the list of make targets you need to add when introducing a new agent.
