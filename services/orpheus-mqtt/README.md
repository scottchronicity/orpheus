# Orpheus MQTT Message Broker

Production-ready MQTT broker service for the Orpheus wildlife monitoring system. This service provides reliable, persistent message passing between all Orpheus agents and components.

## Table of Contents

- [What is MQTT?](#what-is-mqtt)
- [Why MQTT for Orpheus?](#why-mqtt-for-orpheus)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Verification](#verification)
- [Service Management](#service-management)
- [Topic Naming Conventions](#topic-naming-conventions)
- [Connecting Agents](#connecting-agents)
- [Security Considerations](#security-considerations)
- [Troubleshooting](#troubleshooting)
- [Advanced Configuration](#advanced-configuration)

## What is MQTT?

MQTT (Message Queuing Telemetry Transport) is a lightweight publish/subscribe messaging protocol designed for IoT and machine-to-machine communication. It's perfect for scenarios where:

- Multiple agents need to communicate efficiently
- Network bandwidth is limited
- Devices may connect/disconnect frequently
- Messages need to be retained for late-joining subscribers
- Quality of Service (QoS) guarantees are important

### Key Concepts

- **Broker**: Central message hub (this service)
- **Publisher**: Agent that sends messages to topics
- **Subscriber**: Agent that receives messages from topics
- **Topic**: Named channel for messages (e.g., `orpheus/audio/detections`)
- **QoS**: Quality of Service levels (0=at most once, 1=at least once, 2=exactly once)

## Why MQTT for Orpheus?

The Orpheus wildlife monitoring system uses MQTT because:

1. **Decoupling**: Audio and video agents can operate independently
2. **Scalability**: Easy to add new agents without reconfiguring existing ones
3. **Reliability**: Persistent messages survive broker restarts
4. **Flexibility**: Agents can subscribe only to relevant data streams
5. **Simplicity**: Clean publish/subscribe API for Python/other languages
6. **Standards-based**: Well-supported protocol with mature libraries

### Orpheus Architecture

```bash
┌─────────────────┐        ┌─────────────────┐
│  Audio Agent    │───────▶│                 │
└─────────────────┘        │                 │
                           │  MQTT Broker    │◀────┐
┌─────────────────┐        │  (localhost)    │     │
│  Video Agent    │───────▶│                 │     │
└─────────────────┘        └─────────────────┘     │
                                   │                │
                                   ▼                │
                           ┌─────────────────┐     │
                           │ Detection Agent │─────┘
                           └─────────────────┘
```

## Quick Start

```bash
# Install the broker (requires sudo)
cd services/orpheus-mqtt
sudo make install

# Verify it's working
make test

# View status
make status

# Monitor logs
make logs
```

## Installation

### Prerequisites

- Ubuntu 20.04+ or Debian-based Linux
- sudo/root access
- systemd (for service management)

### Automated Installation

The installation script handles everything:

```bash
cd services/orpheus-mqtt
sudo make install
```

This will:

1. Install Mosquitto MQTT broker via apt
2. Create `/etc/orpheus/` root configuration directory (shared by all services)
3. Create `/etc/orpheus/mqtt/` for MQTT-specific configuration
4. Install Orpheus MQTT configuration to `/etc/orpheus/mqtt/mosquitto.conf`
5. Create `/var/lib/orpheus/` root data directory (shared by all services)
6. Create `/var/lib/orpheus/mqtt/` for MQTT message persistence
7. Install and enable systemd service
8. Start the broker

### Manual Installation

If you prefer manual installation:

```bash
# Install Mosquitto
sudo apt-get update
sudo apt-get install -y mosquitto mosquitto-clients

# Create shared Orpheus directories
sudo mkdir -p /etc/orpheus/mqtt
sudo mkdir -p /var/lib/orpheus/mqtt
sudo chown mosquitto:mosquitto /var/lib/orpheus/mqtt

# Copy configuration
sudo cp config/mosquitto.conf /etc/orpheus/mqtt/

# Install systemd service
sudo cp systemd/orpheus-mqtt.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable orpheus-mqtt.service
sudo systemctl start orpheus-mqtt.service
```

**Note**: The `/etc/orpheus/` and `/var/lib/orpheus/` directories are shared by all Orpheus services. Each service uses its own subdirectory (e.g., `/etc/orpheus/mqtt/`, `/etc/orpheus/audio/`, etc.).

## Verification

### Quick Test

```bash
make test
```

This runs `scripts/test-connection.py` which performs a complete publish/subscribe test cycle.

### Manual Testing

Open two terminals:

**Terminal 1** (Subscriber):

```bash
mosquitto_sub -h localhost -t 'orpheus/#' -v
```

**Terminal 2** (Publisher):

```bash
mosquitto_pub -h localhost -t 'orpheus/test' -m 'Hello from Orpheus!'
```

You should see the message appear in Terminal 1.

### Check Service Status

```bash
make status
# or
systemctl status orpheus-mqtt.service
```

## Service Management

### Makefile Commands

```bash
make status    # Check if broker is running
make start     # Start the broker
make stop      # Stop the broker
make restart   # Restart the broker
make logs      # View recent logs
make health    # Quick health check
```

### Systemd Commands

```bash
# Status
sudo systemctl status orpheus-mqtt.service

# Start/Stop/Restart
sudo systemctl start orpheus-mqtt.service
sudo systemctl stop orpheus-mqtt.service
sudo systemctl restart orpheus-mqtt.service

# Enable/Disable auto-start on boot
sudo systemctl enable orpheus-mqtt.service
sudo systemctl disable orpheus-mqtt.service

# View logs
journalctl -u orpheus-mqtt.service -f
```

## Topic Naming Conventions

Orpheus uses a hierarchical topic structure for organization and filtering:

```bash
orpheus/
├── audio/
│   ├── chunks           # Raw audio data chunks
│   ├── detections       # Wildlife audio detection results
│   └── status           # Audio agent status/health
├── video/
│   ├── frames           # Sampled video frames
│   ├── detections       # Wildlife video detection results
│   └── status           # Video agent status/health
├── events/
│   ├── wildlife         # Confirmed wildlife events (combined audio+video)
│   ├── alerts           # High-priority alerts
│   └── activity         # General activity events
├── system/
│   ├── status           # System-wide health/status
│   ├── metrics          # Performance metrics
│   └── errors           # Error reports
└── control/
    ├── cameras          # Camera control commands
    ├── audio            # Audio system commands
    └── recording        # Recording start/stop commands
```

### Topic Design Guidelines

1. **Use hierarchical paths**: `orpheus/category/subcategory/detail`
2. **Be specific but not too deep**: Max 4-5 levels
3. **Use singular nouns**: `detection` not `detections` (except for collections)
4. **Lowercase with underscores**: `wildlife_event` not `WildlifeEvent`
5. **Avoid spaces**: Use underscores or hyphens
6. **Include metadata in payload**: Don't encode data in topic path

### Wildcards for Subscriptions

- `+`: Single-level wildcard (e.g., `orpheus/+/detections` matches audio and video)
- `#`: Multi-level wildcard (e.g., `orpheus/audio/#` matches all audio topics)

**Examples:**

```python
# Subscribe to all detections (audio and video)
client.subscribe("orpheus/+/detections")

# Subscribe to everything under audio
client.subscribe("orpheus/audio/#")

# Subscribe to all system messages
client.subscribe("orpheus/system/#")
```

## Connecting Agents

### Python Example

Install the MQTT client library:

```bash
pip install paho-mqtt
```

Basic publisher:

```python
import paho.mqtt.client as mqtt
import json

# Connect to broker
client = mqtt.Client("orpheus-audio-agent")
client.connect("localhost", 1883, 60)

# Publish a detection
detection = {
    "timestamp": "2025-11-07T10:30:00Z",
    "species": "bird_chirping",
    "confidence": 0.87,
    "source": "audio_agent_1"
}
client.publish("orpheus/audio/detections", json.dumps(detection), qos=1)
```

Basic subscriber:

```python
import paho.mqtt.client as mqtt

def on_message(client, userdata, msg):
    print(f"Received on {msg.topic}: {msg.payload.decode()}")

client = mqtt.Client("orpheus-monitor")
client.on_message = on_message
client.connect("localhost", 1883, 60)
client.subscribe("orpheus/#")
client.loop_forever()
```

### Connection Parameters

- **Host**: `localhost` (127.0.0.1)
- **Port**: `1883`
- **Authentication**: None (anonymous allowed)
- **TLS/SSL**: Not enabled (localhost only)
- **Keep-alive**: 60 seconds recommended

### Quality of Service (QoS)

Choose QoS level based on importance:

- **QoS 0** (At most once): System metrics, non-critical status updates
- **QoS 1** (At least once): Detection results, events (may receive duplicates)
- **QoS 2** (Exactly once): Critical commands, alerts (highest overhead)

**Recommendation**: Use QoS 1 for most Orpheus data (good balance of reliability and performance).

## Security Considerations

### Current Security Model

The Orpheus MQTT broker is configured for **localhost-only access**:

- ✅ Listens on `127.0.0.1:1883` (not accessible from network)
- ✅ Only local processes can connect
- ✅ Anonymous authentication (no password required)
- ✅ Suitable for single-machine deployments

### Why Localhost Only?

1. **Security**: No external network exposure prevents unauthorized access
2. **Simplicity**: No need to manage passwords/certificates for local agents
3. **Performance**: Local connections are faster than network
4. **Typical Use Case**: All agents run on the same Jetson/edge device

### When You Need Remote Access

If you need agents on different machines (e.g., multiple cameras), you'll need to:

1. **Enable Network Listener**:

   ```conf
   listener 1883 0.0.0.0  # Listen on all interfaces
   ```

2. **Enable Authentication**:

   ```bash
   # Create password file
   sudo mosquitto_passwd -c /etc/orpheus/mosquitto_passwd orpheus_agent
   ```

   Update config:

   ```conf
   allow_anonymous false
   password_file /etc/orpheus/mosquitto_passwd
   ```

3. **Enable TLS/SSL** (strongly recommended for network access):

   ```conf
   listener 8883
   cafile /etc/orpheus/certs/ca.crt
   certfile /etc/orpheus/certs/server.crt
   keyfile /etc/orpheus/certs/server.key
   ```

4. **Configure Firewall**:

   ```bash
   sudo ufw allow 1883/tcp  # Or 8883 for TLS
   ```

### Production Security Checklist

For production deployments:

- [ ] Use TLS/SSL encryption
- [ ] Enable password authentication
- [ ] Implement Access Control Lists (ACLs)
- [ ] Limit connection rates (DoS protection)
- [ ] Monitor failed authentication attempts
- [ ] Regularly rotate credentials
- [ ] Use client certificates for high-security environments

## Troubleshooting

### Broker Won't Start

**Check service status:**

```bash
sudo systemctl status orpheus-mqtt.service
```

**View detailed logs:**

```bash
sudo journalctl -u orpheus-mqtt.service -n 100
```

**Common causes:**

- Configuration file syntax error: `sudo mosquitto -c /etc/orpheus/mqtt/mosquitto.conf -t`
- Persistence directory permissions: `ls -la /var/lib/orpheus/mqtt`
- Port 1883 already in use: `sudo lsof -i :1883`

### Can't Connect to Broker

**Verify broker is listening:**

```bash
sudo netstat -tlnp | grep 1883
# or
sudo ss -tlnp | grep 1883
```

**Test with mosquitto_pub:**

```bash
mosquitto_pub -h localhost -t 'test' -m 'hello'
# No error = working
```

**Check firewall (if connecting remotely):**

```bash
sudo ufw status
```

### Messages Not Being Received

**Check topic spelling:**

- MQTT topics are case-sensitive
- Verify wildcards (`+`, `#`) are correct

**Verify subscription:**

```bash
mosquitto_sub -h localhost -t 'orpheus/#' -v
```

**Check QoS levels:**

- Ensure publisher and subscriber QoS are compatible

### High Memory Usage

**Check retained messages:**

```bash
# Connect and count retained messages
mosquitto_sub -h localhost -t '#' -v --retained-only | wc -l
```

**Clear retained messages if needed:**

```bash
# Publish empty message with retain flag
mosquitto_pub -h localhost -t 'topic/to/clear' -n -r
```

### Persistence Issues

**Check disk space:**

```bash
df -h /var/lib/orpheus/mqtt
```

**Verify permissions:**

```bash
ls -la /var/lib/orpheus/mqtt
# Should be owned by mosquitto:mosquitto
```

**Rebuild persistence (last resort):**

```bash
sudo systemctl stop orpheus-mqtt.service
sudo rm -rf /var/lib/orpheus/mqtt/*
sudo systemctl start orpheus-mqtt.service
```

### Common Error Messages

| Error | Cause | Solution |
| ------- | ------- | ---------- |
| `Connection refused` | Broker not running | `sudo systemctl start orpheus-mqtt.service` |
| `Error: Address already in use` | Port 1883 busy | Find and stop conflicting process |
| `Error loading config` | Syntax error in conf | Validate with `mosquitto -c ... -t` |
| `Permission denied` | Wrong file permissions | Fix ownership/permissions |

## Advanced Configuration

### Increasing Message Size Limit

For large audio/video chunks:

```conf
# In /etc/orpheus/mqtt/mosquitto.conf
max_packet_size 52428800  # 50MB
```

### Tuning Performance

For high-throughput scenarios:

```conf
max_inflight_messages 40
max_queued_messages 2000
```

### Custom Logging

To log to a file instead of systemd journal:

```conf
log_dest file /var/log/orpheus/mqtt.log
log_type all
```

### Bridge to Remote Broker

To forward messages to a cloud MQTT broker:

```conf
connection cloud-bridge
address mqtt.example.com:1883
topic orpheus/# out 0
cleansession false
```

## Files and Directories

### System-Wide Orpheus Directories

These directories are **shared by all Orpheus services**:

| Path | Purpose | Owner |
| ------ | --------- | ------- |
| `/etc/orpheus/` | Root configuration directory | root |
| `/var/lib/orpheus/` | Root data/persistence directory | varies |
| `/var/log/orpheus/` | Root log directory (if not using systemd) | varies |

Each service creates its own subdirectory within these shared roots.

### MQTT Broker Files

| Path | Description |
| ------ | ------------- |
| `/etc/orpheus/mqtt/mosquitto.conf` | MQTT broker configuration |
| `/etc/systemd/system/orpheus-mqtt.service` | Systemd service unit |
| `/var/lib/orpheus/mqtt/` | Message persistence directory |

### Source Files

| Path | Description |
| ------ | ------------- |
| `config/mosquitto.conf` | Template configuration |
| `systemd/orpheus-mqtt.service` | Template service file |
| `scripts/install.sh` | Installation script |
| `scripts/test-connection.py` | Connection test utility |
| `Makefile` | Build/management targets |

### Important Notes

- **Never delete** `/etc/orpheus/` or `/var/lib/orpheus/` - they are shared infrastructure
- Each service only manages its own subdirectory (e.g., `/etc/orpheus/mqtt/`)
- The `make clean` target only removes MQTT-specific files, not shared directories
- See `SYSTEM_DIRECTORIES.md` for complete directory hierarchy documentation

## Resources

### Documentation

- [Mosquitto Documentation](https://mosquitto.org/documentation/)
- [MQTT Protocol Specification](https://mqtt.org/mqtt-specification/)
- [Paho Python Client](https://www.eclipse.org/paho/index.php?page=clients/python/docs/index.php)

### Useful Tools

- **mosquitto_pub**: Command-line publisher
- **mosquitto_sub**: Command-line subscriber
- **MQTT Explorer**: GUI client for debugging ([MQTT Explorer](http://mqtt-explorer.com/))
- **mosquitto_passwd**: Password file management

### Example Commands

```bash
# Monitor all Orpheus topics
mosquitto_sub -h localhost -t 'orpheus/#' -v

# Publish test detection
mosquitto_pub -h localhost -t 'orpheus/audio/detections' \
  -m '{"species":"bird","confidence":0.9}'

# Check broker statistics
mosquitto_sub -h localhost -t '$SYS/#' -v
```

## Support

For issues, questions, or contributions:

- GitHub: <https://github.com/scottchronicity/orpheus>
- Issues: Open an issue on GitHub
- Documentation: See main Orpheus README

## License

This component is part of the Orpheus wildlife monitoring system. See the main LICENSE file in the repository root.

---

**Last Updated**: November 7, 2025  
**Version**: 1.0.0  
**Maintainer**: Orpheus Project Team
