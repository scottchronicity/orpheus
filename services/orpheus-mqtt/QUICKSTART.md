# MQTT Broker Quick Start

Fast reference for common MQTT broker operations in the Orpheus system.

## Installation (One-Time Setup)

```bash
cd services/orpheus-mqtt
sudo make install
```

This installs Mosquitto, configures it for Orpheus, and starts the service.

## Daily Operations

### Check Status
```bash
make status
```

### Test Connection
```bash
make test
```

### View Logs
```bash
make logs              # View recent logs
make logs-follow       # Follow logs in real-time (Ctrl+C to exit)
```

### Start/Stop/Restart
```bash
sudo make start
sudo make stop
sudo make restart
```

## Quick Testing with Command Line

### Subscribe to All Orpheus Topics
```bash
mosquitto_sub -h localhost -t 'orpheus/#' -v
```

### Publish Test Message
```bash
mosquitto_pub -h localhost -t 'orpheus/test' -m 'Hello Orpheus!'
```

### Monitor Audio Detections
```bash
mosquitto_sub -h localhost -t 'orpheus/audio/detections' -v
```

### Monitor Video Detections
```bash
mosquitto_sub -h localhost -t 'orpheus/video/detections' -v
```

### Monitor All Detections (Audio + Video)
```bash
mosquitto_sub -h localhost -t 'orpheus/+/detections' -v
```

## Connection Details for Agents

- **Host**: `localhost`
- **Port**: `1883`
- **Authentication**: None (anonymous)
- **Protocol**: MQTT v3.1.1/v5

## Python Quick Start

```python
import paho.mqtt.client as mqtt

# Create client
client = mqtt.Client("my-agent")

# Connect
client.connect("localhost", 1883, 60)

# Publish
client.publish("orpheus/audio/detections", "message", qos=1)

# Subscribe
def on_message(client, userdata, msg):
    print(f"{msg.topic}: {msg.payload.decode()}")

client.on_message = on_message
client.subscribe("orpheus/#")
client.loop_forever()
```

## Troubleshooting

### Broker Not Running?
```bash
sudo systemctl status orpheus-mqtt.service
sudo journalctl -u orpheus-mqtt.service -n 50
```

### Can't Connect?
```bash
# Check if broker is listening
sudo netstat -tlnp | grep 1883

# Test basic connectivity
mosquitto_pub -h localhost -t 'test' -m 'hello'
```

### Need to Restart?
```bash
sudo systemctl restart orpheus-mqtt.service
```

## Topic Structure

```
orpheus/
├── audio/chunks
├── audio/detections
├── video/frames
├── video/detections
├── events/wildlife
├── system/status
└── control/...
```

Use wildcards:
- `+` for single level: `orpheus/+/detections` 
- `#` for multiple levels: `orpheus/audio/#`

## Getting Help

- Full documentation: See [README.md](README.md)
- Check logs: `make logs`
- Test connection: `make test`
- Validate config: `make validate-config`
