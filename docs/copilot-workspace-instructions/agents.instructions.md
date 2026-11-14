---
applyTo: "agents/**"
---

# Agent Development Instructions

Read [AGENTS.md](https://github.com/scottchronicity/orpheus/blob/main/AGENTS.md), then the
[architecture contract](../ARCHITECTURE.md#architecture-contract) and affected
component docs before changing architecture, configuration, runtime or deployment.
Use the [shared branch/review workflow](../agent-instructions/12-git-and-lfs.md#shared-development-and-independent-review).
Python compatibility is per component; preserve detection semantics across
backends, and keep model/runtime dependencies separate from reusable IPC.

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

Use the existing `Actor` hooks for new domain agents: `on_setup`,
`subscriptions`, `on_started`, `health_payload`, `on_stopping` and `on_shutdown`.
The base owns bus lifecycle and supervision hooks; create the EventBus through
`create_event_bus`, never directly instantiate a broker client. See audio-events
for the shared in-process/subprocess detection emission path, and
[event bus invariants](../agent-instructions/21-event-bus-and-data-flow.md) for
lineage, error accounting and persistence.

## Service Registration

After creating a new agent, register it in the root Makefile to enable orchestration targets:

1. Add the agent to `PYTHON_PROJECTS` variable in `/Makefile`
2. Add install/test/lint/format/clean targets following the existing pattern
3. Add the service to orchestration targets: `services-install`, `services-start`, `services-stop`, `status-all`, `update-all`

This ensures the new agent is included in `make status-all`, `make update-all`, and other root-level commands.

## Anti-Patterns

- DO NOT create new config files - use OrpheusConfig
- DO NOT copy broker handling code - use Actor/EventBus
- DO NOT hardcode paths - use storage helpers
- DO NOT use print() - use the logging system
- DO NOT skip type hints
