# Orpheus Deployment Quick Reference

## First-Time Setup (Jetson)

```bash
# 1. Clone repository
cd ~ && mkdir -p runtime/orpheus
cd runtime/orpheus
git clone https://github.com/scottchronicity/orpheus.git .

# 2. Install platform library (REQUIRED FIRST)
cd platform/orpheus-common
sudo make install-service

# 3. Configure for your deployment
sudo nano /opt/orpheus/config/orpheus.yaml

# 4. Install services
cd ../../services/orpheus-mqtt && sudo make install-service && sudo systemctl start orpheus-mqtt
cd ../orpheus-dashboard && sudo make install-service && sudo systemctl start orpheus-dashboard

# 5. Install agents
cd ../../agents/orpheus-agent-audio-motion
sudo make install-service
sudo systemctl start orpheus-agent-audio-motion

# 6. Video agents (for camera timelapse)
cd ../orpheus-agent-video-snapshotter && sudo make install-service && sudo systemctl start orpheus-agent-video-snapshotter
cd ../orpheus-agent-video-timelapser && sudo make install-service && sudo systemctl start orpheus-agent-video-timelapser
```

## Root Makefile Commands (Recommended)

The repository includes a root Makefile for easy orchestration across all services and agents:

```bash
# Quick deployment from root directory
cd ~/runtime/orpheus
make status-all       # Check status of all services
make update-all       # Update all services and agents after git pull
make logs-all         # Stream logs from all Orpheus services

# Full installation (first-time setup)
make services-install # Install all systemd services
make services-start   # Start all services

# Service control
make services-stop    # Stop all services
make services-restart # Restart all services
```

## Updating After Git Pull

### Update Platform + Config

```bash
cd ~/runtime/orpheus/platform/orpheus-common
git pull
sudo make install-service  # Redeploys library
sudo make update            # Updates config and restarts services
```

### Update Specific Service

```bash
cd ~/runtime/orpheus/services/orpheus-dashboard
git pull
sudo make update  # Redeploys and restarts
```

### Update Agent

```bash
cd ~/runtime/orpheus/agents/orpheus-agent-audio-motion
git pull
sudo make install-service
sudo systemctl restart orpheus-agent-audio-motion
```

## Check Status

```bash
# All services
systemctl status orpheus-mqtt orpheus-dashboard orpheus-agent-audio-motion orpheus-agent-video-snapshotter orpheus-agent-video-timelapser

# Logs
sudo journalctl -u orpheus-agent-audio-motion -f
sudo journalctl -u orpheus-agent-video-timelapser -f

# Dashboard
http://<jetson-ip>:8080
```

## Architecture

```shell
/opt/orpheus/
├── config/
│   └── orpheus.yaml                 # Single source of truth
├── platform/
│   └── orpheus-common/              # Shared library
├── services/
│   ├── orpheus-dashboard/
│   └── orpheus-mqtt/
└── agents/
    ├── orpheus-agent-audio-motion/
    ├── orpheus-agent-video-snapshotter/
    └── orpheus-agent-video-timelapser/

Each service has its own venv but shares orpheus-common + config
```

## Config Search Order

OrpheusConfig looks for `orpheus.yaml` in this order:

1. `$ORPHEUS_CONFIG_PATH` (explicit override)
2. `/opt/orpheus/config/orpheus.yaml` (production)
3. `/etc/orpheus/orpheus.yaml` (alternative)
4. `config/orpheus.yaml` (development)
5. `orpheus.yaml` (current directory)

## Service Names

- `orpheus-mqtt` - MQTT broker
- `orpheus-dashboard` - Web dashboard
- `orpheus-agent-audio-motion` - Audio motion detector
- `orpheus-agent-video-snapshotter` - Periodic camera snapshots
- `orpheus-agent-video-timelapser` - Timelapse video generation

## Systemd Service Design Principles

All Orpheus services follow these design principles to ensure **resilience and decoupling**:

### Time Synchronization

All services include `After=time-sync.target` to ensure the system clock is synchronized before starting. This prevents:

- Log timestamps showing Unix epoch (1970)
- Incorrect timestamps in recorded events
- Issues with certificate validation

### Loose Coupling

Services use `Wants=` instead of `Requires=` for inter-service dependencies:

```ini
# ✅ Correct: Loose coupling
After=network.target time-sync.target orpheus-mqtt.service
Wants=orpheus-mqtt.service

# ❌ Incorrect: Tight coupling
After=network.target orpheus-mqtt.service
Requires=orpheus-mqtt.service
```

**Why `Wants=` over `Requires=`:**

- Services can start even if dependencies aren't running
- If MQTT crashes, agents aren't forcibly stopped
- Dashboard remains accessible for diagnostics even if MQTT is down
- Each service handles connection failures gracefully in code

### Restart Policy

All services use `Restart=always` or `Restart=on-failure` with appropriate `RestartSec=` delays to handle transient failures without overwhelming the system.

### Design Rationale

The system is designed so each service can **independently start, stop, and restart** without cascading failures. This is critical for:

- **Debugging**: Dashboard should always be available to show system state
- **Maintenance**: Update one service without affecting others
- **Recovery**: Services reconnect automatically when dependencies come back online

## Systemd Journal Logging

Orpheus services automatically integrate with systemd journal for production logging.

### Requirements

To enable journal integration on Jetson, install systemd-python:

```bash
sudo apt-get install -y libsystemd-dev pkg-config
/opt/orpheus/<component>/venv/bin/pip install systemd-python>=235
```

This step is **optional** - services will work without it, logging to stdout/stderr. With systemd-python installed, logs are sent directly to the journal with proper metadata and also to stdout for backwards compatibility.

### Viewing Logs

```bash
# Follow logs for a service
sudo journalctl -u orpheus-dashboard -f

# View logs from the last hour
sudo journalctl -u orpheus-agent-audio-motion --since "1 hour ago"

# View logs from all Orpheus services
sudo journalctl -u "orpheus-*" -f
```

### Log Behavior

- **Development mode** (not under systemd): Logs to console with timestamps
- **Production mode** (under systemd without systemd-python): Logs to stdout/stderr, captured by journal
- **Production mode** (under systemd with systemd-python): Logs directly to journal with structured metadata + stdout

See [INSTALLATION.md](INSTALLATION.md) for full details.
