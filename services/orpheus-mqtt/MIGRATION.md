# MQTT Service Directory Structure Migration

## ⚠️ Important Notice

If you installed the MQTT broker before **November 7, 2025**, the directory structure has changed to support proper multi-service coexistence.

## What Changed?

### Old Structure (Incorrect)
```
/etc/orpheus/mosquitto.conf          ← Service owned root directory
```

### New Structure (Correct)
```
/etc/orpheus/                        ← Shared by ALL services
└── mqtt/                            ← MQTT-specific subdirectory
    └── mosquitto.conf
```

## Why the Change?

The old structure had the MQTT service owning `/etc/orpheus/` directly, which would conflict when adding other services (audio, video, etc.). The new structure uses:

- `/etc/orpheus/` - Shared root for ALL Orpheus services
- `/etc/orpheus/mqtt/` - MQTT-specific configuration
- `/etc/orpheus/audio/` - Future audio agent configuration  
- `/etc/orpheus/video/` - Future video agent configuration

This ensures all services can coexist safely without conflicts.

## Do You Need to Migrate?

Check if you have the old structure:

```bash
ls -la /etc/orpheus/
```

**If you see:**
- `mosquitto.conf` directly in `/etc/orpheus/` → You need to migrate
- `mqtt/mosquitto.conf` → Already using new structure, no action needed

## Migration Steps

### Option 1: Fresh Install (Recommended)

If you haven't customized your configuration:

```bash
# 1. Stop the service
sudo systemctl stop orpheus-mqtt.service

# 2. Remove old installation
cd services/orpheus-mqtt
sudo make clean

# 3. Pull latest code
git pull origin setup

# 4. Reinstall with new structure
sudo make install

# 5. Verify it's working
make test
```

### Option 2: Manual Migration

If you have customized configuration you want to preserve:

```bash
# 1. Stop the service
sudo systemctl stop orpheus-mqtt.service

# 2. Create new directory structure
sudo mkdir -p /etc/orpheus/mqtt

# 3. Move existing config
sudo mv /etc/orpheus/mosquitto.conf /etc/orpheus/mqtt/

# 4. Update systemd service file
sudo cp services/orpheus-mqtt/systemd/orpheus-mqtt.service /etc/systemd/system/
sudo systemctl daemon-reload

# 5. Start service
sudo systemctl start orpheus-mqtt.service

# 6. Verify it's working
cd services/orpheus-mqtt
make test
make status
```

## Verify Migration Success

After migrating, verify the new structure:

```bash
# Check directory structure
tree /etc/orpheus/
# Should show:
# /etc/orpheus/
# └── mqtt/
#     └── mosquitto.conf

# Check service is using correct config
sudo systemctl cat orpheus-mqtt.service | grep ExecStart
# Should show: /usr/sbin/mosquitto -c /etc/orpheus/mqtt/mosquitto.conf

# Test connection
cd services/orpheus-mqtt
make test
```

## Troubleshooting

### Service won't start after migration

**Check config path:**
```bash
sudo systemctl cat orpheus-mqtt.service | grep ExecStart
```

Should be: `/usr/sbin/mosquitto -c /etc/orpheus/mqtt/mosquitto.conf`

If incorrect, update the service file:
```bash
sudo cp services/orpheus-mqtt/systemd/orpheus-mqtt.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start orpheus-mqtt.service
```

### Config file not found

**Verify file exists:**
```bash
ls -la /etc/orpheus/mqtt/mosquitto.conf
```

If missing, copy from template:
```bash
sudo mkdir -p /etc/orpheus/mqtt
sudo cp services/orpheus-mqtt/config/mosquitto.conf /etc/orpheus/mqtt/
```

### Permission errors

**Check ownership:**
```bash
ls -la /var/lib/orpheus/mqtt/
```

Should be owned by `mosquitto:mosquitto`. If not:
```bash
sudo chown -R mosquitto:mosquitto /var/lib/orpheus/mqtt/
```

## Clean Up Old Files

After successful migration, you can remove any orphaned files:

```bash
# Only if /etc/orpheus/mosquitto.conf still exists after migration
sudo rm -f /etc/orpheus/mosquitto.conf

# The directory structure should now be:
tree /etc/orpheus/
# /etc/orpheus/
# └── mqtt/
#     └── mosquitto.conf
```

## Questions?

If you encounter issues:

1. Check service logs: `sudo journalctl -u orpheus-mqtt.service -n 50`
2. Validate config: `sudo mosquitto -c /etc/orpheus/mqtt/mosquitto.conf -t`
3. See full documentation: `services/orpheus-mqtt/README.md`
4. Review system directory structure: `services/SYSTEM_DIRECTORIES.md`

---

**Last Updated**: November 7, 2025  
**Applies to**: MQTT broker service migration from v0.x to v1.0
