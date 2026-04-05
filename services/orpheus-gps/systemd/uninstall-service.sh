#!/bin/bash
set -e

echo "Uninstalling Orpheus GPS Service systemd service..."

# Stop and disable service
systemctl stop orpheus-gps || true
systemctl disable orpheus-gps || true

# Remove systemd service file
rm -f /etc/systemd/system/orpheus-gps.service
systemctl daemon-reload

# Remove installation directory
rm -rf /opt/orpheus/services/orpheus-gps

echo "✓ Service uninstalled"
