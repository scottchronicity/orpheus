# Orpheus Testing Strategy

**See [`CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md) for core development guidelines.**

This document provides comprehensive testing patterns and strategies for the Orpheus platform.

---

## Testing Framework

- **Framework**: pytest with pytest-asyncio
- **Async mode**: `asyncio_mode = "auto"` in pytest.ini
- **Coverage**: 70% minimum (enforced by CI)
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

## Test Patterns

### Test Class Organization

```python
class TestMyFeature:
    """Tests for MyFeature class."""
    
    def test_happy_path(self, mock_config):
        """Test normal operation."""
        result = my_function(valid_input)
        assert result.status == "success"
    
    def test_error_handling(self, mock_config):
        """Test behavior with invalid input."""
        with pytest.raises(ValueError):
            my_function(invalid_input)
    
    def test_edge_case(self, mock_config):
        """Test boundary conditions."""
        result = my_function(edge_case_input)
        assert result is not None
```

### Async Test Pattern

```python
import pytest

@pytest.mark.asyncio
async def test_async_operation(mock_config):
    """Test asynchronous operation."""
    result = await async_function()
    assert result is not None
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

## Testing Best Practices

### 1. Test One Thing at a Time

```python
# ✅ Good - focused test
def test_detection_threshold_filtering(mock_config):
    """Test that detections below threshold are filtered."""
    detector = Detector(threshold=-40.0)
    result = detector.process(audio_level=-45.0)
    assert result is None  # Below threshold

# ❌ Bad - testing multiple things
def test_detector(mock_config):
    """Test detector."""  # Vague
    detector = Detector(threshold=-40.0)
    assert detector.process(-45.0) is None
    assert detector.process(-35.0) is not None
    assert detector.get_stats() == {...}  # Too much in one test
```

### 2. Use Descriptive Test Names

```python
# ✅ Good
def test_mqtt_reconnects_after_connection_lost():
    ...

def test_audio_clip_saved_with_correct_format():
    ...

# ❌ Bad
def test_mqtt():
    ...

def test_audio():
    ...
```

### 3. Test Error Paths

```python
def test_handles_missing_audio_file_gracefully(mock_config, tmp_path):
    """Test that missing file raises appropriate error."""
    nonexistent = tmp_path / "missing.flac"
    
    with pytest.raises(FileNotFoundError):
        load_audio(nonexistent)
```

### 4. Use Parametrize for Multiple Cases

```python
@pytest.mark.parametrize("input_level,expected", [
    (-50.0, False),  # Below threshold
    (-40.0, True),   # At threshold
    (-30.0, True),   # Above threshold
])
def test_threshold_detection(input_level, expected, mock_config):
    """Test detection at various levels."""
    detector = Detector(threshold=-40.0)
    result = detector.detect(input_level)
    assert (result is not None) == expected
```

---

## Coverage Requirements

### Minimum Coverage: 70%

Run coverage locally before committing:

```bash
cd platform/orpheus-common  # or agents/*, services/*
make coverage
```

### Coverage Report

```bash
# Generate HTML coverage report
pytest --cov=orpheus_agent_audio_motion --cov-report=html
open htmlcov/index.html
```

### What Not to Worry About

Some code is OK to exclude from coverage:
- Type checking blocks (`if TYPE_CHECKING:`)
- Defensive assertions that should never execute
- Platform-specific code paths (if testing on one platform)
- `__repr__` and `__str__` methods (unless critical)

---

## Testing Anti-Patterns

### ❌ Don't Mock Everything

```python
# Bad - over-mocking makes tests meaningless
def test_process_audio():
    mock_audio = MagicMock()
    mock_detector = MagicMock()
    mock_detector.detect.return_value = True
    result = mock_detector.detect(mock_audio)
    assert result  # This test proves nothing!
```

### ❌ Don't Test Implementation Details

```python
# Bad - testing internal implementation
def test_detector_uses_list_internally():
    detector = Detector()
    assert isinstance(detector._internal_buffer, list)  # Fragile!

# Good - testing behavior
def test_detector_buffers_audio_samples():
    detector = Detector(buffer_size=10)
    detector.add_samples([1, 2, 3])
    assert len(detector.get_buffered_samples()) == 3
```

### ❌ Don't Write Flaky Tests

```python
# Bad - depends on timing
def test_async_operation():
    result = None
    async_function(lambda x: result = x)
    time.sleep(0.1)  # Race condition!
    assert result is not None

# Good - use proper async testing
@pytest.mark.asyncio
async def test_async_operation():
    result = await async_function()
    assert result is not None
```

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

See [`platform/orpheus-common/README.md`](../platform/orpheus-common/README.md) for details.

### Testing Dashboard

Dashboard tests should:
- Use FastAPI TestClient for API endpoints
- Mock MQTT subscriptions
- Test WebSocket message handling
- Validate API response schemas

See [`docs/copilot-workspace-instructions/dashboard.instructions.md`](../docs/copilot-workspace-instructions/dashboard.instructions.md) for patterns.

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
- [ ] Coverage is ≥70% (`make coverage`)
- [ ] No test warnings or deprecation messages
- [ ] Tests are focused and descriptive
- [ ] Error paths are tested
- [ ] External dependencies are mocked

---

## References

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio Documentation](https://pytest-asyncio.readthedocs.io/)
- [unittest.mock Documentation](https://docs.python.org/3/library/unittest.mock.html)
- [`CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md) - Core development guidelines
- [`docs/copilot-workspace-instructions/tests.instructions.md`](../docs/copilot-workspace-instructions/tests.instructions.md) - Quick reference patterns
