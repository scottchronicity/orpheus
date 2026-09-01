# AI Agent Context - Orpheus

**The canonical entry point for AI coding agents is now [`/AGENTS.md`](https://github.com/scottchronicity/orpheus/blob/main/AGENTS.md)
at the repo root.** It provides a short list of non-negotiable rules
and a navigation map to themed deep-dive files in
[`docs/agent-instructions/`](../agent-instructions/).

This file is retained as a project reference and quick read for
maintainers. The deep-dive files supersede most of what's below for
agent-specific guidance.

---

This file provides high-level context for AI coding assistants (Claude, Copilot, Gemini, Cursor, etc.) working on the Orpheus codebase.

## Project Overview

Orpheus is a Python monorepo for wildlife monitoring and cross-species communication research, designed for NVIDIA Jetson Orin NX edge deployment. The system uses distributed agents communicating over an event bus — NATS with
JetStream by default, with MQTT as a fallback backend.

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
│   ├── orpheus_ui/              # React/FastAPI web UI
│   ├── orpheus-backplane/       # Messaging backplane (NATS default, mosquitto fallback)
│   └── orpheus-bluetooth-autoconnect/ # Bluetooth speaker autoconnect
├── agents/
│   ├── orpheus-agent-audio-motion/      # Layer 1: Audio motion detection
│   ├── orpheus-agent-video-motion/      # Layer 1: Video motion detection
│   ├── orpheus-agent-video-snapshotter/ # Video: Periodic camera snapshots
│   ├── orpheus-agent-video-timelapser/  # Video: Timelapse generation
│   ├── orpheus-agent-bird-detection/    # Layer 2: BirdNET species identification (IOC taxonomy)
│   ├── orpheus-agent-audio-events/      # Layer 2: PANNs SED on AudioSet ontology
│   ├── orpheus-agent-crow-detection/    # Layer 2: Crow vocalization analysis (call type / age)
│   ├── orpheus-agent-event-correlator/  # Layer 2/3: Event-based clustering + auto-discovery
│   └── orpheus-agent-audio-playback/    # Audio output agent
└── Makefile                     # Root orchestration
```

## Development Workflow

```bash
# Install all components
make install

# Run all tests (`make test` at the root aliases test-all; there is no
# root `make coverage`)
make test-all

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
cd platform/orpheus-common  # or services/orpheus_ui/backend, agents/*, etc.
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
| `orpheus/system/{agent}/health` | Health monitoring | `orpheus/system/bird-detection/health` |
| `orpheus/detection/{classifier}/events` | Classifier output | `orpheus/detection/bird/events`, `orpheus/detection/audio/events`, `orpheus/detection/crow/events` |
| `orpheus/entities/animal` | Correlated Entity events | (Layer 2 output from the event-correlator) |
| `orpheus/system/auto-discovery/health` | Auto-discovery scan summaries | (Layer 3 background worker pulse) |

## Cross-classifier identity

The `detectallanimals` branch introduced a 5-layer identity stack that
keeps each classifier autonomous (holonic) while combining their
outputs into one coherent picture per acoustic event. New code should
respect these invariants:

- Each classifier emits `taxonomy: TaxonomyRef` in a canonical
  namespace (`ioc`, `audioset`, `ebird`, `inaturalist`, `itis`).
- Each Detection carries `root_event_id` denormalising the audio.motion
  root; new agents should propagate it via
  `Detection.derive_root_event_id(parent)`.
- Multi-classifier evidence is preserved per-Entity — never collapse
  to a single "consensus" species.
- Cross-namespace identity goes through `equivalent_taxa()` — never
  hand-maintain alias maps.

See `docs/designs/cross-classifier-identity.md` for the full design.

## Key Files

| File | Purpose |
| ------ | --------- |
| `platform/orpheus-common/src/orpheus_common/config.py` | Central configuration |
| `platform/orpheus-common/src/orpheus_common/mqtt.py` | MQTT client wrapper |
| `platform/orpheus-common/src/orpheus_common/detection/models.py` | Detection / Entity / TaxonomyRef / EntityEvidence |
| `platform/orpheus-common/src/orpheus_common/detection/equivalence.py` | TaxonomyEquivalenceDB (Layer 3) |
| `platform/orpheus-common/src/orpheus_common/detection/equivalence_discovery.py` | Auto-discovery worker |
| `platform/orpheus-common/src/orpheus_common/detection/species.py` | Corvid genera + is_corvid helpers |
| `platform/orpheus-common/src/orpheus_common/detection/namespaces.py` | KNOWN_NAMESPACES registry |
| `agents/orpheus-agent-audio-motion/src/orpheus_agent_audio_motion/main.py` | Reference agent implementation |
| `agents/orpheus-agent-event-correlator/src/orpheus_agent_event_correlator/cluster_manager.py` | Layer 2 time-window clustering |
| `docs/designs/cross-classifier-identity.md` | Layered identity design |
| `services/orpheus_ui/backend/src/orpheus_ui/main.py` | UI backend FastAPI app |

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

- ❌ Use `X | None` where the expression is evaluated at runtime (`isinstance`, `cast`, `TypeAdapter`) — in annotations it is fine, because every module has `from __future__ import annotations`
- ❌ Use `match` statements (Python 3.10+)
- ❌ Use `list[X]` or `dict[K, V]` without importing from typing
- ❌ Add Black as a dependency (use ruff only)
- ❌ Hardcode paths (use storage helpers)
- ❌ Duplicate MQTT/config code (use orpheus_common)
- ❌ Use print() for logging (use get_logger)
- ❌ Skip type hints on public functions

## Do

- ✅ Run `make test-<component>` (and `make lint-<component>`) before committing
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
