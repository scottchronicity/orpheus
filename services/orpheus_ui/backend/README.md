# Orpheus UI Backend

FastAPI backend for the Orpheus UI wildlife monitoring interface, providing REST APIs, JWT authentication, and MQTT integration.

## Quick Start

```bash
# Install dependencies
make install

# Run backend (port 8082)
make run

# Run tests
make test

# Run with coverage
make coverage
```

## Architecture

- **Framework**: FastAPI with Uvicorn
- **Auth**: FastAPI-Users with JWT tokens and SQLite user database
- **Roles**: Admin, Viewer, Public
- **MQTT**: Real-time system status via `orpheus-common` MQTTClient
- **Logging**: structlog JSON via `orpheus-common`

## API Modules

| Module | Endpoints |
| ----------- | ----------- |
| `cameras` | Camera feeds and snapshots |
| `diagnostics` | System health monitoring |
| `entities` | Detection entity management |
| `media` | Audio/video media access |
| `system` | Service status and system info |

## Configuration

Uses `OrpheusConfig` from `orpheus-common`. Set `ORPHEUS_CONFIG_PATH` or place config at `/opt/orpheus/config/orpheus.yaml`.

## User Database

- **Development**: `./users.db`
- **Production**: `/data/orpheus/users.db`

Default users are seeded on first startup (see [ORPHEUS_UI.md](../../../docs/ORPHEUS_UI.md)).

## Development

```bash
make install    # Set up venv and install dependencies
make run        # Run with auto-reload on port 8082
make test       # Run pytest tests
make coverage   # Run tests with coverage
make lint       # Run ruff linting
make format     # Format code with ruff
make clean      # Remove venv and caches
```

## Related Documentation

- [Orpheus UI Overview](../../../docs/ORPHEUS_UI.md) — full UI documentation
- [Parent README](../README.md) — combined backend/frontend setup
- [UI Instructions](../../../docs/copilot-workspace-instructions/orpheus-ui.instructions.md) — development patterns
