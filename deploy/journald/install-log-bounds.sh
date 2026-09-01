#!/usr/bin/env bash
# Install Orpheus's host-log bounds. Opt-in: nothing calls this automatically.
set -euo pipefail

DROPIN_DIR=/etc/systemd/journald.conf.d
DROPIN="${DROPIN_DIR}/10-orpheus.conf"
SRC="$(cd "$(dirname "$0")" && pwd)/10-orpheus.conf"

[ "$(id -u)" -eq 0 ] || { echo "ERROR: run with sudo — this writes ${DROPIN}" >&2; exit 1; }

echo "Installing ${DROPIN}"
install -d -m 0755 "$DROPIN_DIR"
install -m 0644 "$SRC" "$DROPIN"

# Persistence needs the directory to exist; Storage=persistent creates it, but
# doing it here makes the change effective without waiting on journald's own
# handling and is harmless if it already exists.
install -d -m 2755 -g systemd-journal /var/log/journal 2>/dev/null || install -d -m 2755 /var/log/journal

echo "Restarting systemd-journald"
systemctl restart systemd-journald

# The restart alone leaves the runtime journal in /run: the move to disk
# happens on flush. Without this the report below shows the old location and
# reads as a failed install even though the change took.
systemctl start systemd-journal-flush.service 2>/dev/null || journalctl --flush 2>/dev/null || true

echo
echo "Effective journal configuration:"
journalctl --header 2>/dev/null | grep -iE 'file path|storage' | head -3 || true
journalctl --disk-usage 2>/dev/null || true
echo
echo "Done. To undo: sudo rm ${DROPIN} && sudo systemctl restart systemd-journald"
echo "Note: the journal no longer mirrors into /var/log/syslog. Existing"
echo "      /var/log/syslog files are left alone; remove them yourself if you"
echo "      want the space back."
