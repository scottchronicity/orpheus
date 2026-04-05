---
applyTo: "services/orpheus-dashboard/**"
---

# Dashboard Service Instructions

**See [`CODING_AGENT_CONTEXT.md`](../../CODING_AGENT_CONTEXT.md) for core guidelines.** This file contains dashboard-specific quick reference patterns.

**See [`docs/DASHBOARD.md`](../DASHBOARD.md) for comprehensive dashboard architecture and patterns.**

---

## Architecture

- **Backend**: FastAPI serving REST API + static files
- **Frontend**: Vanilla HTML/JS/CSS in `static/` directory
- **Data**: MQTT subscriptions cached in memory, no persistent storage

---

## API Endpoint Patterns

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

## MQTT Integration

Subscribe in the `lifespan` context manager:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mqtt_client
    _mqtt_client = MQTTClient(...)
    _mqtt_client.subscribe("orpheus/topic/#", _on_message_handler)
    _mqtt_client.connect()
    yield
    _mqtt_client.disconnect()
```

## Caching Pattern

Use thread-safe caches for MQTT data:
```python
_cache: Optional[Dict[str, Any]] = None
_cache_lock = threading.Lock()

def _on_message(topic: str, payload: dict):
    global _cache
    with _cache_lock:
        _cache = payload
```

## Frontend Guidelines

- Use vanilla JS (no frameworks)
- Poll `/api/config` for refresh interval
- Use fetch() for API calls
- Display green/red status indicators for health
