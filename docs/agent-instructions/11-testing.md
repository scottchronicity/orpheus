# 11 — Testing conventions

## Invocation

**Always via `make` targets.** See [`10-tooling.md`](10-tooling.md) for
the rules. Quick reference:

```bash
make test-<component>           # one component
make coverage-<component>       # with coverage
make test-all                   # everything
```

## Test layout

Each component has:

```
<component>/
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # autouse fixtures, shared helpers
│   ├── test_<module>.py        # unit tests, fast
│   └── integration/            # slow tests requiring real models/data
│       ├── __init__.py
│       └── test_*.py
└── pytest.ini                  # testpaths, asyncio_mode, coverage threshold
```

Default: `make test-<x>` runs all of `tests/` including integration.
For agents that have a `tests/integration/` with real-model tests,
those tests must auto-skip when the real model isn't installed (so
CI without LFS pulls still passes).

Shell scripts are tested with bats-core: suites live in `tests/bats/*.bats`
(helpers in `tests/bats/test_helper.bash`), run via `make test-bash` — which
bootstraps pinned bats-core/support/assert clones into the gitignored
`tests/bats/lib/` on first use (deliberately not submodules; see the Makefile
target's comment). Tests must sandbox-copy scripts before running them
(never mutate real repo files).

Pattern for auto-skipping integration tests:

```python
@pytest.fixture(scope="module")
def real_model():
    checkpoint = Path(os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus")) / "models" / "<file>.pth"
    if not checkpoint.exists():
        pytest.skip("Model checkpoint not present — run 'git lfs pull'.")
    ...
```

## OrpheusConfig singleton reset

`OrpheusConfig.get_instance()` caches. Without a reset, tests that
read config see stale state from prior tests.

Every per-component `conftest.py` should have:

```python
import pytest
from orpheus_common.config import OrpheusConfig

@pytest.fixture(autouse=True)
def reset_orpheus_config_singleton() -> None:
    original_instance = OrpheusConfig._instance
    original_dotenv = OrpheusConfig._DOTENV_LOADED
    OrpheusConfig._instance = None
    OrpheusConfig._DOTENV_LOADED = False
    yield
    OrpheusConfig._instance = original_instance
    OrpheusConfig._DOTENV_LOADED = original_dotenv
```

Copy this verbatim from a sibling component's `conftest.py`.

## Coverage thresholds

Thresholds live in two places and they do **not** all agree. No `pytest.ini`
carries one — setting it there does nothing.

- CI sets `COVERAGE_THRESHOLD_<NAME>` in the `env:` block of
  `.github/workflows/pr-tests.yml`: 78 for `orpheus-common`, 72 for
  `audio-motion`, 70 elsewhere.
- The root Makefile's `coverage-<name>` either reads `$(COVERAGE_THRESHOLD)`
  (default **80**, and only `common` and `audio-motion` use it) or hardcodes 70.
- A component's own `make coverage` enforces nothing at all.

Run `make coverage-<component>` from the repo root. For `common` and
`audio-motion` it is stricter than CI, which is the safe direction.

Don't lower a threshold to avoid writing tests. Add the missing
tests.

## Test name conventions

- `test_<thing>_<expected behavior>` — what you're testing + what
  should happen.
- Class-grouped for related cases:
  `class TestX: def test_y_with_z_condition(self): ...`

## Mocking vs real dependencies

- Unit tests: mock external systems (MQTT, DB, ML model). Use
  `unittest.mock.MagicMock` or `pytest-mock`.
- Integration tests: use real dependencies where possible. The
  audio-events agent has `DeterministicFakeSED` for unit tests AND
  `PANNsCnn14SED` for integration tests against a real checkpoint.
- For DB tests: use `tmp_path` to create a temporary SQLite file;
  never write to `/data/orpheus`.

## Pytest asyncio

`pytest.ini` already has `asyncio_mode = auto` for the agents that
need it. Don't add `@pytest.mark.asyncio` to every async test —
asyncio_mode=auto handles it.

## Shared test fixtures

Per-component conftests handle the common ones. For repo-wide fixtures
(rare), put them in `platform/orpheus-common/tests/conftest.py` and
they're available to every consumer's tests.

## Soup-to-nuts integration tests

For features that span multiple components (e.g., cross-classifier
identity which spans audio-motion → bird → correlator → DB), write
an integration test that simulates the full pipeline using the
ClusterManager directly. Pattern: `agents/orpheus-agent-event-correlator/tests/test_soup_to_nuts.py`.

For features that span MQTT, use the live-pump harness:
`tools/integration/pump_fake_animal_events.py`. This is a manual
smoke test, not a pytest run — used pre-deploy.

## When to add an integration test under `tests/integration/`

- The component loads a real ML model. → Yes (auto-skipped without
  checkpoint).
- The component does heavy filesystem or DB work that's hard to mock
  cleanly. → Maybe.
- The component is pure logic over Pydantic models. → No, unit tests
  suffice.

## Don't add `@pytest.mark.slow` or similar

We don't tier tests beyond "unit vs integration." If a test is slow,
move it to `tests/integration/`. If it's fast enough for `tests/`,
keep it there.
