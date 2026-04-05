# AI Agent Context - Orpheus

This file provides context for AI coding assistants (Claude, Copilot, Gemini, Cursor, etc.) working on the Orpheus codebase.

## Project Overview

Orpheus is a Python monorepo for wildlife monitoring and cross-species communication research, designed for NVIDIA Jetson Orin NX edge deployment. The system uses distributed agents communicating via MQTT.

## Critical Constraints

| Constraint | Value | Reason |
| ------------ | ------- | -------- |
| **Python Version** | 3.9.5 | Jetson Orin NX system Python |
| **Architecture** | ARM64 + x86_64 | Edge (Jetson) + Dev (Mac) |
| **Type Syntax** | `Optional[X]` | No `X \| None` - Python 3.9 compat |
| **Coverage** | 70% minimum | CI enforcement |

## Repository Structure

```bash
orpheus/
├── platform/orpheus-common/     # Shared library (config, mqtt, storage, logging)
├── services/
│   ├── orpheus-dashboard/       # FastAPI web UI (legacy)
│   ├── orpheus_ui/              # React/FastAPI web UI (new)
│   ├── orpheus-mqtt/            # Mosquitto broker wrapper
│   └── orpheus-bluetooth/       # Bluetooth speaker autoconnect
├── agents/
│   ├── orpheus-agent-audio-motion/      # Layer 1: Audio motion detection
│   ├── orpheus-agent-video-motion/      # Layer 1: Video motion detection
│   ├── orpheus-agent-video-snapshotter/ # Video: Periodic camera snapshots
│   ├── orpheus-agent-video-timelapser/  # Video: Timelapse generation
│   ├── orpheus-agent-bird-detection/    # Layer 2: BirdNET species identification
│   ├── orpheus-agent-crow-detection/    # Layer 2: Crow vocalization analysis
│   └── orpheus-agent-audio-playback/    # Audio output agent
└── Makefile                     # Root orchestration
```

## Development Workflow

```bash
# Install all components
make install

# Run all tests
make test

# Run tests with coverage
make coverage-all

# Format all code with ruff
make format

# Lint all code
make lint
```

## Per-Component Commands

Each component follows the same pattern:

```bash
cd platform/orpheus-common  # or services/orpheus-dashboard, agents/*, etc.
make install          # Create venv, install deps
make test             # Run pytest
make coverage         # Run with coverage
make lint             # Check code with ruff
make format           # Format with ruff
make clean            # Remove venv and caches
make dry-run          # Validate Python 3.9.5 compatibility
make install-service  # Deploy systemd unit (requires sudo)
make update           # Reinstall + restart service
make service-logs     # Tail journalctl
```

## Code Style

- **Formatter/Linter**: Ruff only (no Black)
- **Line length**: 100 characters
- **Docstrings**: Google style
- **Type hints**: Required for all public APIs

```python
# ✅ Correct (Python 3.9 compatible)
from typing import Optional, List, Dict

def process(items: List[str]) -> Optional[str]:
    """Process items and return result.
    
    Args:
        items: List of items to process.
    
    Returns:
        Processed result or None if empty.
    """
    ...

# ❌ Wrong (Python 3.10+ syntax)
def process(items: list[str]) -> str | None:  # NO!
    ...
```

## Common Patterns

### Configuration Access

```python
from orpheus_common import OrpheusConfig
config = OrpheusConfig.get_instance()
```

### Logging

```python
from orpheus_common.logging import get_logger, setup_logging
setup_logging("my-agent", level="INFO")
logger = get_logger(__name__)
```

### MQTT Publishing

```python
from orpheus_common.mqtt import MQTTClient
client = MQTTClient(
    broker_host=config.mqtt.broker_host,
    broker_port=config.mqtt.broker_port,
    client_id="my-agent"
)
client.publish("orpheus/events", {"type": "detection"})
```

### Storage Paths

```python
from orpheus_common.storage import get_audio_path, get_video_path
audio_path = get_audio_path(category="audio_motion", channel_id="1")
# Returns: Path("/data/orpheus/audio/audio_motion/1/")
```

## MQTT Topic Conventions

| Pattern | Purpose | Example |
| --------- | --------- | --------- |
| `orpheus/{domain}/{type}/events` | Event notifications | `orpheus/audio/motion/events` |
| `orpheus/{domain}/{type}/status` | Agent status | `orpheus/video/motion/status` |
| `orpheus/system/{agent}/health` | Health monitoring | `orpheus/system/dashboard/health` |

## Key Files

| File | Purpose |
| ------ | --------- |
| `platform/orpheus-common/src/orpheus_common/config.py` | Central configuration |
| `platform/orpheus-common/src/orpheus_common/mqtt.py` | MQTT client wrapper |
| `agents/orpheus-agent-audio-motion/src/orpheus_agent_audio_motion/main.py` | Reference agent implementation |
| `services/orpheus-dashboard/src/orpheus_dashboard/main.py` | Dashboard FastAPI app |

## Testing

- Framework: pytest with pytest-asyncio
- Coverage threshold: 70%
- Async mode: `asyncio_mode = "auto"`

```python
import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_config():
    with patch("orpheus_common.config.OrpheusConfig.get_instance") as mock:
        config = MagicMock()
        config.mqtt.broker_host = "localhost"
        mock.return_value = config
        yield config

def test_my_function(mock_config):
    result = my_function()
    assert result is not None
```

## Don't Do

- ❌ Use `X | None` type unions (Python 3.10+)
- ❌ Use `match` statements (Python 3.10+)
- ❌ Use `list[X]` or `dict[K, V]` without importing from typing
- ❌ Add Black as a dependency (use ruff only)
- ❌ Hardcode paths (use storage helpers)
- ❌ Duplicate MQTT/config code (use orpheus_common)
- ❌ Use print() for logging (use get_logger)
- ❌ Skip type hints on public functions

## Do

- ✅ Run `make test` before committing
- ✅ Use `Optional[X]`, `List[X]`, `Dict[K, V]` from typing
- ✅ Keep coverage above 70%
- ✅ Follow existing patterns in `orpheus-agent-audio-motion`
- ✅ Use ruff for all formatting/linting
- ✅ Import shared code from orpheus_common
- ✅ Add docstrings to public classes and functions
- ✅ Mock external dependencies in tests

## Reference Implementation

Use `agents/orpheus-agent-audio-motion/` as the template for new agents:

- Directory structure and file organization
- Makefile targets and patterns
- systemd service setup scripts
- Test organization with conftest.py
- MQTT lifecycle management in main.py
