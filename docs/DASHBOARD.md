# Orpheus Dashboard Design (Legacy)

> ⚠️ **Note:** This documents the legacy `orpheus-dashboard` service. For the modern React-based UI, see [`services/orpheus_ui/README.md`](../services/orpheus_ui/README.md) and [`docs/copilot-workspace-instructions/orpheus-ui.instructions.md`](./copilot-workspace-instructions/orpheus-ui.instructions.md).

**See [`CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md) for core development guidelines.**

This document describes the architecture and patterns for the legacy Orpheus web dashboard.

---

## Architecture Overview

- **Backend**: FastAPI serving REST API + static files
- **Frontend**: Vanilla HTML/JS/CSS in `static/` directory  
- **Data**: MQTT subscriptions cached in memory, no persistent storage
- **Port**: 8080 (default) - will move to 8081 when orpheus-ui replaces it

---

## Backend Patterns

### API Endpoint Structure

```python
@app.get("/api/{resource}")
def get_resource():
    """Get current state of resource."""
    return {"data": ..., "error": None}

@app.get("/api/diagnostics/{subsystem}")
def get_diagnostics():
    """Get health/status of subsystem."""
    return {"status": "ok", "details": {...}}

@app.post("/api/{resource}/{action}")
def perform_action(request: RequestModel):
    """Trigger an action via MQTT."""
    _mqtt_client.publish("orpheus/...", request.dict())
    return {"success": True, "message": "..."}
```

### MQTT Integration

Subscribe to topics in the `lifespan` context manager:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    global _mqtt_client
    
    # Setup MQTT client
    _mqtt_client = MQTTClient(
        broker_host=config.mqtt.broker_host,
        broker_port=config.mqtt.broker_port,
        client_id="orpheus-dashboard"
    )
    
    # Subscribe to topics
    _mqtt_client.subscribe("orpheus/audio/motion/events", _on_audio_motion)
    _mqtt_client.subscribe("orpheus/detection/bird/events", _on_bird_detection)
    _mqtt_client.subscribe("orpheus/system/+/health", _on_health_update)
    
    # Connect
    _mqtt_client.connect()
    logger.info("Dashboard MQTT client connected")
    
    yield  # Application runs here
    
    # Cleanup
    _mqtt_client.disconnect()
    logger.info("Dashboard MQTT client disconnected")

app = FastAPI(lifespan=lifespan)
```

### Caching Pattern

Use thread-safe caches for MQTT data:

```python
from threading import Lock
from typing import Optional, Dict, Any

# Cache and lock
_cache: Optional[Dict[str, Any]] = None
_cache_lock = Lock()

def _on_message(topic: str, payload: dict):
    """Handle incoming MQTT message."""
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = {}
        _cache[topic] = payload
        _cache["last_update"] = time.time()

@app.get("/api/data")
def get_data():
    """Get cached data."""
    with _cache_lock:
        if _cache is None:
            return {"data": None, "error": "No data received"}
        return {"data": _cache, "error": None}
```

### Health Status Aggregation

```python
_agent_health: Dict[str, Dict[str, Any]] = {}
_health_lock = Lock()

def _on_health_message(topic: str, payload: dict):
    """Cache agent health messages."""
    # Extract agent name from topic: orpheus/system/{agent}/health
    agent_name = topic.split("/")[2]
    
    with _health_lock:
        _agent_health[agent_name] = {
            "status": payload.get("status"),
            "timestamp": payload.get("timestamp"),
            "last_seen": time.time()
        }

@app.get("/api/health")
def get_system_health():
    """Get health status of all agents."""
    with _health_lock:
        return {
            "agents": _agent_health,
            "timestamp": time.time()
        }
```

---

## Frontend Patterns

### Technology Choices

- **No frameworks** - Vanilla JavaScript for simplicity
- **ES6 modules** - Use modern JavaScript features
- **Fetch API** - For HTTP requests
- **WebSocket** (future) - For real-time updates

### API Polling Pattern

```javascript
// Poll configuration for refresh rate
async function loadConfig() {
    const response = await fetch('/api/config');
    const data = await response.json();
    return data.refresh_interval_ms || 1000;
}

// Poll data with configurable interval
async function pollData() {
    const interval = await loadConfig();
    
    setInterval(async () => {
        try {
            const response = await fetch('/api/data');
            const data = await response.json();
            updateUI(data);
        } catch (error) {
            console.error('Failed to fetch data:', error);
            showError(error);
        }
    }, interval);
}
```

### Status Indicator Pattern

```javascript
function updateHealthIndicator(elementId, status) {
    const indicator = document.getElementById(elementId);
    
    // Remove all status classes
    indicator.classList.remove('status-online', 'status-offline', 'status-degraded');
    
    // Add appropriate class
    if (status === 'online') {
        indicator.classList.add('status-online');
        indicator.textContent = '● Online';
    } else if (status === 'offline') {
        indicator.classList.add('status-offline');
        indicator.textContent = '● Offline';
    } else {
        indicator.classList.add('status-degraded');
        indicator.textContent = '● Degraded';
    }
}
```

### CSS Status Colors

```css
.status-online {
    color: #4caf50;  /* Green */
}

.status-offline {
    color: #f44336;  /* Red */
}

.status-degraded {
    color: #ff9800;  /* Orange */
}
```

---

## Configuration API

Dashboard reads from OrpheusConfig for:

- Refresh intervals
- Agent list to monitor
- Camera configurations
- Storage paths

```python
@app.get("/api/config")
def get_config():
    """Get dashboard configuration."""
    config = OrpheusConfig.get_instance()
    
    return {
        "refresh_interval_ms": config.dashboard.refresh_interval_ms,
        "agents": [
            {"name": "audio-motion", "display": "Audio Motion"},
            {"name": "video-motion", "display": "Video Motion"},
            {"name": "bird-detection", "display": "Bird Detection"},
        ],
        "cameras": [
            {"id": c.id, "name": c.name, "rtsp_url": c.rtsp_url}
            for c in config.cameras
        ]
    }
```

---

## File Serving

### Static Files

```python
from fastapi.staticfiles import StaticFiles

# Serve static files (HTML, CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve index.html at root
@app.get("/")
async def root():
    return FileResponse("static/index.html")
```

### Audio/Video Files

```python
from fastapi.responses import FileResponse

@app.get("/api/audio/{category}/{channel}/{filename}")
def serve_audio(category: str, channel: str, filename: str):
    """Serve audio file from storage."""
    from orpheus_common.storage import get_audio_path
    
    audio_dir = get_audio_path(category=category, channel_id=channel)
    file_path = audio_dir / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        file_path,
        media_type="audio/flac",
        filename=filename
    )
```

---

## Diagnostics API

### Hardware Status

```python
@app.get("/api/diagnostics/audio")
def get_audio_diagnostics():
    """Get audio hardware diagnostics."""
    from orpheus_common.diagnostics import AudioDiagnostics
    
    diag = AudioDiagnostics()
    status = diag.check_all()
    
    return {
        "status": "ok" if all(s["healthy"] for s in status.values()) else "degraded",
        "devices": status
    }

@app.get("/api/diagnostics/cameras")
def get_camera_diagnostics():
    """Get camera diagnostics."""
    from orpheus_common.diagnostics import CameraDiagnostics
    
    diag = CameraDiagnostics()
    status = diag.check_all()
    
    return {
        "status": "ok" if all(s["reachable"] for s in status.values()) else "degraded",
        "cameras": status
    }
```

---

## Testing

### API Testing

```python
from fastapi.testclient import TestClient

def test_get_config():
    """Test configuration endpoint."""
    client = TestClient(app)
    response = client.get("/api/config")
    
    assert response.status_code == 200
    data = response.json()
    assert "refresh_interval_ms" in data
    assert "agents" in data

def test_health_endpoint():
    """Test health status endpoint."""
    client = TestClient(app)
    response = client.get("/api/health")
    
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
```

### MQTT Mocking

```python
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_mqtt():
    """Mock MQTT client."""
    with patch("orpheus_common.mqtt.MQTTClient") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client

def test_mqtt_subscription(mock_mqtt):
    """Test MQTT topic subscriptions."""
    # Trigger lifespan startup
    with TestClient(app):
        # Verify subscriptions
        mock_mqtt.return_value.subscribe.assert_called()
```

---

## Deployment

See [`docs/DEPLOYMENT.md`](./DEPLOYMENT.md) for deployment instructions.

Quick reference:

```bash
cd services/orpheus-dashboard
sudo make install-service
sudo systemctl start orpheus-dashboard
sudo systemctl status orpheus-dashboard

# Access dashboard
http://<jetson-ip>:8080
```

---

## Frontend Development

### Local Development

```bash
cd services/orpheus-dashboard

# Run dashboard in development mode
make run

# Dashboard available at http://localhost:8080
```

### File Structure

```bash
static/
├── index.html           # Main page
├── css/
│   └── style.css        # Styles
└── js/
    ├── main.js          # Main application logic
    ├── api.js           # API wrapper functions
    └── ui.js            # UI update functions
```

---

## Best Practices

### Backend

- ✅ Use lifespan context manager for MQTT lifecycle
- ✅ Thread-safe caching with locks
- ✅ Return consistent JSON structure: `{"data": ..., "error": None}`
- ✅ Log all MQTT message handling
- ✅ Validate MQTT payloads before caching

### Frontend

- ✅ Use fetch API with error handling
- ✅ Show user-friendly error messages
- ✅ Poll configuration to get refresh interval
- ✅ Use semantic HTML and accessible UI
- ✅ Display clear online/offline/degraded status

### Testing

See [`docs/TESTING.md`](./TESTING.md) for testing guidance.

---

## References

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [MQTT Client (orpheus-common)](../platform/orpheus-common/src/orpheus_common/mqtt.py)
- [`CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md) - Core guidelines
- [`docs/copilot-workspace-instructions/dashboard.instructions.md`](../docs/copilot-workspace-instructions/dashboard.instructions.md) - Quick reference patterns
