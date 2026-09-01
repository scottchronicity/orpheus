# Services

Core infrastructure services for the Orpheus platform.

## Overview

System-wide services that provide:
- Message brokering (MQTT)
- Diagnostic monitoring and health checks
- API endpoints
- Data storage and retrieval (coming soon)

## Structure

- `orpheus-backplane/` - Messaging backplane (NATS + JetStream default, mosquitto fallback)
- `orpheus_ui/` - React + FastAPI web UI (system health, detections, entities, equivalences)
- `orpheus-gps/` - GPS time + location service
- `orpheus-bluetooth-autoconnect/` - Audio-out Bluetooth routing

## Services

### Messaging Backplane
Central message broker for agent coordination and event distribution.

- **Purpose**: Inter-service communication via pub/sub messaging
- **Default**: NATS + JetStream on port 4222 (`event_bus.backend: nats`)
- **Fallback**: mosquitto/MQTT 3.1.1 on port 1883 (`event_bus.backend: mqtt`)
- **Usage**: Agents publish detections, status updates, and requests

See `orpheus-backplane/README.md` for setup and configuration.

### Orpheus UI
The user-facing web interface for system monitoring, detection
browsing, equivalence management, and configuration.

- **Default Port**: 8080 (nginx proxies to 8082)
- **Tech Stack**: React + TypeScript + Tailwind frontend; FastAPI +
  fastapi-users backend; JWT auth.
- **Features**: System health grid, entity browsing, bird/crow
  history, cross-classifier equivalences, audio-event correlation,
  per-agent error feed.

See `orpheus_ui/README.md` for setup and `docs/ORPHEUS_UI.md` for
the full design.

## Service Management

Each service follows the same Makefile pattern for consistency:

### Development
```bash
cd <service-name>/
make install    # Set up virtual environment
make run        # Run in development mode
make test       # Run tests
make clean      # Clean build artifacts
```

### Production
```bash
cd <service-name>/
make install-service        # Install to /opt/orpheus/<service-name>
sudo systemctl enable orpheus-<service-name>
make service-start          # Start service
make service-status         # Check status
make service-logs           # View logs
make update                 # Deploy code changes
```

## Top-Level Service Management

From the repository root:

```bash
make services-install   # Install all services
make services-start     # Start all services
make services-stop      # Stop all services
make services-restart   # Restart all services
```

## Adding New Services

When creating a new service:

1. Create directory under `services/`
2. Follow the established Makefile pattern (see existing services)
3. Use isolated virtual environments (no shared dependencies)
4. Include systemd service file in `systemd/` subdirectory
5. Publish status updates via MQTT
6. Add health check endpoint if applicable
7. Update this README
8. Update root Makefile to include new service

## Service Communication

Services communicate via MQTT topics:

- `orpheus/status/<service-name>` - Service health heartbeats
- `orpheus/events/<agent-name>` - Detection events
- `orpheus/commands/<agent-name>` - Control commands

See individual service documentation for specific topic schemas.

## Monitoring

Orpheus UI provides a unified view of all service health. Access at:
- Development: `http://localhost:5173` (Vite dev) or `http://localhost:8082` (backend)
- Production: `http://jetson1.local:8080`

See `orpheus_ui/README.md` for production nginx configuration.