# Orpheus GPS Service

GPS service for the Orpheus wildlife monitoring system that provides spatiotemporal context by reading NMEA sentences from a USB GPS dongle and publishing location data to MQTT.

## Overview

The GPS service:

- Reads NMEA sentences directly from a serial GPS device (VK-162 USB GPS dongle)
- Parses `$GPRMC` and `$GPGGA` sentences for location, elevation, and fix quality
- Publishes location state to MQTT topic `orpheus/state/location` (retained message)
- Implements rate limiting (5m distance change or 1-minute heartbeat)
- Provides fallback to static coordinates when GPS is unavailable
- Logs warnings about time drift between GPS and system clock

> **Note**: This service does not modify system time. Time synchronization is an OS-level responsibility (e.g., via `chrony` or `ntpd`).

## Features

- **Direct Serial Reading**: Uses `pyserial` to read from GPS device (no gpsd dependency)
- **NMEA Parsing**: Parses standard GPS sentences using `pynmea2`
- **Smart Rate Limiting**: Only publishes when location changes significantly or on heartbeat
- **Fallback Support**: Uses static coordinates when GPS device is unavailable
- **3D Position**: Publishes latitude, longitude, and elevation
- **Fix Quality**: Reports fix type (3d, 2d, none, static)
- **Time Drift Detection**: Logs warnings if GPS time differs significantly from system time

## Installation

### Development Setup

```bash
# Install dependencies
make install

# Run tests
make test

# Run with coverage
make coverage

# Run linter
make lint

# Format code
make format
```

### Production Deployment

```bash
# Install as systemd service (requires sudo)
make install-service

# Start the service
sudo systemctl start orpheus-gps

# Check status
sudo systemctl status orpheus-gps

# View logs
sudo journalctl -u orpheus-gps -f
```

## Configuration

Configuration is managed through environment variables:

### GPS Device

```bash
# Serial device path (default: /dev/ttyACM0)
ORPHEUS_GPS_DEVICE=/dev/ttyACM0
```

### Static Fallback Coordinates

When the GPS device is unavailable or has no fix, the service can fall back to static coordinates:

```bash
# Static latitude (decimal degrees)
ORPHEUS_STATIC_LAT=47.6062

# Static longitude (decimal degrees)
ORPHEUS_STATIC_LON=-122.3321

# Static elevation in meters (optional, default: 0)
ORPHEUS_STATIC_ELEVATION=50.0
```

### MQTT Configuration

MQTT settings are read from the centralized Orpheus configuration (`/opt/orpheus/config/orpheus.yaml` in production, or `config/orpheus.yaml` in development).

## MQTT Topics

### Published Topics

- `orpheus/state/location` (retained): Current GPS location

#### Message Format

```json
{
  "lat": 47.6062,
  "lon": -122.3321,
  "elevation": 50.0,
  "timestamp": "2024-01-15T12:34:56.789000+00:00",
  "fix": "3d"
}
```

**Fix Types:**

- `3d`: GPS fix with 4+ satellites (includes elevation)
- `2d`: GPS fix with <4 satellites (no elevation)
- `none`: No GPS fix available
- `static`: Using fallback static coordinates

## Architecture

### Rate Limiting

The service implements smart rate limiting to avoid excessive MQTT traffic:

1. **Distance Threshold**: Publishes when location changes by more than 5 meters
2. **Heartbeat**: Publishes every 60 seconds regardless of distance change
3. **First Location**: Always publishes the first valid location

### NMEA Sentence Processing

The service processes two types of NMEA sentences:

- **$GPRMC** (Recommended Minimum): Provides position, date, and time
- **$GPGGA** (Global Positioning System Fix Data): Provides position, elevation, and fix quality

### Serial Connection Handling

- Opens serial port at 9600 baud (standard for VK-162)
- Automatically retries connection if device is unavailable
- Falls back to static coordinates when serial connection fails
- Gracefully handles device disconnection and reconnection

## Hardware

This service is designed for the **VK-162 USB GPS dongle**, which:

- Connects via USB and appears as `/dev/ttyACM0`
- Uses standard NMEA 0183 protocol
- Operates at 9600 baud
- Provides ~1 Hz update rate

### Permissions

The service user (`orpheus`) must be in the `dialout` group to access the serial port:

```bash
sudo usermod -a -G dialout orpheus
```

This is automatically configured by the installation script.

## Development

### Running Locally

```bash
# Run with default settings
make run

# Run with custom GPS device
ORPHEUS_GPS_DEVICE=/dev/ttyUSB0 make run

# Run with static coordinates as fallback
ORPHEUS_STATIC_LAT=47.6062 ORPHEUS_STATIC_LON=-122.3321 make run
```

### Testing

The test suite includes comprehensive tests for:

- NMEA sentence parsing
- Rate limiting logic
- Distance calculations (Haversine formula)
- MQTT publishing
- Fallback behavior
- Time drift detection

```bash
# Run all tests
make test

# Run with coverage report
make coverage
```

### Code Quality

```bash
# Check code with ruff
make lint

# Auto-fix issues and format
make format

# Check formatting only
make check
```

## Manual Verification

As specified in the issue, you can verify the service behavior:

1. **Normal Operation**: Deploy and check MQTT `orpheus/state/location` for live coordinates
2. **No Fix Handling**: Cover the GPS or unplug it → Ensure `fix: "static"` or `fix: "none"` is published
3. **Live Fix**: Expose GPS to the sky → Ensure live coordinates are published with `fix: "3d"` or `fix: "2d"`

Example using the `nats` CLI:

```bash
# Subscribe to location updates
nats sub 'orpheus.state.location'
```

## Dependencies

- Python 3.9.5+ (locked for Jetson compatibility)
- `orpheus-common`: Shared Orpheus platform library
- `paho-mqtt>=2.1.0`: MQTT client
- `pyserial>=3.5`: Serial port communication
- `pynmea2>=1.18.0`: NMEA sentence parsing
- `PyYAML>=6.0`: Configuration file parsing

## Service Management

```bash
# Start service
sudo systemctl start orpheus-gps

# Stop service
sudo systemctl stop orpheus-gps

# Restart service
sudo systemctl restart orpheus-gps

# Check status
sudo systemctl status orpheus-gps

# View logs
sudo journalctl -u orpheus-gps -f

# Enable auto-start on boot
sudo systemctl enable orpheus-gps

# Disable auto-start
sudo systemctl disable orpheus-gps
```

## Troubleshooting

### GPS Device Not Found

If you see "GPS device not available" errors:

1. Check that the device exists: `ls -l /dev/ttyACM0`
2. Verify permissions: `groups orpheus` should include `dialout`
3. Check if another process is using the device: `lsof /dev/ttyACM0`
4. Try unplugging and replugging the GPS dongle

### No GPS Fix

If the service publishes `fix: "none"`:

1. Ensure the GPS has a clear view of the sky
2. Wait 1-2 minutes for initial satellite acquisition (cold start)
3. Check GPS LED indicator (should blink when acquiring satellites)
4. Verify NMEA sentences are being received: `cat /dev/ttyACM0`

### Time Drift Warnings

If you see time drift warnings in the logs:

1. The GPS service only logs warnings - it does not modify system time
2. System time synchronization is managed at the OS level
3. Configure time sync using `chrony`, `ntpd`, or `systemd-timesyncd`
4. For GPS-based time sync, configure chrony to use GPS as a time source
5. Check system time sync status: `timedatectl status`

## License

MIT License - See LICENSE file in repository root.
