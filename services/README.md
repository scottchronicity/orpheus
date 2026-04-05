# Services

Core infrastructure services for the Orpheus platform.

## Overview

System-wide services that provide:
- Message brokering (MQTT)
- Diagnostic monitoring and health checks
- API endpoints
- Data storage and retrieval (coming soon)

## Structure

- `orpheus-mqtt/` - MQTT broker for inter-service messaging
- `orpheus-dashboard/` - Web-based diagnostic dashboard

## Services

### MQTT Broker
Central message broker for agent coordination and event distribution.

- **Purpose**: Inter-service communication via pub/sub messaging
- **Default Port**: 1883
- **Protocol**: MQTT 3.1.1
- **Usage**: Agents publish detections, status updates, and requests

See `orpheus-mqtt/README.md` for setup and configuration.

### Orpheus Dashboard
Diagnostic web interface for system monitoring and status.

- **Purpose**: Real-time system health and service status monitoring
- **Default Port**: 8080
- **Tech Stack**: FastAPI backend, vanilla JavaScript frontend
- **Features**: 
  - System health (CPU, memory, disk, uptime)
  - Service status tracking
  - Hardware validation (coming soon)
  - Detection statistics (coming soon)

See `orpheus-dashboard/README.md` for development and deployment.

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
sudo make install-service   # Install to /opt/orpheus/<service-name>
sudo systemctl enable orpheus-<service-name>
sudo make service-start     # Start service
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

The dashboard service provides a unified view of all service health. Access at:
- Development: `http://localhost:8080`
- Production: `http://jetson1.local:8080`

For production deployment on port 80, see `orpheus-dashboard/README.md` for nginx configuration.