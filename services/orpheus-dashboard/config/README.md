# Camera Configuration Guide

This guide explains how to configure the camera system for the Orpheus Dashboard.

## Overview

The Orpheus Dashboard supports multiple IP cameras (currently Amcrest) via a flexible configuration system. Cameras are defined using environment variables, which allows for easy deployment and secret management.

## Configuration Locations

### Development
For local development, copy `config/env.example` to `.env` in the project root. The application will automatically load variables from this file.

```bash
cp config/env.example .env
```

### Production
In production (on the Jetson), the configuration is stored at `/etc/orpheus/dashboard/config/.env`. This file is created during installation and is secured with restricted permissions (readable only by root).

## Adding Cameras

The system supports up to 10 cameras (CAMERA_1_* through CAMERA_10_*). To add a camera, define the following variables:

- `CAMERA_X_TYPE`: The camera driver type (currently only `amcrest` is supported)
- `CAMERA_X_NAME`: A unique identifier for the camera (e.g., `orpheus-eye-1`)
- `CAMERA_X_HOST`: The IP address or hostname of the camera
- `CAMERA_X_MODEL`: The camera model (for documentation purposes)

### Example

```ini
# Camera 1
CAMERA_1_TYPE=amcrest
CAMERA_1_NAME=front-gate
CAMERA_1_HOST=192.168.1.101
CAMERA_1_MODEL=IP5M-B1186EW-AI-V3
```

## Credentials

All cameras currently share a single set of credentials. This is a simplification for the current deployment environment.

```ini
CAMERA_USER=admin
CAMERA_PASS=secure_password
```

## Supported Cameras

### Amcrest
- **Driver**: `src/hardware/cameras/amcrest.py`
- **Features**: Snapshot retrieval, health checks
- **Requirements**: HTTP API access enabled on the camera

## Troubleshooting

### Camera not showing up
1. Check that the configuration variables are numbered sequentially (e.g., don't skip from CAMERA_1 to CAMERA_3).
2. Verify the `CAMERA_X_TYPE` matches a supported driver.
3. Check application logs for "Failed to initialize camera" messages.

### Connection Refused
1. Verify the camera IP/Hostname is reachable from the dashboard server.
2. Check that the camera credentials are correct.
3. Ensure the camera's HTTP API is enabled.

## Security

- **Permissions**: The production config file `/etc/orpheus/dashboard/cameras.env` should be owned by root and have 600 permissions.
- **Passwords**: Avoid committing real passwords to version control. Use the example file for templates.
