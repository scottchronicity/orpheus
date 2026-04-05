"""
Orpheus Common Library - Usage Examples

This file demonstrates how to use the orpheus-common library
across different Orpheus services and agents.
"""

from datetime import date

from orpheus_common.config import Config
from orpheus_common.hardware import CameraRegistry
from orpheus_common.logging import setup_logging
from orpheus_common.mqtt import MQTTClient
from orpheus_common.storage import get_audio_path, get_video_path
from orpheus_common.system.health import SystemHealth
from orpheus_common.utils.time import parse_iso_timestamp, utc_now_iso

# Example 1: Configuration Management
print("=" * 60)
print("Example 1: Configuration Management")
print("=" * 60)

# Load YAML config from ./config/cameras.yaml or /etc/orpheus/cameras.yaml
config = Config.load("cameras.yaml", required=False)

# Get configuration values with defaults
camera_user = config.get("cameras.auth.username", default="admin")
north_cam_ip = config.get("cameras.north.host", default="192.168.1.100")

print(f"Camera user: {camera_user}")
print(f"North camera IP: {north_cam_ip}")

# Environment variable override: ORPHEUS_CAMERAS_NORTH_HOST
# Will override the YAML value
print()


# Example 2: Logging Setup
print("=" * 60)
print("Example 2: Logging Setup")
print("=" * 60)

# Setup logging for your service
logger = setup_logging("my-agent", level="INFO")

logger.info("Service starting...")
logger.debug("This won't show at INFO level")
logger.warning("This is a warning")
logger.error("This is an error")

print()


# Example 3: MQTT Communication
print("=" * 60)
print("Example 3: MQTT Communication")
print("=" * 60)

# Create MQTT client
client = MQTTClient(
    broker_host="localhost",
    client_id="example-agent",
    topics=["orpheus/sensors/#"],
    will_topic="orpheus/status/example-agent",
    will_payload={"status": "offline"},
)


# Register message handler
@client.on_message("orpheus/sensors/audio/#")
def handle_audio(topic, payload):
    print(f"Audio message on {topic}: {payload}")


# Publish message
def example_publish():
    client.publish(
        "orpheus/detection/audio",
        {
            "type": "detection",
            "species": "amecro",
            "confidence": 0.95,
            "timestamp": "2025-11-25T12:34:56.789Z",
        },
    )


# Connect (commented out for example)
# client.connect()
# example_publish()

print("MQTT client configured (not connected in example)")
print()


# Example 4: Storage Utilities
print("=" * 60)
print("Example 4: Storage Utilities")
print("=" * 60)

# Get standardized paths
audio_dir = get_audio_path("raw", date.today(), channel=1)
video_dir = get_video_path("snapshots", date.today(), camera="north")

print(f"Audio directory: {audio_dir}")
print(f"Video directory: {video_dir}")

# Ensure directories exist (commented out to not create dirs in example)
# ensure_directory(audio_dir)

print()


# Example 5: Hardware Abstractions - Cameras
print("=" * 60)
print("Example 5: Hardware Abstractions - Cameras")
print("=" * 60)

# Load cameras from configuration
registry = CameraRegistry.from_config("cameras.yaml")

if len(registry) > 0:
    print(f"Loaded {len(registry)} cameras")

    # Get specific camera
    camera = registry.get("north")
    if camera:
        print(f"Camera: {camera.name} at {camera.host}")

        # Check health (commented out to avoid actual camera calls)
        # health = camera.get_health_status()
        # print(f"Status: {health['status']}")
        # print(f"Network: {health['checks']['network']['ok']}")
else:
    print("No cameras configured (expected in example)")

print()


# Example 6: System Health Monitoring
print("=" * 60)
print("Example 6: System Health Monitoring")
print("=" * 60)

health = SystemHealth()

# Get system metrics
metrics = health.get_metrics()
print(f"CPU: {metrics.cpu_percent}%")
print(f"Memory: {metrics.memory_percent}%")
print(f"Disk: {metrics.disk_percent}%")
print(f"Uptime: {metrics.uptime_seconds}s")

# Check storage
storage = health.get_data_storage()
if storage.ok:
    print(f"\nData storage: {storage.percent}% full")
    print(f"Free: {storage.free / (1024**3):.2f} GB")
else:
    print(f"\nData storage error: {storage.error}")

print()


# Example 7: Time Utilities
print("=" * 60)
print("Example 7: Time Utilities")
print("=" * 60)

# Get current timestamp
timestamp = utc_now_iso()
print(f"Current time: {timestamp}")

# Parse timestamp
dt = parse_iso_timestamp(timestamp)
print(f"Parsed datetime: {dt}")

print()


# Example 8: Complete Agent Pattern
print("=" * 60)
print("Example 8: Complete Agent Pattern")
print("=" * 60)

"""
Here's a complete pattern for an Orpheus agent:

```python
from orpheus_common.config import Config
from orpheus_common.logging import setup_logging
from orpheus_common.mqtt import MQTTClient
from orpheus_common.storage import get_audio_path, ensure_directory
from orpheus_common.utils.time import utc_now_iso

# Setup
logger = setup_logging("my-detection-agent", level="INFO")
config = Config.load("agent-config.yaml")
mqtt_client = MQTTClient(
    broker_host=config.get("mqtt.host", default="localhost"),
    client_id="my-detection-agent",
)

# Storage
output_dir = get_audio_path("detections", date.today())
ensure_directory(output_dir)

# Message handler
@mqtt_client.on_message("orpheus/sensors/audio/#")
def handle_audio_data(topic, payload):
    logger.info(f"Processing audio from {topic}")

    # Your detection logic here
    detection = run_detection(payload)

    if detection['confidence'] > 0.8:
        # Publish detection
        mqtt_client.publish("orpheus/detection/audio", {
            "species": detection['species'],
            "confidence": detection['confidence'],
            "timestamp": utc_now_iso(),
            "channel": payload['channel']
        })

        logger.info(f"Detection: {detection['species']} ({detection['confidence']:.2f})")

# Start
logger.info("Agent starting...")
mqtt_client.connect()

# Keep running
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logger.info("Shutting down...")
    mqtt_client.disconnect()
```
"""

print("See source code for complete agent pattern example")
print()

print("=" * 60)
print("Examples complete!")
print("=" * 60)
