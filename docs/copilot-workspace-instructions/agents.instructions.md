---
applyTo: "agents/**"
---

# Agent Development Instructions

**See [`CODING_AGENT_CONTEXT.md`](../../CODING_AGENT_CONTEXT.md) for core guidelines.** This file contains agent-specific implementation details.

**See [`docs/AGENTS.md`](../AGENTS.md) for agent architecture and design patterns.**

---

## Agent Structure Template

Every agent must follow this structure:
```
orpheus-agent-{name}/
├── src/orpheus_agent_{name}/
│   ├── __init__.py
│   ├── config.py          # Agent-specific dataclasses
│   ├── main.py            # Entry point with MQTT lifecycle
│   └── {domain}_*.py      # Processing logic
├── tests/
│   ├── conftest.py        # Pytest fixtures
│   └── test_*.py          # Minimum 70% coverage
├── systemd/
│   ├── install-service.sh
│   └── orpheus-agent-{name}.service
├── Makefile               # Standard targets (see below)
├── requirements.txt       # Include -e ../../platform/orpheus-common
├── pyproject.toml
└── README.md
```

## Required Makefile Targets

```makefile
make install          # Create venv, install deps including orpheus-common
make test             # Run pytest
make coverage         # pytest --cov with report
make lint             # ruff check
make format           # ruff format
make install-service  # Deploy systemd unit (requires sudo)
make update           # Reinstall + restart service
make service-logs     # journalctl -f
```

## Main Entry Point Pattern

```python
from orpheus_common.logging import setup_logging, get_logger
from orpheus_common.mqtt import MQTTClient
from orpheus_common import OrpheusConfig

def main():
    setup_logging("orpheus-agent-{name}", level="INFO")
    logger = get_logger(__name__)
    config = OrpheusConfig.get_instance()
    
    mqtt_client = MQTTClient(
        broker_host=config.mqtt.broker_host,
        broker_port=config.mqtt.broker_port,
        client_id="orpheus-agent-{name}",
        will_topic="orpheus/system/{name}/health",
        will_payload={"status": "offline"}
    )
    
    @mqtt_client.on_message("orpheus/input/topic/#")
    def handle_input(topic: str, payload: dict):
        # Process and publish results
        pass
    
    mqtt_client.connect()
    # Main loop...
```

## Service Registration

After creating a new agent, register it in the root Makefile to enable orchestration targets:

1. Add the agent to `PYTHON_PROJECTS` variable in `/Makefile`
2. Add install/test/lint/format/clean targets following the existing pattern
3. Add the service to orchestration targets: `services-install`, `services-start`, `services-stop`, `status-all`, `update-all`

This ensures the new agent is included in `make status-all`, `make update-all`, and other root-level commands.

## Anti-Patterns

- DO NOT create new config files - use OrpheusConfig
- DO NOT copy MQTT handling code - use MQTTClient
- DO NOT hardcode paths - use storage helpers
- DO NOT use print() - use the logging system
- DO NOT skip type hints
