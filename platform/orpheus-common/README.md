# orpheus-common

## Shared platform library for the Orpheus cross-species communication system

This package provides common infrastructure used across all Orpheus services and agents. It prevents code duplication, ensures consistency, and provides battle-tested patterns for hardware abstraction, configuration management, storage utilities, and inter-service communication.

## Philosophy

**If functionality is needed by multiple services or agents, it belongs in `orpheus-common`.**

This library is designed to be:

- **Minimal**: Only essential shared functionality
- **Reliable**: Battle-tested code from production services
- **Well-documented**: Comprehensive API docs and examples
- **Type-safe**: Full type hints throughout
- **Testable**: Hardware mocking for unit tests

## Installation

### Development (Editable Install)

```bash
# From any service or agent directory
pip install -r requirements.txt
pip install -e ../../platform/orpheus-common
```

Or using the Makefile:

```bash
cd platform/orpheus-common
make install
```

### Production (Future)

```bash
pip install orpheus-common
```

## Package Structure

```bash
src/
├── examples/
│   └── usage_example.py
└── orpheus_common/
  ├── config.py           # Unified orpheus.yaml loader (dataclasses + env overrides)
  ├── mqtt.py             # MQTT client wrapper with auto-reconnect
  ├── logging.py          # Systemd journal logging setup
  │
  ├── hardware/           # Hardware abstractions
  │   ├── base.py        # Abstract Camera class
  │   ├── registry.py    # Hardware discovery and management
  │   ├── storage.py     # Storage device health monitoring
  │   └── cameras/       # Camera implementations
  │       └── amcrest.py # Amcrest IP camera
  │
  ├── system/            # System utilities
  │   └── health.py      # CPU, memory, disk, uptime metrics
  │
  ├── storage/           # T7 storage utilities
  │   ├── paths.py       # Path construction for /data/orpheus
  │   ├── usage.py       # How big each recording category is
  │   ├── sweep.py       # orpheus-storage-sweep: the ONE component that deletes
  │   ├── cleanup.py     # Per-directory helper; nothing runs it on a timer
  │   └── management.py  # Small standalone age/disk helpers
  │
  ├── detection/         # Detection data models (placeholder)
  │   ├── models.py      # Pydantic models for detection events
  │   └── database.py    # SQLite DetectionDB wrapper
  │
  └── utils/             # Shared utilities
    └── time.py        # Timestamp utilities
```

## Quick Start

### Unified Configuration (Recommended)

```python
from orpheus_common import OrpheusConfig

# Load unified orpheus.yaml (searches /etc/orpheus/ then config/)
config = OrpheusConfig.load()

# Typed access to sections
print(config.mqtt.broker_host)

# Iterate audio channels
for channel in config.audio.channels:
  if channel.enabled:
    print(f"Channel {channel.id}: {channel.name}")

# Camera helpers
username, password = config.camera_credentials()
for camera in config.get_enabled_cameras():
  print(f"Camera {camera.name} @ {camera.host}")

# Storage + detection settings
print(config.storage.base_path)
print(config.detection.min_confidence)
```

### Legacy Config Loader (Deprecated)

`orpheus_common.config.Config` is still available for YAML fragments such as
`cameras.yaml`, but all new code should migrate to `OrpheusConfig` and the
single `orpheus.yaml` source of truth.

### MQTT Communication

```python
from orpheus_common.mqtt import MQTTClient

# Create client with auto-reconnect
client = MQTTClient(
    broker_host="localhost",
    client_id="my-agent",
    topics=["orpheus/sensors/#"]
)

# Publish with automatic JSON serialization
client.publish("orpheus/detection/audio", {
    "type": "detection",
    "species": "amecro",
    "confidence": 0.95
})

# Subscribe with callback
@client.on_message("orpheus/detection/#")
def handle_detection(topic, payload):
    print(f"Detection: {payload['species']}")

client.connect()
```

### Hardware Abstraction

```python
from orpheus_common.hardware.cameras import AmcrestCamera
from orpheus_common.hardware.registry import CameraRegistry

# Access cameras through registry
registry = CameraRegistry.from_config("cameras.yaml")
camera = registry.get_camera("north_cam")

# Get snapshot
image = camera.get_snapshot()

# Check health
health = camera.check_health()
print(f"Status: {health.status}")
```

### Storage Utilities

```python
from orpheus_common.storage import get_audio_path, ensure_directory
from datetime import date

# Construct standardized paths
audio_dir = get_audio_path("raw", date.today(), channel=1)
# Returns: /data/orpheus/audio/raw/2025-11-25/channel_1/

# Ensure directory exists with proper permissions
ensure_directory(audio_dir)
```

### System Health

```python
from orpheus_common.system.health import SystemHealth

health = SystemHealth()
metrics = health.get_metrics()

print(f"CPU: {metrics.cpu_percent}%")
print(f"Memory: {metrics.memory_percent}%")
print(f"Disk: {metrics.disk_usage}")
```

## Configuration Files

All services now share a single `orpheus.yaml` file that lives either in
`/etc/orpheus/` (production) or the repository `config/` directory (development).
An example lives at `config/orpheus.example.yaml`.

**Search order:**

1. `/etc/orpheus/orpheus.yaml`
2. `config/orpheus.yaml`
3. `orpheus.yaml` in the current working directory
4. `../../config/orpheus.yaml` (repo root, relative to component)

**Environment substitution:** values may embed `${VAR}` (required) or
`${VAR:-default}`. Missing required variables raise `ConfigError`.

**Environment overrides:** any variable that starts with `ORPHEUS_` can override
config values. Use double underscores to separate nesting:

```bash
export ORPHEUS_MQTT__BROKER_HOST=mqtt.local
export ORPHEUS_STORAGE__BASE_PATH=/mnt/data
export ORPHEUS_CAMERAS__NORTH__HOST=192.168.1.50
```

The YAML schema covers `mqtt`, `audio`, `cameras`, `storage`, `detection`,
`dashboard`, `logging`, and `hardware` sections. See the example file for the
full structure.

### Audio + Camera Streams

For Amcrest cameras the `audio.channels[].device` entries can point directly to
each camera's RTSP feed (including credentials). The default
`config/orpheus.yaml` maps four "Eye" cameras to matching audio channels, so all
agents—audio motion detection, storage, etc.—share one source of truth.

### Development Overrides

Use the slim `config/orpheus.test.yaml` for laptops/CI by pointing
`ORPHEUS_CONFIG_PATH` at it. It trims the system down to one simulated camera,
a single audio loopback channel, and local storage (`/path/to/data/orpheus`).

### .env Support

`OrpheusConfig` automatically loads `config/.env.orpheus` if it exists.
Set `ORPHEUS_DOTENV_PATH` to point to a different file.

Copy the example and adjust `ORPHEUS_*` overrides (e.g., audio channels or storage path):

## Development

### Install Dependencies

```bash
# Install package in editable mode
pip install -r requirements.txt
pip install -e .

# Or install with development dependencies
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .

# Or use the Makefile
make install      # Just the package
make install-dev  # With dev dependencies
```

### Run Tests

```bash
pytest tests/ -v
# Or use Makefile
make test
```

### Format Code

```bash
ruff format src/
ruff check --fix src/
# Or use Makefile
make format
```

### Type Checking

```bash
# mypy not included by default - install separately if needed
pip install mypy
mypy src/orpheus_common/
```

## Design Principles

### 1. Configuration Over Code

Use YAML files for configuration, not hardcoded values. Environment variables override YAML for deployment flexibility.

### 2. Hardware Abstraction

All hardware access goes through abstract base classes. This enables:

- Mocking for tests
- Hot-swapping implementations
- Consistent error handling

### 3. Path Standardization

All file operations use `orpheus_common.storage` utilities to ensure:

- Consistent directory structure
- Proper /data/orpheus usage
- Automatic directory creation

### 4. Systemd Integration

Services use systemd for lifecycle management. The library provides:

- Journal logging
- Service health checks
- Graceful shutdown handling

### 5. Type Safety

Full type hints throughout. Use mypy for static type checking.

## Migration history (orpheus-dashboard → orpheus-common)

The legacy `orpheus-dashboard` service (removed in favour of
`orpheus_ui`) contributed battle-tested code that was migrated into
`orpheus-common`:

- ✅ `hardware/` - Camera abstractions and registry
- ✅ `system/health.py` - System metrics
- 🔄 Configuration management (enhanced with YAML)
- 🔄 Storage utilities (new T7 patterns)

New agents can now import this proven infrastructure instead of copying code.

## Related Documentation

- `T7_Storage_Architecture_Nov_2025.md` - Storage paths and patterns
- `Orpheus_Distributed_Agent_Architecture_v2_Nov_2025.md` - How agents communicate
- `Detection_Data_Schema_and_Storage_Nov_2025.md` - Detection database schema
- `Orpheus_Common_Library_Specification_Nov_2025.md` - Complete API specification

## Contributing

This is an internal package for the Orpheus monorepo. When adding functionality:

1. **Is it shared?** Only add code needed by multiple services/agents
2. **Is it tested?** All modules must have comprehensive tests
3. **Is it documented?** Add docstrings and update README
4. **Is it typed?** Full type hints required

## License

MIT License - See LICENSE file in repository root

## Version History

- **0.2.0** (2025-11-29) - Unified configuration system
  - Single `orpheus.yaml` for every service/agent
  - Dataclass-backed access with validation and env substitution
  - Example configs in `config/orpheus.example.yaml` with macOS overrides via `config/.env.orpheus.example`
- **0.1.0** (2025-11-25) - Initial release with core infrastructure
  - Configuration management (YAML + env vars)
  - MQTT client wrapper
  - Hardware abstractions (cameras)
  - System health monitoring
  - Storage utilities
