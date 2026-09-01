# Orpheus Bluetooth Auto-Connect Service

Automatic Bluetooth speaker connection service for the Orpheus wildlife monitoring system.

## Overview

This service ensures that a configured Bluetooth speaker automatically connects on system boot and reconnects if the connection drops. It's designed for autonomous operation where manual Bluetooth pairing after reboots is not practical.

## Features

- **Auto-connect on boot**: Connects to configured Bluetooth device after `bluetooth.service` is ready
- **Auto-reconnect**: Monitors connection and reconnects if it drops
- **Automatic audio switching**: Switches PulseAudio output to the connected Bluetooth device
- **Configurable**: Easy to adapt for different Bluetooth devices and users
- **Robust**: Exponential backoff on repeated failures
- **Observable**: Comprehensive logging via journald

## Installation

```bash
# Default installation (JBL Flip 4: FC:58:FA:02:AF:28)
make install

# Custom Bluetooth device
BLUETOOTH_SPEAKER_MAC=XX:XX:XX:XX:XX:XX make install
```

## Configuration

The service supports two configuration options:

1. **BLUETOOTH_SPEAKER_MAC**: MAC address of the Bluetooth device (e.g., `FC:58:FA:02:AF:28`)
2. **AUDIO_USER**: User account running PulseAudio (defaults to `orpheus`)

Configuration can be set via:

1. Environment variables during installation
2. Configuration file `/etc/orpheus/bluetooth-autoconnect/config.env` (can be edited post-install)

To change configuration after installation:

```bash
# Edit the configuration file
sudo nano /etc/orpheus/bluetooth-autoconnect/config.env

# Example content:
# BLUETOOTH_SPEAKER_MAC=XX:XX:XX:XX:XX:XX
# AUDIO_USER=orpheus

# Restart the service
sudo systemctl restart orpheus-bluetooth-autoconnect.service
```

## Usage

```bash
# Check status
make status

# View logs
make logs

# Follow logs in real-time
make logs-follow

# Restart service
make restart

# Stop service
make stop

# Start service
make start
```

## Troubleshooting

### Service won't start

```bash
# Check service logs
sudo journalctl -u orpheus-bluetooth-autoconnect.service -n 50

# Check Bluetooth service status
systemctl status bluetooth.service

# Verify bluetoothctl is working
bluetoothctl show
```

### Device won't connect

```bash
# Try manual connection to diagnose
bluetoothctl

# In bluetoothctl:
power on
agent on
scan on
# Wait for device to appear
pair XX:XX:XX:XX:XX:XX
trust XX:XX:XX:XX:XX:XX
connect XX:XX:XX:XX:XX:XX
```

### View connection attempts

```bash
# Real-time logs
sudo journalctl -u orpheus-bluetooth-autoconnect.service -f

# Recent logs with timestamps
sudo journalctl -u orpheus-bluetooth-autoconnect.service --since "10 minutes ago"
```

## Architecture

The service consists of:

1. **Connection Script** (`/usr/local/bin/orpheus-bluetooth-connect`)
   - Main loop that monitors and maintains Bluetooth connection
   - Trusts device on startup
   - Checks connection status every 10 seconds
   - Reconnects if disconnected
   - Automatically switches PulseAudio output to the connected device
   - Waits 2 seconds for sink initialization before switching
   - Converts MAC address format (colons to underscores) for PulseAudio sink name
   - Runs `pactl` as the configured user via `su`

2. **Systemd Service** (`orpheus-bluetooth-autoconnect.service`)
   - Starts after `bluetooth.service`
   - Restarts automatically on failure (exponential backoff)
   - Resource-limited (64MB RAM, 10% CPU)
   - Logs to journald

3. **Configuration** (`/etc/orpheus/bluetooth-autoconnect/config.env`)
   - Contains `BLUETOOTH_SPEAKER_MAC` setting
   - Contains `AUDIO_USER` setting
   - Sourced by connection script

## Files

| Path | Description |
| ------ | ------------- |
| `/etc/systemd/system/orpheus-bluetooth-autoconnect.service` | Systemd service unit |
| `/usr/local/bin/orpheus-bluetooth-connect` | Connection monitoring script |
| `/etc/orpheus/bluetooth-autoconnect/config.env` | Configuration file |

## Development

```bash
# Run tests
make test

# Lint code
make lint

# Format code
make format

# Validate Python 3.9.5 compatibility
make dry-run
```

## Uninstallation

```bash
# Remove service
make uninstall

# Complete cleanup (removes config too)
make clean
```

## MQTT Topics

**Subscribes to:** Nothing.

**Publishes to:** Nothing.

This service does not participate in the MQTT bus. It is a pure infrastructure service that manages the Bluetooth connection at the OS level. Its only role in the Orpheus system is to ensure the Bluetooth audio sink is available so that `orpheus-agent-audio-playback` can send audio to it.

## Integration with Orpheus

This service is designed to work seamlessly with the Orpheus audio actuation system. After the Jetson reboots, audio playback to the Bluetooth speaker will work automatically without manual intervention.

## Requirements

- **Bluetooth**: `bluez` package (auto-installed if missing)
- **Python**: 3.9+ (for test suite)
- **System**: Linux with systemd

## License

Part of the Orpheus wildlife monitoring system.
