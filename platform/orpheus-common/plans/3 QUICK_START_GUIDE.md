# Orpheus Platform Common Library - Quick Start Guide

**Location:** `platform/orpheus-common/`  
**Package Name:** `orpheus-common`  
**Status:** ✅ Ready for validation and dashboard migration

---

## What Was Built

A complete, production-ready shared library that consolidates:

- ✅ **Configuration Management** - YAML + environment variables
- ✅ **MQTT Communication** - Auto-reconnect, JSON serialization
- ✅ **Hardware Abstractions** - Camera classes from dashboard (battle-tested)
- ✅ **System Health** - CPU, memory, disk, service monitoring
- ✅ **Storage Utilities** - T7 path management
- ✅ **Logging** - Systemd journal integration
- ✅ **Time Utilities** - ISO 8601 timestamps

---

## Installation

### Step 1: Extract the Archive

```bash
cd ~/orpheus  # Your monorepo root
tar -xzf orpheus-platform-common.tar.gz
```

This creates: `platform/orpheus-common/` directory with the complete library.

### Step 2: Install in Development Mode

```bash
cd platform/orpheus-common
pip install -e .
```

This makes `orpheus_common` importable from anywhere in your environment.

---

## Quick Validation

### Test 1: Import the Library

```bash
python3 -c "from orpheus_common import Config; print('✓ Import successful')"
```

### Test 2: Run Usage Examples

```bash
cd platform/orpheus-common
python3 examples/usage_example.py
```

You should see output demonstrating all major features.

### Test 3: Check System Health

```python
from orpheus_common.system.health import SystemHealth

health = SystemHealth()
metrics = health.get_metrics()
print(f"CPU: {metrics.cpu_percent}%")
print(f"Memory: {metrics.memory_percent}%")
```

---

## Next Steps

### Priority 1: Migrate Dashboard

The dashboard service currently has duplicate code. Let's migrate it to use `orpheus-common`.

**Dashboard Location:** `services/orpheus-dashboard/`

#### Step 1: Update Dashboard Requirements

Edit `services/orpheus-dashboard/requirements.txt`:

```txt
# Add this line:
-e ../../platform/orpheus-common

# Keep existing requirements:
fastapi==0.104.1
uvicorn[standard]==0.24.0
# ... etc
```

#### Step 2: Update Dashboard Imports

Edit `services/orpheus-dashboard/src/orpheus_dashboard/main.py`:

```python
# OLD imports (delete these):
# from .hardware.registry import CameraRegistry
# from .hardware.storage import get_storage_hardware_info
# from .system.health import get_data_storage_usage

# NEW imports (add these):
from orpheus_common.hardware import CameraRegistry, get_storage_hardware_info
from orpheus_common.system.health import get_data_storage_usage
```

#### Step 3: Test Dashboard

```bash
cd services/orpheus-dashboard
make install  # Reinstall with new dependency
make run      # Start dashboard
```

**Verify:**
- Navigate to http://localhost:8080
- Check that cameras appear
- Check that system health shows
- Check that storage appears

#### Step 4: Remove Duplicate Code

Once dashboard is working with `orpheus-common`:

```bash
cd services/orpheus-dashboard
rm -rf src/hardware/
rm src/system/health.py
```

### Priority 2: Update or Archive Example Agents

The old `agents/common/` directory has placeholder code. Decide whether to:

**Option A:** Archive it
```bash
cd agents
mv common common-old-reference
```

**Option B:** Update it to use platform/orpheus-common
```bash
cd agents/common
# Update requirements.txt to point to platform/orpheus-common
# Update imports
```

### Priority 3: Create New Detection Agents

Now that shared infrastructure exists, create real agents:

**Audio Detection Agent:**
```bash
mkdir -p agents/audio-detection
cd agents/audio-detection

# Create requirements.txt with:
-e ../../platform/orpheus-common
# ... other dependencies
```

**In your agent code:**
```python
from orpheus_common.config import Config
from orpheus_common.logging import setup_logging
from orpheus_common.mqtt import MQTTClient
from orpheus_common.storage import get_audio_path

logger = setup_logging("audio-detection", level="INFO")
config = Config.load("config.yaml")
mqtt = MQTTClient(broker_host="localhost", client_id="audio-detection")

# Your agent logic here...
```

---

## Configuration Files

### Example: Camera Configuration

Create `config/cameras.yaml`:

```yaml
cameras:
  auth:
    username: admin
    password: yourpassword
  
  north:
    type: amcrest
    host: 192.168.1.100
    model: IP5M-B1186EW-AI-V3
    enabled: true
  
  south:
    type: amcrest
    host: 192.168.1.101
    model: IP5M-B1186EW-AI-V3
    enabled: true
```

### Example: Agent Configuration

Create `config/audio-detection.yaml`:

```yaml
mqtt:
  host: localhost
  port: 1883

audio:
  channels: [1, 2, 3, 4]
  sample_rate: 48000
  chunk_duration: 60

detection:
  min_confidence: 0.8
  species_of_interest:
    - amecro  # American Crow
    - rebwoo  # Red-bellied Woodpecker
```

### Environment Variable Overrides

```bash
# Override YAML values:
export ORPHEUS_MQTT_HOST=mqtt.example.com
export ORPHEUS_AUDIO_CHANNELS="[1,2]"
export ORPHEUS_DETECTION_MIN_CONFIDENCE=0.9
```

---

## Common Tasks

### Check Storage Health

```python
from orpheus_common.hardware.storage import get_storage_hardware_info

info = get_storage_hardware_info()
print(f"Status: {info['status']}")
if info['status'] != 'healthy':
    print(f"Issue: {info.get('message', 'Unknown')}")
```

### Work with Cameras

```python
from orpheus_common.hardware import CameraRegistry

registry = CameraRegistry.from_config("cameras.yaml")
camera = registry.get("north")

# Check health
health = camera.get_health_status()
print(f"Camera status: {health['status']}")

# Get snapshot
snapshot = camera.capture_snapshot()
if snapshot['ok']:
    with open('snapshot.jpg', 'wb') as f:
        f.write(snapshot['image_data'])
```

### Publish MQTT Messages

```python
from orpheus_common.mqtt import MQTTClient
from orpheus_common.utils.time import utc_now_iso

client = MQTTClient(broker_host="localhost", client_id="my-agent")
client.connect()

client.publish("orpheus/detection/audio", {
    "type": "detection",
    "species": "amecro",
    "confidence": 0.95,
    "timestamp": utc_now_iso(),
    "channel": 1
})
```

### Manage Storage Paths

```python
from orpheus_common.storage import get_audio_path, ensure_directory
from datetime import date

# Get standardized path
audio_dir = get_audio_path("raw", date.today(), channel=1)
# Returns: /data/orpheus/audio/raw/2025-11-25/channel_1/

# Ensure it exists
ensure_directory(audio_dir)

# Save file
audio_file = audio_dir / "recording_001.wav"
# ... write audio data ...
```

---

## Troubleshooting

### Import Error: "No module named 'orpheus_common'"

**Solution:**
```bash
cd platform/orpheus-common
pip install -e .
```

### Config File Not Found

The library searches:
1. `/etc/orpheus/<service>/config.yaml` (production)
2. `./config/config.yaml` (development)

**Solution:** Create `config/` directory in your service:
```bash
mkdir -p config
cp config.yaml.example config/config.yaml
```

### Camera Connection Issues

**Check network:**
```bash
ping 192.168.1.100  # Your camera IP
```

**Verify credentials:**
Check `CAMERA_USER` and `CAMERA_PASS` environment variables or YAML config.

**Test from dashboard:**
The dashboard health checks will show detailed error messages.

---

## Documentation

- **Complete README:** `ORPHEUS_COMMON_README.md`
- **Implementation Details:** `IMPLEMENTATION_SUMMARY.md`
- **Usage Examples:** `platform/orpheus-common/examples/usage_example.py`
- **API Documentation:** See docstrings in each module

---

## Get Help

If you run into issues:

1. **Check logs:** The logging module integrates with systemd journal
2. **Enable debug mode:** `setup_logging("service", level="DEBUG")`
3. **Review examples:** `platform/orpheus-common/examples/usage_example.py`
4. **Read module docstrings:** All functions have comprehensive documentation

---

## Success Criteria

✅ **Package installs cleanly:** `pip install -e platform/orpheus-common`  
✅ **Examples run:** `python3 examples/usage_example.py`  
✅ **Dashboard migrates:** Imports work, all endpoints functional  
✅ **New agents use it:** Rapid development with shared infrastructure

---

**You're ready to go! Start with the dashboard migration, then build out detection agents using this solid foundation.** 🚀
