#!/usr/bin/env bats
# deploy/storage/install-data-root-recovery.sh and scripts/verify-data-root-recovery.sh:
# when the data drive drops out and comes back, Orpheus must come back too
# (jetson1, 2026-11-22: a USB drop 110 s after boot stopped every data-root
# service, the drive returned, and nothing remounted it or restarted them).
# A fake systemctl/udevadm stand in; the installer writes a sandbox root.

load 'test_helper'

INSTALL="$REPO_ROOT/deploy/storage/install-data-root-recovery.sh"
CHECK="$REPO_ROOT/scripts/verify-data-root-recovery.sh"
UUID=84ad2057-1fe4-4365-a76c-c4ebbd7dd5e8

setup() {
  SB="$BATS_TEST_TMPDIR"
  mkdir -p "$SB/state" "$SB/root/etc"
  # state/<unit>.<Property> is what `systemctl show` reports, state/<unit>.enabled
  # what is-enabled reports. Every systemctl and udevadm call is logged.
  cat > "$SB/systemctl" <<EOF2
#!/bin/bash
echo "systemctl \$*" >> "$SB/calls"
case "\$1" in
  is-enabled) cat "$SB/state/\$2.enabled" 2>/dev/null || echo disabled ;;
  show) cat "$SB/state/\$2.\$4" 2>/dev/null ;;
esac
EOF2
  printf '#!/bin/bash\necho "udevadm $*" >> "%s/calls"\n' "$SB" > "$SB/udevadm"
  chmod +x "$SB/systemctl" "$SB/udevadm"
  export SYSTEMCTL="$SB/systemctl" UDEVADM="$SB/udevadm" ORPHEUS_RECOVERY_ROOT="$SB/root"
  RULE="$SB/root/etc/udev/rules.d/90-orpheus-data-root.rules"
}

fstab() { printf '%s\n' "/dev/root / ext4 defaults 0 1" "$1 /data/orpheus ext4 defaults,nofail 0 2" > "$SB/root/etc/fstab"; }
set_prop() { printf '%s\n' "$3" > "$SB/state/$1.$2"; }
service() {  # <name> <enabled|disabled>: an installed data-root service
  set_prop "$1.service" LoadState loaded
  echo "$2" > "$SB/state/$1.service.enabled"
}

# --- installer ---------------------------------------------------------------

@test "install: the drive named by UUID in fstab starts its mount when it appears" {
  fstab "UUID=$UUID"
  run "$INSTALL"
  [ "$status" -eq 0 ]
  grep -qx "ACTION!=\"remove\", SUBSYSTEM==\"block\", ENV{ID_FS_UUID}==\"$UUID\", ENV{SYSTEMD_WANTS}+=\"data-orpheus.mount\"" "$RULE"
}

@test "install: reloads udev and systemd, and starts, restarts or re-triggers nothing" {
  fstab "UUID=$UUID"
  run "$INSTALL"
  [ "$status" -eq 0 ]
  grep -qx "udevadm control --reload" "$SB/calls"
  grep -qx "systemctl daemon-reload" "$SB/calls"
  ! grep -qE 'trigger|systemctl (start|stop|restart|try-restart|reload-or-restart)|--now' "$SB/calls"
}

@test "install: a LABEL= or PARTUUID= entry maps to the matching udev property" {
  fstab "LABEL=orpheus-data"
  run "$INSTALL"
  grep -q 'ENV{ID_FS_LABEL}=="orpheus-data"' "$RULE"
  fstab "PARTUUID=6a90dd88-aacf-4fa5-980b-0ce993528484"
  run "$INSTALL"
  grep -q 'ENV{ID_PART_ENTRY_UUID}=="6a90dd88-aacf-4fa5-980b-0ce993528484"' "$RULE"
}

@test "install: a kernel device name gets no rule, and install-host carries on" {
  # The name changes when the drive reconnects (sde -> sdf). Exit 0 so the rest
  # of make install-host still runs; verify-deploy reports it instead.
  fstab "/dev/sde1"
  run "$INSTALL"
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING"*"UUID="* ]]
  [ ! -e "$RULE" ]
}

@test "install: a network share is not a drive to recover" {
  fstab "nas:/export/orpheus"
  run "$INSTALL"
  [ "$status" -eq 0 ]
  [[ "$output" == *"not a local drive"* ]]
  [ ! -e "$RULE" ]
}

@test "install: /dev/disk/by-* paths map to the same stable identifiers" {
  fstab "/dev/disk/by-uuid/$UUID"
  run "$INSTALL"
  grep -q "ENV{ID_FS_UUID}==\"$UUID\"" "$RULE"
  fstab "/dev/disk/by-partuuid/6a90dd88-aacf-4fa5-980b-0ce993528484"
  run "$INSTALL"
  grep -q 'ENV{ID_PART_ENTRY_UUID}=="6a90dd88-aacf-4fa5-980b-0ce993528484"' "$RULE"
}

@test "install: a data root that is not its own fstab entry needs nothing" {
  printf '/dev/root / ext4 defaults 0 1\n' > "$SB/root/etc/fstab"
  run "$INSTALL"
  [ "$status" -eq 0 ]
  [[ "$output" == *"nothing installed"* ]]
  [ ! -e "$RULE" ]
}

@test "install: any disk UUID works; nothing about jetson1 is built in" {
  other=0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0
  fstab "UUID=$other"
  run "$INSTALL"
  [ "$status" -eq 0 ]
  grep -q "ENV{ID_FS_UUID}==\"$other\"" "$RULE"
  ! grep -q "$UUID" "$RULE"
}

@test "install: refuses a data drive mounted anywhere but /data/orpheus" {
  # The units require and restart with data-orpheus.mount; a rule for another
  # mount would remount the drive but never bring the services back.
  printf 'UUID=%s /srv/orpheus-data ext4 defaults,nofail 0 2\n' "$UUID" > "$SB/root/etc/fstab"
  run "$INSTALL" /srv/orpheus-data
  [ "$status" -eq 1 ]
  [[ "$output" == *"Mount the data drive at /data/orpheus"* ]]
  [ ! -e "$RULE" ]
}

@test "install: a development data root outside fstab needs nothing" {
  printf '/dev/root / ext4 defaults 0 1\n' > "$SB/root/etc/fstab"
  run "$INSTALL" "$HOME/data/orpheus"
  [ "$status" -eq 0 ]
  [ ! -e "$RULE" ]
}

@test "install: is idempotent and leaves no temporary file in rules.d" {
  fstab "UUID=$UUID"
  run "$INSTALL"
  run "$INSTALL"
  [ "$status" -eq 0 ]
  [ "$(ls "$SB/root/etc/udev/rules.d")" = "90-orpheus-data-root.rules" ]
}

# --- verify ------------------------------------------------------------------

@test "verify: passes when the rule is in place and the mount wants every enabled service" {
  fstab "UUID=$UUID"
  "$INSTALL" >/dev/null
  service orpheus-agent-audio-motion enabled
  service orpheus-ui enabled
  set_prop data-orpheus.mount Wants "orpheus-agent-audio-motion.service orpheus-ui.service systemd-fsck@x.service"
  run "$CHECK"
  [ "$status" -eq 0 ]
  [[ "$output" == *"✅ the drive (UUID=$UUID) starts data-orpheus.mount when it reappears"* ]]
  [[ "$output" == *"restarts all 2 enabled data-root services"* ]]
}

@test "verify: fails as jetson1 stood on 2026-11-22, naming what would stay down" {
  fstab "UUID=$UUID"
  service orpheus-agent-audio-motion enabled
  service orpheus-ui enabled
  set_prop data-orpheus.mount Wants "systemd-fsck@x.service"
  run "$CHECK"
  [ "$status" -eq 1 ]
  [[ "$output" == *"❌ nothing mounts /data/orpheus again when the drive reappears"* ]]
  [[ "$output" == *"❌ data-orpheus.mount would not restart"*"orpheus-agent-audio-motion.service orpheus-ui.service"* ]]
  [[ "$output" == *"make install-data-root-recovery"* ]]
}

@test "verify: a service the operator disabled is not expected back" {
  fstab "UUID=$UUID"
  "$INSTALL" >/dev/null
  service orpheus-agent-audio-motion enabled
  service orpheus-agent-crow-detection disabled
  set_prop data-orpheus.mount Wants "orpheus-agent-audio-motion.service"
  run "$CHECK"
  [ "$status" -eq 0 ]
}

@test "verify: a rule for a different drive does not count" {
  fstab "UUID=$UUID"
  "$INSTALL" >/dev/null
  fstab "UUID=00000000-0000-0000-0000-000000000000"
  run "$CHECK"
  [ "$status" -eq 1 ]
  [[ "$output" == *"❌ nothing mounts /data/orpheus again"* ]]
}

@test "verify: a kernel device name in fstab fails with the fix" {
  fstab "/dev/sde1"
  run "$CHECK"
  [ "$status" -eq 1 ]
  [[ "$output" == *"❌"*"kernel name"*"use UUID="* ]]
}

@test "verify: a network share passes, as nothing to recover" {
  fstab "nas:/export/orpheus"
  run "$CHECK"
  [ "$status" -eq 0 ]
  [[ "$output" == *"not a local drive"* ]]
}

@test "verify: a data drive mounted elsewhere fails" {
  printf 'UUID=%s /srv/orpheus-data ext4 defaults,nofail 0 2\n' "$UUID" > "$SB/root/etc/fstab"
  run "$CHECK" /srv/orpheus-data
  [ "$status" -eq 1 ]
  [[ "$output" == *"mount the drive there"* ]]
}

@test "verify: a data root on the system disk passes" {
  printf '/dev/root / ext4 defaults 0 1\n' > "$SB/root/etc/fstab"
  run "$CHECK"
  [ "$status" -eq 0 ]
  [[ "$output" == *"not a separate drive"* ]]
}

# --- shipped units ---------------------------------------------------------

@test "every long-running data-root service in the repo is wanted by the data mount" {
  source "$REPO_ROOT/scripts/data-root-units.sh"
  for name in "${DATA_ROOT_SERVICES[@]}"; do
    unit="$(find "$REPO_ROOT/agents" "$REPO_ROOT/services" -name "$name.service" -path '*/systemd/*' | head -1)"
    [ -n "$unit" ] || fail "$name.service not found"
    grep -qE '^WantedBy=(.*\s)?data-orpheus\.mount(\s|$)' "$unit" || fail "$name: no WantedBy=data-orpheus.mount"
    grep -qE '^WantedBy=(.*\s)?multi-user\.target(\s|$)' "$unit" || fail "$name: lost WantedBy=multi-user.target"
  done
}
