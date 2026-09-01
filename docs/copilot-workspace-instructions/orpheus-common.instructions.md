---
applyTo: "platform/orpheus-common/**"
---

# orpheus-common Library Instructions

**See [`/CODING_AGENT_CONTEXT.md`](https://github.com/scottchronicity/orpheus/blob/main/CODING_AGENT_CONTEXT.md) for core guidelines.** This file contains orpheus-common specific implementation details.

**See [`/platform/orpheus-common/README.md`](https://github.com/scottchronicity/orpheus/blob/main/platform/orpheus-common/README.md) for library overview and usage.**

---

## Purpose

This is the shared library imported by ALL agents and services. Changes here affect the entire system.

---

## Module Responsibilities

- `config.py` - OrpheusConfig singleton, YAML loading, dataclasses
- `mqtt.py` - MQTTClient wrapper with auto-reconnect, JSON serialization
- `logging.py` - Centralized logging setup with consistent format
- `storage/` - Path management for /data/orpheus, usage survey, and `sweep.py` —
  the one component that deletes recordings (no agent does)
- `detection/` - Detection models and SQLite database (DetectionDB)
- `hardware/` - Camera and audio abstractions
- `diagnostics/` - Health monitoring for audio/video subsystems

## Adding New Functionality

1. Ask: "Will multiple agents need this?" - If yes, put it here
2. Add type hints and docstrings
3. Add unit tests (tests/ directory)
4. Export from `__init__.py` if it's a public API
5. Bump the version with `scripts/bump-version.sh platform/orpheus-common <major|minor|patch>` — the `VERSION` file is the source of truth and `pyproject.toml` reads it dynamically (ADR 0014)

## Key Classes

```python
# Singleton config - ALWAYS use get_instance()
config = OrpheusConfig.get_instance()

# MQTT client - handles reconnect and JSON automatically
client = MQTTClient(broker_host="...", client_id="...")

# Storage helpers - respect ORPHEUS_DATA_ROOT
path = get_audio_path(category="audio_motion", channel_id="1")
```

## Testing Requirements

- Mock file system operations
- Mock MQTT connections
- Test configuration loading with various YAML inputs
- Test error handling paths

## Backward Compatibility

Changes to public APIs must not break existing agents. If breaking changes are needed, deprecate first.
