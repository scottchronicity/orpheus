# Orpheus Testing Strategy

How Orpheus is tested: the suites, what each one covers, the conventions to follow when
you add a test, and the fixtures that keep them from interfering with each other. Read
[AGENTS.md](agents-index.md) first for the rules that apply to any change — chiefly that
CI runs `make` targets, so you should too.

To run the whole collective in containers instead of testing a component, see
[the Simulacrum](operator-manual/index.md#3-deployment-topologies).

---

## Testing Framework

- **Framework**: pytest with pytest-asyncio
- **Async mode**: components that need it set `asyncio_mode = auto` in their own
  `pytest.ini` — `orpheus-common` does not have that line. Don't decorate async
  tests; if your component lacks the setting, add it rather than marking every test
- **Coverage**: 70% for most components; `orpheus-common` is 78% and
  `audio-motion` 72%. `codecov.yml` and the `env:` block of `pr-tests.yml` are
  the sources of truth.
- **Mocking**: unittest.mock for external dependencies

---

## File Organization

```
tests/
├── conftest.py              # Shared fixtures
├── test_{module}.py         # Tests for each source module
└── {subdir}/
    ├── __init__.py
    └── test_{feature}.py
```

---

## Fixture Patterns

### Standard Fixtures (conftest.py)

```python
# conftest.py
import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_mqtt_client():
    """Mock MQTT client for testing."""
    with patch("orpheus_common.mqtt.MQTTClient") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client

@pytest.fixture
def mock_config():
    """Mock OrpheusConfig singleton."""
    with patch("orpheus_common.config.OrpheusConfig.get_instance") as mock:
        config = MagicMock()
        config.mqtt.broker_host = "localhost"
        config.mqtt.broker_port = 1883
        mock.return_value = config
        yield config

@pytest.fixture
def temp_data_dir(tmp_path):
    """Temporary data directory for file operations."""
    data_dir = tmp_path / "orpheus"
    data_dir.mkdir()
    return data_dir
```

---

## What to Test

### Required Coverage
- ✅ All public functions and methods
- ✅ Error handling paths
- ✅ Edge cases (empty input, None values, boundaries)
- ✅ MQTT message handling with various payloads
- ✅ Configuration loading with missing/invalid values

### Component-Specific Testing

#### Agents
- Agent lifecycle (startup, shutdown)
- MQTT message processing
- Detection algorithms with known inputs
- File I/O operations
- Model inference (with mocked models)

#### Services
- API endpoints (FastAPI TestClient)
- WebSocket connections
- MQTT integration
- Configuration validation

#### Platform (orpheus-common)
- Configuration loading from various sources
- MQTT client connection/reconnection
- Storage path resolution
- Logging setup

---

## What to Mock

### Always Mock
- ✅ MQTT connections and publishing
- ✅ File system operations (use `tmp_path` fixture)
- ✅ External services and hardware
- ✅ `OrpheusConfig` (unless testing config itself)
- ✅ Time-dependent operations (`time.time()`, `datetime.now()`)
- ✅ Network requests
- ✅ Hardware interfaces (cameras, audio devices)

### Never Mock (Test the Real Thing)
- ❌ Data structures and models
- ❌ Pure functions (no side effects)
- ❌ Internal logic within the unit being tested

---

## Writing tests

General pytest technique is pytest's own documentation, linked under References.
What is specific to Orpheus is in
[11 — Testing conventions](agent-instructions/11-testing.md), whose examples are
real files in this repo.

## Coverage Requirements

### Floors are per-component

70% for most, 78% for `orpheus-common`, 72% for `audio-motion`. Run coverage
locally before committing:

```bash
cd platform/orpheus-common  # or agents/*, services/*
make coverage
```

### Coverage Report

```bash
# Generate an HTML report. Note this bypasses the make target, so it does not
# apply the --cov-fail-under the target supplies -- use it to read the report,
# not to decide whether you pass.
make coverage-audio-motion
cd agents/orpheus-agent-audio-motion && venv/bin/python -m pytest tests/ \
  --cov=orpheus_agent_audio_motion --cov-report=html && open htmlcov/index.html
```

### What Not to Worry About

Some code is OK to exclude from coverage:
- Type checking blocks (`if TYPE_CHECKING:`)
- Defensive assertions that should never execute
- Platform-specific code paths (if testing on one platform)
- `__repr__` and `__str__` methods (unless critical)

---

## Component-Specific Guidance

### Testing Agents

Agents should test:
- Message processing with various valid/invalid payloads
- Graceful handling of MQTT disconnections
- Proper cleanup on shutdown
- Detection algorithms with known inputs/outputs

See agent READMEs for component-specific test examples.

### Testing orpheus-common

Platform library tests should:
- Test all public APIs
- Verify configuration loading from multiple sources
- Test MQTT client reconnection logic
- Validate storage path resolution

See [`platform/orpheus-common/README.md`](https://github.com/scottchronicity/orpheus/blob/main/platform/orpheus-common/README.md) for details.

### Testing Dashboard

Dashboard tests should:
- Use FastAPI TestClient for API endpoints
- Mock MQTT subscriptions
- Test WebSocket message handling
- Validate API response schemas

See [`copilot-workspace-instructions/orpheus-ui.instructions.md`](copilot-workspace-instructions/orpheus-ui.instructions.md) for patterns.

---

## Running Tests

### Local Testing

```bash
# Single component
cd platform/orpheus-common
make test                    # Run tests
make coverage                # Run with coverage

# All components
make test-all                # From repository root
make coverage-all            # Coverage for all
```

### CI Testing

Tests run automatically on:
- Every push to a branch
- Every pull request
- Before merging to main

CI enforces:
- ✅ All tests pass
- ✅ Coverage ≥ 70%
- ✅ Linting passes (ruff)

---

## Debugging Test Failures

### View Detailed Output

```bash
pytest -v                    # Verbose output
pytest -vv                   # Very verbose
pytest -s                    # Show print statements
pytest --pdb                 # Drop into debugger on failure
```

### Run Specific Tests

```bash
pytest tests/test_config.py                           # Single file
pytest tests/test_config.py::test_load_config         # Single test
pytest tests/test_config.py::TestConfig::test_load    # Single class method
pytest -k "mqtt"                                      # Match by name
```

### Capture Logs

```python
def test_with_logs(caplog):
    """Test that captures log output."""
    import logging
    with caplog.at_level(logging.INFO):
        my_function()
    
    assert "Expected log message" in caplog.text
```

---

## Testing Checklist

Before committing code:
- [ ] All new code has tests
- [ ] Tests pass locally (`make test`)
- [ ] Coverage meets the component's floor (`make coverage-<component>`)
- [ ] No test warnings or deprecation messages
- [ ] Tests are focused and descriptive
- [ ] Error paths are tested
- [ ] External dependencies are mocked

---

## End-to-end BDD scenarios (`tests/bdd/`)

Beyond unit/integration tests, `tests/bdd/` is a [behave](https://behave.readthedocs.io/)
suite that validates the **whole cognitive loop** — detection → correlation →
entity_type derivation → corollary-discharge tagging → persistence — as
human-readable Gherkin.

Run it:

```bash
make test-bdd            # runs behave over tests/bdd via the event-correlator venv
```

(`behave` is a dev extra of `orpheus-agent-event-correlator`; `make
install-event-correlator` installs it. The BDD suite imports `orpheus_common`
+ the correlator, which both live in that venv.)

### Layout

- `tests/bdd/features/*.feature` — Gherkin scenarios (one file per domain).
- `tests/bdd/steps/*_steps.py` — step definitions (`@given/@when/@then`).
- `tests/bdd/environment.py` — `before_scenario`/`after_scenario` hooks that wire
  a **fresh, in-process** event-correlator per scenario: a `Mock` event bus
  captures publishes, a tmp SQLite DB receives persistence, and the cluster
  manager is wired exactly like the agent's real `start()`.

### How the drive works (and the one deliberate boundary)

Scenarios call the correlator's **real entry points** (`_on_detection_event`,
`_on_playback_event`), then force-expire clusters with `flush_all()` and run each
built entity through the real `_on_entity_ready` (tag + persist + publish) — so
the assertions run against genuinely-emitted + genuinely-persisted EntityEvents,
deterministically, with no asyncio timer or network.

**Boundary:** the classifier leg (audio chunk → species) is *not* re-run on
synthetic audio — a synthetic sine wave can't be deterministically classified as
a real species, and that leg is already covered by the audio-events tests. So a
scenario **injects the post-classification detection** (the `species_code` +
`TaxonomyRef` a classifier would have emitted) and the synthetic signal is a
generated placeholder. The scenario therefore exercises the correlation/identity
loop deterministically, not the ML.

### Writing a new scenario

1. Add a `Scenario:` to a `.feature` file using existing step phrasings where you
   can.
2. For new phrasings, add `@given/@when/@then` defs in `steps/`. Reuse the
   `_detection(...)` / `_run_pipeline(...)` helpers — `_detection` produces a
   detection dict shaped like the MQTT payload (sensor_id rides in `context`,
   distinct `root_event_id` per sensor).
3. Assert on `context.published` (the captured EntityEvents) and/or
   `context.agent.db.get_entities()`.

`make test-bdd` runs in CI inside the `test-orpheus-agent-event-correlator` job,
followed by `make sim-matrix-ci`.

### Not yet wired

- Cross-modal (audio+video) and non-bird (`Animal.Critter`, etc.) scenarios —
  blocked on those detectors and derivations existing.

---

## References

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio Documentation](https://pytest-asyncio.readthedocs.io/)
- [unittest.mock Documentation](https://docs.python.org/3/library/unittest.mock.html)
- [`AGENTS.md`](agents-index.md) - Core development guidelines
- [`agent-instructions/11-testing.md`](agent-instructions/11-testing.md) - Test conventions in brief
- [`copilot-workspace-instructions/tests.instructions.md`](copilot-workspace-instructions/tests.instructions.md) - Quick reference patterns
