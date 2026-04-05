# Orpheus Common Library - Installation Guide

**For Python 3.9.5 with old pip versions**

---

## Quick Install (3 Steps)

### Step 1: Navigate to Package
```bash
cd platform/orpheus-common
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

This installs:
- pydantic (data validation)
- pyyaml (configuration files)
- paho-mqtt (MQTT communication)
- requests (HTTP for cameras)
- psutil (system metrics)
- Pillow (image validation)

### Step 3: Install Package in Editable Mode
```bash
pip install -e .
```

The `-e` flag means "editable" - changes to the code take effect immediately without reinstalling.

---

## Verify Installation

```bash
# Test import
python -c "from orpheus_common import Config; print('✓ Works!')"

# Run examples
python examples/usage_example.py
```

---

## Using Makefile (Easier!)

If you prefer, use the Makefile:

```bash
cd platform/orpheus-common
make install
```

This does steps 2 and 3 automatically.

---

## For Development

If you want to contribute or run tests:

```bash
cd platform/orpheus-common
make install-dev
```

This installs additional tools:
- pytest (testing)
- ruff (linting/formatting)

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'yaml'"

**Problem:** Dependencies weren't installed  
**Solution:** Run `pip install -r requirements.txt` first

### "ERROR: File 'setup.py' not found"

**Problem:** Old pip version needs setup.py (which we now have!)  
**Solution:** Make sure you're in `platform/orpheus-common/` directory and setup.py exists

### "Permission denied"

**Problem:** System-wide install attempt  
**Solution:** Use a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate  # On Linux/Mac
# or
venv\Scripts\activate     # On Windows

# Then install
pip install -r requirements.txt
pip install -e .
```

---

## Installing in Other Services

Once orpheus-common is installed, use it in other services:

### In Dashboard (services/orpheus-dashboard/)

Edit `requirements.txt`:
```txt
# Add this line at the top:
-e ../../platform/orpheus-common

# Keep existing requirements:
fastapi==0.104.1
uvicorn[standard]==0.24.0
# ... etc
```

Then:
```bash
cd services/orpheus-dashboard
pip install -r requirements.txt
```

### In New Agents

Create `requirements.txt`:
```txt
-e ../../platform/orpheus-common

# Add agent-specific dependencies
# e.g., for audio detection:
numpy>=1.24.0
scipy>=1.10.0
```

---

## Python Version Requirements

- **Minimum:** Python 3.9.5 (Jetson Orin NX Ubuntu 20.04)
- **Recommended:** Python 3.9+
- **Tested on:** Python 3.9, 3.10, 3.11

---

## What Gets Installed

**Package:** `orpheus-common` version 0.1.0

**Modules available:**
```python
from orpheus_common import Config, setup_logging
from orpheus_common.mqtt import MQTTClient
from orpheus_common.hardware import CameraRegistry, AmcrestCamera
from orpheus_common.system.health import SystemHealth
from orpheus_common.storage import get_audio_path, get_video_path
from orpheus_common.utils.time import utc_now_iso
```

---

## Next Steps

After installation:
1. Read `README.md` for API documentation
2. Check `examples/usage_example.py` for complete examples
3. Start migrating dashboard: see `QUICK_START_GUIDE.md`

---

**You're ready to go!** The package is installed and importable from anywhere in your Python environment.
