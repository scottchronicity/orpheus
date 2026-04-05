# Orpheus Installation Guide

This guide covers production deployment of the Orpheus cross-species communication system on edge devices (tested on NVIDIA Jetson Orin NX).

## Overview

Orpheus uses a **centralized shared library architecture**:

```shell
/opt/orpheus/
├── platform/
│   └── orpheus-common/          # Shared library (install FIRST)
├── config/
│   └── orpheus.yaml             # Central configuration
├── services/
│   ├── orpheus-dashboard/       # Web dashboard
│   └── orpheus-mqtt/            # MQTT broker
└── agents/
    ├── orpheus-agent-audio-motion/     # Audio motion detection
    ├── orpheus-agent-video-snapshotter/ # Periodic camera snapshots
    └── orpheus-agent-video-timelapser/  # Timelapse video generation
```

Each service/agent has its own Python virtual environment but shares:

- **orpheus-common library** (installed once at `/opt/orpheus/platform/orpheus-common`)
- **Configuration** (single `orpheus.yaml` at `/opt/orpheus/config/orpheus.yaml`)

## Prerequisites

- Ubuntu 20.04+ or Jetson Linux (L4T)
- Python 3.9+ (Python 3.9.5 for Jetson compatibility)
- systemd
- sudo access

## Quick Start (Jetson)

```bash
# Clone the repository
cd ~
mkdir -p runtime/orpheus
cd runtime/orpheus
git clone https://github.com/scottchronicity/orpheus.git .

# Install in order:
# 1. Platform library (REQUIRED FIRST)
cd platform/orpheus-common
sudo ./systemd/install.sh

# 2. Edit configuration for your deployment
sudo nano /opt/orpheus/config/orpheus.yaml

# 3. MQTT Broker
cd ../../services/orpheus-mqtt
sudo make install-service
sudo systemctl start orpheus-mqtt

# 4. Dashboard
cd ../orpheus-dashboard
sudo make install-service
sudo systemctl start orpheus-dashboard

# 5. Audio Motion Detector Agent
cd ../../agents/orpheus-agent-audio-motion
sudo make install-service
sudo systemctl start orpheus-agent-audio-motion

# 6. Video Agents (optional, for camera timelapse generation)
cd ../orpheus-agent-video-snapshotter
sudo make install-service
sudo systemctl start orpheus-agent-video-snapshotter

cd ../orpheus-agent-video-timelapser
sudo make install-service
sudo systemctl start orpheus-agent-video-timelapser
```

## Step-by-Step Installation

### 1. Install orpheus-common Platform Library

This **must be installed first** as all services depend on it.

```bash
cd ~/runtime/orpheus/platform/orpheus-common
sudo ./systemd/install.sh
```

This will:

- Install the shared library to `/opt/orpheus/platform/orpheus-common`
- Deploy default config to `/opt/orpheus/config/orpheus.yaml`
- Create example configs for reference

### 2. Configure Your Deployment

Edit the central configuration file:

```bash
sudo nano /opt/orpheus/config/orpheus.yaml
```

Key settings to update:

- MQTT broker host/port
- Camera hostnames and credentials
- Storage paths
- Audio channel configuration
- Service list for dashboard monitoring

### 3. Install Services

Each service installer will:

- Create isolated Python venv
- Install orpheus-common from central location
- Deploy service-specific files
- Install and enable systemd unit

```bash
# MQTT Broker
cd ~/runtime/orpheus/services/orpheus-mqtt
sudo make install-service
sudo systemctl start orpheus-mqtt

# Dashboard
cd ~/runtime/orpheus/services/orpheus-dashboard  
sudo make install-service
sudo systemctl start orpheus-dashboard
```

### 4. Install Agents

```bash
# Audio Motion Detector
cd ~/runtime/orpheus/agents/orpheus-agent-audio-motion
sudo make install-service
sudo systemctl start orpheus-agent-audio-motion

# Video Snapshotter (captures periodic camera images)
cd ~/runtime/orpheus/agents/orpheus-agent-video-snapshotter
sudo make install-service
sudo systemctl start orpheus-agent-video-snapshotter

# Video Timelapser (generates timelapse videos from snapshots)
cd ~/runtime/orpheus/agents/orpheus-agent-video-timelapser
sudo make install-service
sudo systemctl start orpheus-agent-video-timelapser
```

## Updating After Changes

When you make code or configuration changes:

### Update Platform Library

```bash
cd ~/runtime/orpheus/platform/orpheus-common
git pull
sudo ./systemd/install.sh
```

### Update Configuration

```bash
cd ~/runtime/orpheus/platform/orpheus-common
git pull
sudo make update  # Deploys config and restarts services
```

### Update Individual Services

```bash
cd ~/runtime/orpheus/services/orpheus-dashboard
git pull
sudo make update  # Redeploys and restarts service
```

### Update Agents

```bash
cd ~/runtime/orpheus/agents/orpheus-agent-audio-motion
git pull
sudo make install-service  # Redeploys and restarts
sudo systemctl restart orpheus-agent-audio-motion
```

## Verification

Check all services are running:

```bash
systemctl status orpheus-mqtt
systemctl status orpheus-dashboard
systemctl status orpheus-agent-audio-motion
systemctl status orpheus-agent-video-snapshotter
systemctl status orpheus-agent-video-timelapser
```

Access the dashboard:

```shell
http://<jetson-ip>:8080
```

View logs:

```bash
sudo journalctl -u orpheus-mqtt -f
sudo journalctl -u orpheus-dashboard -f
sudo journalctl -u orpheus-agent-audio-motion -f
```

## Uninstallation

```bash
# Stop and disable services
sudo systemctl stop orpheus-agent-audio-motion
sudo systemctl disable orpheus-agent-audio-motion
sudo systemctl stop orpheus-dashboard
sudo systemctl disable orpheus-dashboard
sudo systemctl stop orpheus-mqtt
sudo systemctl disable orpheus-mqtt

# Remove service files
sudo rm /etc/systemd/system/orpheus-*.service
sudo systemctl daemon-reload

# Remove installation
sudo rm -rf /opt/orpheus

# Remove configuration (if desired)
sudo rm -rf /opt/orpheus/config
```

## Development vs Production

**Development** (on laptop/desktop):

- Use `make install` to create local venv
- Uses `-e ../../platform/orpheus-common` editable install
- Config in repo at `config/orpheus.yaml` (repo root)
- Run with `make run`

**Production** (on Jetson):

- Use `sudo make install-service` for systemd deployment
- Installs orpheus-common from `/opt/orpheus/platform/orpheus-common`
- Config at `/opt/orpheus/config/orpheus.yaml`
- Runs as systemd service under `orpheus` user

## Troubleshooting

### Service won't start

```bash
# Check status and recent logs
sudo systemctl status orpheus-agent-audio-motion
sudo journalctl -u orpheus-agent-audio-motion -n 50 --no-pager
```

### orpheus-common not found

Ensure you installed it first:

```bash
sudo /opt/orpheus/platform/orpheus-common/systemd/install.sh
```

### Config file not found

The system looks for config in this order:

1. `/opt/orpheus/config/orpheus.yaml` (production)
2. `./config/orpheus.yaml` (development)
3. `~/.config/orpheus/orpheus.yaml` (user config)

Ensure `/opt/orpheus/config/orpheus.yaml` exists.

### Permission errors

Services run as the `orpheus` user. Check permissions:

```bash
ls -la /opt/orpheus/
ls -la /mnt/data/  # or your storage path
```

## Architecture Notes

**Why centralized orpheus-common?**

- Single source of truth for shared code
- Easier updates (update once, restart services)
- Smaller deployment footprint
- Consistent behavior across all components

**Why single orpheus.yaml?**

- Simplified configuration management
- No config drift between services
- Easy backup/restore
- GitOps friendly

**Why separate venvs?**

- Isolation: Agent crashes don't affect dashboard
- Different Python versions possible
- Service-specific dependencies separated
- Security: principle of least privilege
