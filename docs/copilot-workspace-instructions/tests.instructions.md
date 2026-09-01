---
applyTo: "**/tests/**"
---

# Test Development Instructions

**See [`/CODING_AGENT_CONTEXT.md`](https://github.com/scottchronicity/orpheus/blob/main/CODING_AGENT_CONTEXT.md) for core guidelines.** This file contains test-specific quick reference patterns.

**See [`/docs/TESTING.md`](https://github.com/scottchronicity/orpheus/blob/main/TESTING.md) for comprehensive testing strategy and patterns.**

---

## Framework

- Use `pytest` with fixtures
- Use `pytest-cov` for coverage (minimum 70%)
- Use `unittest.mock` for mocking

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

## Fixture Patterns

```python
# conftest.py
import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_mqtt_client():
    with patch("orpheus_common.mqtt.MQTTClient") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client

@pytest.fixture
def mock_config():
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

## Test Patterns

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

## What to Test

- All public functions and methods
- Error handling paths
- Edge cases (empty input, None values, boundaries)
- MQTT message handling with various payloads
- Configuration loading with missing/invalid values

## What to Mock

- MQTT connections and publishing
- File system operations (use tmp_path fixture)
- External services and hardware
- OrpheusConfig (unless testing config itself)
- Time-dependent operations
