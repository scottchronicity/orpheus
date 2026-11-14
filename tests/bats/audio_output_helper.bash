#!/usr/bin/env bash
# Sandbox for the audio-output installer suites: a fake root ($SYSROOT) and
# stateful mocks of systemctl (system + the user's manager via runuser),
# loginctl, getent, id, pgrep/pkill, a python that builds a fake venv, and the
# audio tools. Unit state lives in $MOCK/units/<name>.{enabled,active}.

audio_output_sandbox() {
  export SYSROOT="$BATS_TEST_TMPDIR/root"
  export MOCK="$BATS_TEST_TMPDIR/mock"
  export MOCK_LOG="$MOCK/calls"
  mkdir -p "$SYSROOT/etc/systemd/system" "$SYSROOT/usr/local/bin" \
    "$SYSROOT/home/orpheus" "$SYSROOT/opt/orpheus/services" \
    "$SYSROOT/usr/lib/pulse-13.99.1/modules" "$MOCK/units" "$MOCK/bin"
  for m in module-native-protocol-unix module-bluetooth-policy module-bluetooth-discover; do
    touch "$SYSROOT/usr/lib/pulse-13.99.1/modules/$m.so"
  done

  cat > "$MOCK/bin/systemctl" <<'EOF'
#!/bin/bash
echo "systemctl $*" >> "$MOCK_LOG"
u="$MOCK/units"
[ "$1" = --user ] && { echo "unexpected direct --user" >> "$MOCK_LOG"; exit 1; }
cmd="$1"; shift
if [ "$cmd" = show ]; then   # show -p <Prop> --value <unit>
  prop="$2"; name="$4"
  case "$prop" in
    LoadState) [ -f "$SYSROOT/etc/systemd/system/$name" ] && echo loaded || echo not-found ;;
    User) [ "$name" = orpheus-agent-audio-playback.service ] && echo "${FAKE_PLAYBACK_USER:-orpheus}" ;;
  esac
  exit 0
fi
[ "${1:-}" = --quiet ] && shift
[ "${1:-}" = --now ] && { now=1; shift; }
name="${1:-}"
case "$cmd" in
  is-enabled) [ -f "$u/$name.enabled" ]; exit $? ;;
  is-active)
    if [ "$name" = "user@1001.service" ]; then [ -f "$MOCK/user-manager" ]; exit $?; fi
    [ -f "$u/$name.active" ]; exit $? ;;
  enable) touch "$u/$name.enabled" ;;
  disable) rm -f "$u/$name.enabled"; [ -n "${now:-}" ] && rm -f "$u/$name.active" ;;
  start|restart)
    touch "$u/$name.active"
    [ "$cmd" = restart ] && echo "restarted $name" >> "$MOCK/restarts"
    if [ "$name" = orpheus-audio-output.service ]; then
      if [ -n "${FAKE_UNIT_DIES:-}" ]; then rm -f "$u/$name.active"; exit 0; fi
      if [ -n "${FAKE_HEALTH:-}" ]; then
        mkdir -p "$SYSROOT/run/orpheus-audio-output"
        cp "$FAKE_HEALTH" "$SYSROOT/run/orpheus-audio-output/health.json"
      fi
    fi ;;
  stop) rm -f "$u/$name.active" ;;
  try-restart) [ -f "$u/$name.active" ] && echo "restarted $name" >> "$MOCK/restarts" ;;
esac
exit 0
EOF

  # runuser -u <user> -- env K=V... systemctl --user <args>
  cat > "$MOCK/bin/runuser" <<'EOF'
#!/bin/bash
echo "runuser $*" >> "$MOCK_LOG"
while [ "$1" != systemctl ]; do shift; done
shift 2  # systemctl --user
home="$SYSROOT/home/orpheus/.config/systemd/user"
case "$1" in
  daemon-reload) echo reload >> "$MOCK/user-reloads" ;;
  stop) rm -f "$MOCK/user-socket-active" ;;
  show)
    prop="$3"; unit="$5"
    if [ "$prop" = LoadState ]; then
      if [ -n "${FAKE_USER_LOADSTATE:-}" ]; then echo "$FAKE_USER_LOADSTATE"
      elif [ "$(readlink "$home/$unit" 2>/dev/null)" = /dev/null ] && [ -f "$MOCK/user-reloads" ]; then echo masked
      else echo loaded; fi
    else
      if [ -f "$MOCK/user-socket-active" ] && [ "$unit" = pulseaudio.socket ]; then echo active; else echo inactive; fi
    fi ;;
esac
exit 0
EOF

  cat > "$MOCK/bin/loginctl" <<'EOF'
#!/bin/bash
echo "loginctl $*" >> "$MOCK_LOG"
case "$1" in
  show-user)
    # Like systemd 245: fails when the user has no session and no lingering.
    if [ -n "${FAKE_SHOWUSER_FAILS:-}" ] && [ ! -f "$MOCK/linger" ]; then
      echo "Failed to get user: User ID 1001 is not logged in or lingering" >&2; exit 1
    fi
    [ -f "$MOCK/linger" ] && echo yes || echo no ;;
  enable-linger) touch "$MOCK/linger"; [ -n "${FAKE_NO_USER_MANAGER:-}" ] || touch "$MOCK/user-manager" ;;
  disable-linger) rm -f "$MOCK/linger" ;;
esac
EOF

  cat > "$MOCK/bin/getent" <<'EOF'
#!/bin/bash
[ "$1" = passwd ] && echo "$2:x:1001:1002::/home/$2:/bin/bash"
EOF
  cat > "$MOCK/bin/id" <<'EOF'
#!/bin/bash
[ -n "${FAKE_NO_USER:-}" ] && exit 1
case "$1" in -u) echo 1001;; -g) echo 1002;; *) echo "uid=1001";; esac
EOF
  # pgrep lists the pids in $MOCK/pulseaudio-pids; each has a fake
  # $SYSROOT/proc/<pid>/cmdline (see pulseaudio_running).
  cat > "$MOCK/bin/pgrep" <<'EOF'
#!/bin/bash
[ -s "$MOCK/pulseaudio-pids" ] && cat "$MOCK/pulseaudio-pids"
EOF
  cat > "$MOCK/bin/fakekill" <<'EOF'
#!/bin/bash
echo "kill $*" >> "$MOCK_LOG"
awk -v pid="$1" '$0 != pid { print }' "$MOCK/pulseaudio-pids" > "$MOCK/pulseaudio-pids.tmp"
mv "$MOCK/pulseaudio-pids.tmp" "$MOCK/pulseaudio-pids"
EOF
  for tool in bluetoothctl pulseaudio pactl; do
    printf '#!/bin/bash\nexit 0\n' > "$MOCK/bin/$tool"
  done

  # python3.9 -m venv DIR: a venv whose python answers `-m ... check` from
  # $FAKE_CHECK_JSON / $FAKE_CHECK_RC and runs everything else with python3.
  local real_python
  real_python="$(command -v python3)"
  cat > "$MOCK/bin/fakepython" <<EOF
#!/bin/bash
if [ "\$1" = -m ] && [ "\$2" = venv ]; then
  mkdir -p "\$3/bin"
  printf '#!/bin/bash\necho "pip \$*" >> "\$MOCK_LOG"\n' > "\$3/bin/pip"
  cat > "\$3/bin/python" <<'PY'
#!/bin/bash
if [ "\$1 \$2 \$3" = "-m orpheus_audio_output.main check" ]; then
  cat "\$FAKE_CHECK_JSON"; exit "\${FAKE_CHECK_RC:-0}"
fi
exec $real_python "\$@"
PY
  # A generated entry point, as pip writes one: its shebang names the
  # directory the venv was created in (the staging directory).
  printf '#!%s/bin/python\nprint("tool ok")\n' "\$3" > "\$3/bin/orpheus-tool"
  if [ -n "\${FAKE_BROKEN_SCRIPT:-}" ]; then
    printf '#!/nonexistent/python\n' > "\$3/bin/broken-tool"
  fi
  chmod +x "\$3/bin/pip" "\$3/bin/python" "\$3/bin/orpheus-tool" "\$3/bin/"*
  exit 0
fi
exec $real_python "\$@"
EOF
  chmod +x "$MOCK/bin"/*
  export PATH="$MOCK/bin:$PATH"
  export PYTHON_BIN="$MOCK/bin/fakepython"
  export COMMON_PATH="$BATS_TEST_TMPDIR"
  export REQUIRE_ROOT=0 HEALTH_WAIT_SECONDS=3 USER_MANAGER_WAIT_SECONDS=1
  export KILL_CMD="$MOCK/bin/fakekill"

  export FAKE_CHECK_JSON="$MOCK/check.json"
  echo '{"valid": true, "config": {"enabled": true, "output": {"type": "bluetooth", "bluetooth": {"address": "FC:58:FA:02:AF:28"}}, "server": {"type": "pulseaudio", "pulseaudio": {"user": "orpheus"}}, "reconnect": {}, "source": "legacy"}}' > "$FAKE_CHECK_JSON"
  export FAKE_HEALTH="$MOCK/health-ok.json"
  echo '{"status": "healthy", "server": {"state": "ready", "consecutive_failures": 0}, "output": {"state": "connected"}, "routing": {"state": "routed"}, "capture_isolation": {"ok": true}}' > "$FAKE_HEALTH"
}

unit_on() {  # unit_on <name> enabled|active...
  local name="$1"; shift
  for s in "$@"; do touch "$MOCK/units/$name.$s"; done
}

# Use these as standalone statements: bats ignores a failing `! cmd` and any
# non-final command of an `a && b` list.
is_enabled() { [ -f "$MOCK/units/$1.enabled" ] || { echo "$1 is not enabled" >&2; return 1; }; }
is_active() { [ -f "$MOCK/units/$1.active" ] || { echo "$1 is not running" >&2; return 1; }; }
refute_enabled() { if [ -f "$MOCK/units/$1.enabled" ]; then echo "$1 is enabled" >&2; return 1; fi; }
refute_active() { if [ -f "$MOCK/units/$1.active" ]; then echo "$1 is running" >&2; return 1; fi; }

legacy_installed() {
  printf '[Service]\nExecStart=/usr/local/bin/orpheus-bluetooth-connect\n' \
    > "$SYSROOT/etc/systemd/system/orpheus-bluetooth-autoconnect.service"
  echo '#!/bin/bash' > "$SYSROOT/usr/local/bin/orpheus-bluetooth-connect"
}

# pulseaudio_running <pid> stock|managed
pulseaudio_running() {
  mkdir -p "$SYSROOT/proc/$1"
  if [ "$2" = managed ]; then
    printf 'pulseaudio\0--daemonize=no\0-n\0-F\0/run/orpheus-audio-output/pulseaudio.pa\0' > "$SYSROOT/proc/$1/cmdline"
  else
    printf 'pulseaudio\0--start\0' > "$SYSROOT/proc/$1/cmdline"
  fi
  echo "$1" >> "$MOCK/pulseaudio-pids"
}

playback_installed() {
  printf '[Service]\nUser=orpheus\n' > "$SYSROOT/etc/systemd/system/orpheus-agent-audio-playback.service"
  unit_on orpheus-agent-audio-playback.service enabled active
}

competing_unit() {
  printf '[Service]\nType=oneshot\nExecStart=/usr/bin/bluetoothctl connect FC:58:FA:02:AF:28\n' \
    > "$SYSROOT/etc/systemd/system/bluetooth-speaker-connect.service"
}
