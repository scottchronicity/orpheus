# Orpheus System-Wide Directory Structure

This document defines the standard directory hierarchy for all Orpheus services. **All services must follow this structure** to ensure proper coexistence and prevent conflicts.

## Directory Hierarchy

### Configuration: `/etc/orpheus/`

Root configuration directory for all Orpheus services. **This directory is shared infrastructure and must never be deleted by any individual service.**

```
/etc/orpheus/                      # Root config directory (shared, never delete)
├── mqtt/                          # MQTT broker configuration
│   └── mosquitto.conf
├── audio/                         # Audio agent configuration (future)
│   ├── capture.conf
│   └── detection.conf
├── video/                         # Video agent configuration (future)
│   ├── cameras.conf
│   └── detection.conf
├── system.conf                    # System-wide settings (future)
└── README.md                      # Documentation about this directory
```

**Permissions:**
- Owner: `root:root`
- Mode: `755` (drwxr-xr-x)
- Service-specific subdirectories owned by appropriate user

**Rules:**
1. Each service creates its own subdirectory (e.g., `/etc/orpheus/mqtt/`)
2. Services may create multiple files within their subdirectory
3. Services **must not** delete `/etc/orpheus/` itself
4. Services **must not** modify other services' subdirectories
5. The root directory should be created by the first service installed

### Data/Persistence: `/var/lib/orpheus/`

Root data directory for persistent application data, caches, and state. **Shared infrastructure - never delete.**

```
/var/lib/orpheus/                  # Root data directory (shared, never delete)
├── mqtt/                          # MQTT message persistence (mosquitto fallback)
│   ├── mosquitto.db
│   └── mosquitto.db.new           # mosquitto's autosave temp file
├── audio/                         # Audio recordings and cache (future)
│   ├── recordings/
│   ├── chunks/
│   └── cache/
├── video/                         # Video frames and cache (future)
│   ├── frames/
│   ├── clips/
│   └── cache/
└── models/                        # Shared ML models (future)
    ├── audio/
    └── video/
```

**Permissions:**
- Owner: varies by service (e.g., `mosquitto:mosquitto` for `mqtt/`)
- Mode: `755` for directories, `644` for files (or as needed by service)

**Rules:**
1. Each service creates and owns its subdirectory
2. Services set appropriate ownership for their subdirectory
3. Services **must not** delete `/var/lib/orpheus/` itself
4. Services **must not** access other services' data without proper permissions
5. Shared subdirectories (like `models/`) require documented ownership

### Logs: `/var/log/orpheus/` (Optional)

Root log directory if not using systemd journal. **Most services should use systemd journal instead.**

```
/var/log/orpheus/                  # Root log directory (optional)
├── mqtt/                          # MQTT broker logs (if file-based)
│   └── mosquitto.log
├── audio/                         # Audio agent logs
│   └── agent.log
└── video/                         # Video agent logs
    └── agent.log
```

**Note:** Current Orpheus services use systemd journal (`journalctl`) instead of file-based logging. This directory structure is provided for reference if file-based logging is needed in the future.

**Permissions:**
- Owner: varies by service
- Mode: `755` for directories, `644` for log files
- Rotate logs with `logrotate` if using file-based logging

## Service-Specific Responsibilities

### During Installation

Each service installer **must**:

1. ✅ Check if shared root directories exist before creating them
2. ✅ Create root directories with proper permissions if they don't exist
3. ✅ Create service-specific subdirectories
4. ✅ Set appropriate ownership for service-specific subdirectories
5. ✅ Never assume ownership of shared root directories

**Example (install.sh):**
```bash
# Shared root directory (create if needed, don't fail if exists)
ORPHEUS_ROOT_CONFIG="/etc/orpheus"
if [ ! -d "$ORPHEUS_ROOT_CONFIG" ]; then
    mkdir -p "$ORPHEUS_ROOT_CONFIG"
    log_success "Created shared root: $ORPHEUS_ROOT_CONFIG"
else
    log_info "Shared root exists: $ORPHEUS_ROOT_CONFIG"
fi

# Service-specific subdirectory
SERVICE_CONFIG="${ORPHEUS_ROOT_CONFIG}/myservice"
mkdir -p "$SERVICE_CONFIG"
log_success "Created service config: $SERVICE_CONFIG"
```

### During Uninstallation/Clean

Each service **must**:

1. ✅ Only remove its own service-specific subdirectories
2. ✅ **Never** delete shared root directories (`/etc/orpheus/`, `/var/lib/orpheus/`)
3. ✅ Warn users about what is being kept
4. ✅ Provide instructions for complete removal

**Example (Makefile clean target):**
```makefile
clean:
	# Remove only service-specific subdirectory
	rm -rf /etc/orpheus/myservice/
	
	# DO NOT remove /etc/orpheus/ itself
	# DO NOT remove /var/lib/orpheus/ itself
	
	@echo "Shared directories preserved:"
	@echo "  /etc/orpheus/"
	@echo "  /var/lib/orpheus/"
```

### Systemd Service Files

When referencing configuration in systemd service files:

```ini
[Service]
# Use full path to service-specific config
ExecStart=/usr/bin/myservice -c /etc/orpheus/myservice/config.conf

# Grant write access to service-specific data directory
ReadWritePaths=/var/lib/orpheus/myservice/
```

## Directory Ownership Matrix

| Directory | Owner | Group | Mode | Notes |
| ----------- | ------- | ------- | ------ | ------- |
| `/etc/orpheus/` | root | root | 755 | Shared, never delete |
| `/etc/orpheus/mqtt/` | root | root | 755 | MQTT-specific |
| `/etc/orpheus/audio/` | root | root | 755 | Audio-specific (future) |
| `/etc/orpheus/video/` | root | root | 755 | Video-specific (future) |
| `/var/lib/orpheus/` | root | root | 755 | Shared, never delete |
| `/var/lib/orpheus/mqtt/` | mosquitto | mosquitto | 755 | MQTT persistence |
| `/var/lib/orpheus/audio/` | orpheus-audio | orpheus-audio | 755 | Audio data (future) |
| `/var/lib/orpheus/video/` | orpheus-video | orpheus-video | 755 | Video data (future) |

## Complete Removal

To completely remove Orpheus from a system (after uninstalling all services):

```bash
# Stop all Orpheus services first
sudo systemctl stop orpheus-*.service

# Remove systemd service files
sudo rm -f /etc/systemd/system/orpheus-*.service
sudo systemctl daemon-reload

# Remove configurations
sudo rm -rf /etc/orpheus

# Remove data
sudo rm -rf /var/lib/orpheus

# Remove logs (if using file-based logging)
sudo rm -rf /var/log/orpheus

# Clean systemd journal entries (optional)
sudo journalctl --rotate
sudo journalctl --vacuum-time=1s
```

## Migration from Old Structure

If you have an existing service using `/etc/orpheus/` directly (old structure):

**Old (incorrect):**
```
/etc/orpheus/mosquitto.conf
```

**New (correct):**
```
/etc/orpheus/mqtt/mosquitto.conf
```

**Migration steps** (mosquitto-fallback unit; the service was renamed
`orpheus-mqtt` → `orpheus-backplane`, so the mqtt unit is now
`orpheus-backplane-mosquitto.service`):
```bash
# Stop service
sudo systemctl stop orpheus-backplane-mosquitto.service

# Create subdirectory
sudo mkdir -p /etc/orpheus/mqtt

# Move config
sudo mv /etc/orpheus/mosquitto.conf /etc/orpheus/mqtt/

# Update systemd service file to point to new location
sudo nano /etc/systemd/system/orpheus-backplane-mosquitto.service

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl start orpheus-backplane-mosquitto.service
```

## Best Practices

### ✅ DO

- Create shared root directories if they don't exist
- Use service-specific subdirectories for all files
- Check for existence before creating shared directories
- Document ownership and permissions
- Preserve shared directories during uninstallation
- Use descriptive subdirectory names matching the service

### ❌ DON'T

- Delete `/etc/orpheus/` or `/var/lib/orpheus/` in clean/uninstall targets
- Store service files directly in `/etc/orpheus/` (use subdirectory)
- Assume exclusive ownership of shared directories
- Hard-code absolute paths without subdirectories
- Modify other services' subdirectories
- Use generic names that might conflict

## Checklist for New Services

When creating a new Orpheus service, verify:

- [ ] Uses `/etc/orpheus/<service-name>/` for configuration
- [ ] Uses `/var/lib/orpheus/<service-name>/` for data
- [ ] Creates parent directories if they don't exist (with checks)
- [ ] Never deletes parent directories in any script
- [ ] Systemd service file references correct config path
- [ ] Installation script creates subdirectories with proper ownership
- [ ] Clean/uninstall targets only remove service-specific subdirectories
- [ ] Documentation clearly states what is and isn't removed
- [ ] Follows naming conventions (lowercase, hyphenated)

## Questions?

If you're unsure about directory structure for a new service:

1. Check existing services (e.g., `services/orpheus-backplane/`) as examples
2. Review this document
3. Follow the pattern: `/etc/orpheus/<service>/` and `/var/lib/orpheus/<service>/`
4. When in doubt, create a subdirectory rather than using the root

## Version History

- **v1.0** (2025-11-07): Initial version, established shared directory structure
- Future updates will be documented here

---

**Important**: This structure is critical for system stability. All services must comply to prevent conflicts and data loss.
