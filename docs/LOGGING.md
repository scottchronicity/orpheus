# Orpheus Logging

Most of this page is the convention for *writing* log calls, which is a
contributor's job. If you are running a station and want to read logs, you need
four things and none of the rest:

```bash
sudo journalctl -u orpheus-agent-audio-motion -f     # follow one unit
sudo journalctl -u "orpheus-*" --since -10m          # everything, last 10 minutes
sudo journalctl -u orpheus-ui -o json | jq .         # the structured payload
make dev-logs SVC=bird-detection                     # dev stack: logs/<service>.log
```

Verbosity is `LOG_LEVEL` in the unit's environment (`DEBUG`, `INFO`, `WARNING`,
`ERROR`); the default is `INFO`. Under `make dev-stack` the same output also
lands in `logs/<service>.log` in the repo.

## Overview

Orpheus uses [structlog](https://www.structlog.org/) for structured, keyword-based logging. All log messages use keyword arguments so logs are machine-parseable and consistent across agents and services.

## Quick Start

```python
from orpheus_common.logging import setup_logging, get_logger

# Setup logging (done once per service/agent, typically in main())
setup_logging("my-agent", level="INFO")

# Get a logger for your module
logger = get_logger(__name__)

# Use keyword arguments for all variable data
logger.info("Operation completed", operation_id=123, duration_ms=45.2)
```

## Core Rules

### 1. Static Messages Only

The log message must be a static string literal describing the event. **Never** include variable data in the message.

```python
# Bad
logger.info(f"Loaded {count} items")
logger.info("Loaded %d items", count)

# Good
logger.info("Loaded items", item_count=count)
```

### 2. Variables as Keywords

All variable data must be passed as keyword arguments after the message.

```python
# Bad
logger.error("Failed to connect to %s:%d", host, port)

# Good
logger.error("Failed to connect", host=host, port=port)
```

### 3. Descriptive Keys

Use clear, descriptive key names that make the log entry self-documenting.

```python
# Bad
logger.debug("Processing", id=x, t=y)

# Good
logger.debug("Processing frame", camera_id=x, timestamp=y)
```

## Log Levels

### CRITICAL

System cannot continue, immediate action required.

```python
logger.critical("Failed to load model, cannot start agent",
                model_path=model_path, error=str(e))
```

Examples: database corruption, critical hardware failure, missing config at startup, out of disk space.

### ERROR

Operation failed but system continues.

```python
logger.error("Failed to process detection event",
             event_id=event_id, channel_id=channel_id, error=str(e))
```

Examples: model inference failed, failed to save file, event-bus publish failed after retries.

### WARNING

Something unexpected happened but was handled gracefully.

```python
logger.warning("Event bus connection lost, will retry",
               broker=broker_host, retry_in_seconds=5)
```

Examples: connection lost (will retry), slow operation, deprecated config option used.

### INFO (Signs of Life)

Important state changes and normal operations.

```python
logger.info("Service started", service_name="audio-motion", pid=os.getpid())
logger.info("Model loaded", model_path=model_path, load_time_ms=elapsed)
logger.info("Detection processed", event_id=event_id, species=species)
```

Examples: service start/stop, event bus connected, model loaded, detection processed, periodic statistics.

### DEBUG

Detailed information for troubleshooting (disabled in production).

```python
logger.debug("Processing frame", camera_id=cam_id, frame_count=count)
```

Examples: individual frame processing, timing details, cache statistics, internal state transitions.

## Exception Handling

### Inside Exception Handlers

Use `logger.exception()` to automatically capture the full traceback:

```python
try:
    risky_operation()
except ValueError as e:
    logger.exception("Operation failed", operation_id=123, error=str(e))
```

**Note:** `logger.exception()` automatically includes the traceback. Only use it inside `except` blocks.

### Outside Exception Handlers

Use `logger.error()` with keyword arguments:

```python
if not is_valid(data):
    logger.error("Invalid data received", data_type=type(data).__name__)
```

## What to Log

### Agent/Service Lifecycle

- Startup (with config details, version, dependencies)
- Shutdown (graceful or unexpected)
- Event-bus connection/disconnection
- Model loading success/failure

### Detection Events

- Detection event processed (INFO with key details)
- Failed to process event (ERROR with full context)
- Periodic statistics (every N events) — **not** every event-bus message

### Health & Performance

- Periodic health checks (every ~5 seconds is fine)
- Resource warnings (high CPU, low disk space)
- Performance degradation (slow operations)
- **Not** every individual health check result

### Configuration

- Configuration loaded/reloaded
- Invalid configuration detected
- Validation warnings

## Common Patterns

### Startup Logging

Always log service name, configuration source, critical dependencies, and listening topics:

```python
logger.info("Starting Audio Motion Detector agent", version=__version__)
logger.info("Configuration loaded", config_path=config_path)
logger.info("Model loaded", embedder=embedder_path, classifier=classifier_path)
logger.info("Subscribed to event-bus subjects", subjects=["orpheus/audio/motion/events"])
```

### Signs of Life

Log periodic statistics to show the system is alive:

```python
if self.events_processed % 100 == 0:
    logger.info("Processing statistics",
                events_processed=self.events_processed,
                detections_found=self.detections_found,
                rate_per_min=self.events_processed / elapsed_minutes)
```

### Graceful Degradation

Log when falling back to defaults:

```python
if not model_available:
    logger.warning("Model file not found, using fallback",
                   expected_path=model_path, fallback_path=fallback_path)
```

## Formatting Values

### Float Precision

Format floats for specific precision when helpful:

```python
logger.info("Threshold updated", old_db=f"{old:.1f}", new_db=f"{new:.1f}")
```

### Path Objects

No need to convert `pathlib.Path` objects — structlog handles them:

```python
logger.info("File saved", path=output_path)  # Path object is fine
```

### Complex Objects

For complex objects, convert to a string representation:

```python
logger.debug("Config loaded", config=str(config_obj))
```

## Production Environment

- **Systemd integration**: Logs automatically go to journald with structured metadata
- **JSON output**: Logs formatted as JSON when running under systemd (auto-detected)
- **Console output**: Colorful human-readable output in development
- **Searchability**: each event is a JSON object, but it reaches the journal as a
  *message string*, so `-o json` hands you the journal envelope with your payload
  escaped inside `MESSAGE`. Pull the message out first and strip the colour codes:
  `journalctl -u orpheus-ui -o cat | sed 's/\x1b\[[0-9;]*m//g' | jq 'select(.event=="…")'`.
  With `systemd-python` installed the journal handler wraps the payload a second time
  and every event is written twice — once by that handler, once through stdout — so
  expect duplicate lines and an extra `| jq -r .event` unwrap. Nothing in this repo
  ships a log-aggregation stack.

## Testing Logs

Capture and inspect logs in tests:

```python
import logging

def test_logging(caplog):
    with caplog.at_level(logging.INFO):
        logger.info("Test message", test_id=123)

    assert "Test message" in caplog.text
    assert "test_id" in caplog.text
```

## Anti-Patterns

### Don't use print()

```python
# Bad
print("Processing event...")

# Good
logger.info("Processing detection event", event_id=event_id)
```

### Don't log secrets or sensitive data

```python
# Bad
logger.info("Connecting", api_key=api_key)
```

### Don't log entire large objects

```python
# Bad
logger.debug("Full payload", payload=payload)

# Good
logger.debug("Processing payload", event_id=payload.get("event_id"),
             size_bytes=len(str(payload)))
```

### Don't ignore exceptions silently

```python
# Bad
try:
    process_detection()
except Exception:
    pass

# Good
try:
    process_detection()
except Exception as e:
    logger.exception("Failed to process detection", error=str(e))
```

### Don't log every iteration

```python
# Bad — logs every frame
for frame in video_stream:
    logger.debug("Processing frame", frame_num=frame_num)

# Good — log periodically
if frame_num % 100 == 0:
    logger.debug("Processed frames", frame_count=frame_num, fps=fps)
```

## Monitoring & Alerting

Key metrics to watch from logs:

- ERROR and CRITICAL count per service (alert if > threshold)
- WARNING count (track trends)
- "Signs of life" messages (alert if missing for > 5 minutes)
- Detection event rates (alert on sudden drops)
- Event-bus connection state changes (alert on frequent reconnects)

## Migration Checklist

When converting existing code to structured logging:

- [ ] Replace `%s`, `%d`, `%f` format strings with keyword arguments
- [ ] Convert f-strings in log messages to keyword arguments
- [ ] Change `logger.error(..., exc_info=True)` to `logger.exception()` in except blocks
- [ ] Use descriptive key names (e.g., `camera_id` not `id`)
- [ ] Test that logs are readable and contain expected fields

## References

- [structlog Documentation](https://www.structlog.org/)
- Source: `platform/orpheus-common/src/orpheus_common/logging.py`
