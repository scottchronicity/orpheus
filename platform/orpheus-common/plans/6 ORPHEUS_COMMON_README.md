# orpheus-common

**Shared platform library for the Orpheus cross-species communication system**

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
pip install -e ../../platform/orpheus-common
```

### Production (Future)
```bash
pip install orpheus-common
```

## Package Structure

```
src/
├── examples/
│   └── usage_example.py
└── orpheus_common/
  ├── config.py           # YAML configuration with env var overrides
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
  │   └── management.py  # Cleanup, retention policies
  │
  ├── detection/         # Detection data models (placeholder)
  │   ├── models.py      # Pydantic models for detection events
  │   └── database.py    # SQLite DetectionDB wrapper
  │
  └── utils/             # Shared utilities
    └── time.py        # Timestamp utilities
```

## Quick Start

### Configuration Management
```python
from orpheus_common.config import Config

# Load YAML config with environment variable overrides
config = Config.load("cameras.yaml")

# Access configuration
camera_user = config.get("camera.user", default="admin")

# Environment variable override
# ORPHEUS_CAMERA_USER=myuser overrides cameras.user in YAML
```

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

Orpheus uses YAML for configuration with environment variable overrides.

**Configuration Search Path:**
1. `/etc/orpheus/<service>/config.yaml` (production)
2. `./config/config.yaml` (development)
3. Environment variables: `ORPHEUS_<SECTION>_<KEY>`

**Example: `config/cameras.yaml`**
```yaml
cameras:
  north:
    ip: "192.168.1.100"
    user: "admin"
    enabled: true
  south:
    ip: "192.168.1.101"
    user: "admin"
    enabled: true
```

**Override with environment variables:**
```bash
export ORPHEUS_CAMERAS_NORTH_USER=myuser
```

## Development

### Install Dependencies
```bash
pip install -e ".[dev]"
```

### Run Tests
```bash
pytest tests/ -v
```

### Format Code
```bash
ruff format src/
ruff check --fix src/
```

### Type Checking
```bash
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

## Migration from Dashboard

The dashboard service (`services/orpheus-dashboard/`) contains battle-tested code that has been migrated to `orpheus-common`:

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

- **0.1.0** (2025-11-25) - Initial release with core infrastructure
  - Configuration management (YAML + env vars)
  - MQTT client wrapper
  - Hardware abstractions (cameras)
  - System health monitoring
  - Storage utilities
