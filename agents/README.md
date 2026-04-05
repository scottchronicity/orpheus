# Agents

Autonomous agents for wildlife monitoring and analysis.

## Overview

This directory contains AI agents that run independently to:
- Detect and classify wildlife sounds (audio-motion)
- Monitor video streams for motion (video-motion)
- Analyze environmental conditions
- Analyze behavioral patterns
- Trigger alerts and recordings

## Available Agents

### orpheus-agent-audio-motion
Multi-channel audio motion detection agent for the Behringer UMC404HD audio interface.

**Features:**
- 4-channel simultaneous audio monitoring
- Adaptive threshold motion detection
- FLAC audio clip storage
- MQTT event publishing
- Systemd service integration

**Quick Start:**
```bash
cd orpheus-agent-audio-motion
make install
make run
```

### orpheus-agent-video-motion
Multi-camera video motion detection agent for Amcrest IP cameras.

**Features:**
- 4-camera simultaneous monitoring via RTSP
- OpenCV background subtraction motion detection
- MP4 video clip storage
- MQTT event publishing
- Systemd service integration

**Quick Start:**
```bash
cd orpheus-agent-video-motion
make install
make run
```

## Creating New Agents

Each agent should be self-contained with its own dependencies, configuration, and documentation.

**Required Structure:**
```
orpheus-agent-{name}/
├── src/orpheus_agent_{name}/
│   ├── __init__.py
│   ├── main.py              # Entrypoint
│   ├── config.py            # Configuration loader
│   └── ...                  # Additional modules
├── tests/                   # Pytest tests (70%+ coverage)
├── systemd/                 # Systemd service files
├── Makefile                 # Build and deployment
├── requirements.txt         # Dependencies
├── pyproject.toml          # Ruff configuration
└── README.md               # Documentation
```

**Integration Checklist:**
- [ ] Add agent to root `Makefile`
- [ ] Add service to `orpheus.yaml` dashboard.services
- [ ] Add MQTT topics to `orpheus.yaml` mqtt.topics
- [ ] Add agent tests to CI pipeline
- [ ] Document in main README.md

