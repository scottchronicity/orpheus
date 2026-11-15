#!/usr/bin/env bats
# scripts/verify-deploy-isolation.sh — runtime overrides, home-directory paths
# in units, and deployed venvs that depend on a home directory. A fake
# systemctl serves `systemctl show` output from fixture files; the deploy
# prefix is a sandbox tree. Nothing on the host is read or changed.

load 'test_helper'

CHECK="$REPO_ROOT/scripts/verify-deploy-isolation.sh"

setup() {
  SB="$BATS_TEST_TMPDIR"
  UNITS="$SB/units"
  PREFIX="$SB/opt"
  mkdir -p "$UNITS" "$PREFIX/agents"
  cat > "$SB/systemctl" <<EOF
#!/bin/bash
case "\$1" in
  list-unit-files) for f in "$UNITS"/*.props; do [ -e "\$f" ] && echo "\$(basename "\$f" .props) enabled enabled"; done ;;
  show) cat "$UNITS/\${!#}.props" ;;
esac
EOF
  chmod +x "$SB/systemctl"
  export SYSTEMCTL="$SB/systemctl"
}

# unit <name> <KEY=VALUE...>: a clean unit, with the given properties overridden.
unit() {
  local name="$1"; shift
  {
    echo "FragmentPath=/etc/systemd/system/$name"
    echo "DropInPaths="
    echo "ExecStart={ path=/opt/orpheus/agents/x/venv/bin/python ; argv[]=/opt/orpheus/agents/x/venv/bin/python -m x ; }"
    echo "Environment=PYTHONUNBUFFERED=1 XDG_RUNTIME_DIR=/run/user/1001 PULSE_SERVER=unix:/run/user/1001/pulse/native"
    echo "EnvironmentFiles="
    echo "WorkingDirectory=/opt/orpheus/agents/x"
  } > "$UNITS/$name.props"
  # Like real `systemctl show`, each key appears once: extras replace defaults.
  local line
  for line in "$@"; do
    grep -v "^${line%%=*}=" "$UNITS/$name.props" > "$UNITS/$name.tmp" || true
    echo "$line" >> "$UNITS/$name.tmp"
    mv "$UNITS/$name.tmp" "$UNITS/$name.props"
  done
}

# venv <agent>: a clean deployed venv.
venv() {
  V="$PREFIX/agents/$1/venv"
  mkdir -p "$V/bin" "$V/lib/python3.9/site-packages/pkg-1.0.dist-info"
  printf 'home = /usr/bin\n' > "$V/pyvenv.cfg"
  ln -s /usr/bin/python3 "$V/bin/python"
  printf '#!%s/bin/python\nimport x\n' "$V" > "$V/bin/tool"
  echo "/opt/orpheus/agents/$1/src" > "$V/lib/python3.9/site-packages/local.pth"
  echo '{"dir_info": {}, "url": "file:///home/someone/checkout/pkg"}' > "$V/lib/python3.9/site-packages/pkg-1.0.dist-info/direct_url.json"
}

@test "a clean deployment passes (session /run/user paths and a recorded install origin are fine)" {
  unit orpheus-agent-a.service
  venv orpheus-agent-a
  run "$CHECK" "$PREFIX"
  assert_success
  refute_output --partial "❌"
}

@test "a runtime drop-in under /run/systemd fails" {
  unit orpheus-agent-a.service "DropInPaths=/etc/systemd/system/orpheus-agent-a.service.d/10-ok.conf /run/systemd/system/orpheus-agent-a.service.d/90-gpu.conf"
  run "$CHECK" "$PREFIX"
  assert_failure
  assert_output --partial "runtime drop-in /run/systemd/system/orpheus-agent-a.service.d/90-gpu.conf"
  refute_output --partial "10-ok.conf"
}

@test "a runtime-only unit fails" {
  unit orpheus-agent-a.service "FragmentPath=/run/systemd/system/orpheus-agent-a.service"
  run "$CHECK" "$PREFIX"
  assert_failure
  assert_output --partial "the unit itself is runtime-only"
}

@test "a home-directory PYTHONPATH in the effective Environment fails, naming the path" {
  unit orpheus-agent-a.service "Environment=PYTHONUNBUFFERED=1 PYTHONPATH=/home/orpheus/experiment/src:/opt/orpheus/x"
  run "$CHECK" "$PREFIX"
  assert_failure
  assert_output --partial "Environment uses a home-directory path (/home/orpheus/experiment/src)"
}

@test "a home-directory ExecStart or WorkingDirectory fails" {
  unit orpheus-agent-a.service "ExecStart={ path=/Users/me/venv/bin/python ; argv[]=/Users/me/venv/bin/python -m x ; }"
  unit orpheus-agent-b.service "WorkingDirectory=/home/me/checkout"
  run "$CHECK" "$PREFIX"
  assert_failure
  assert_output --partial "orpheus-agent-a.service: ExecStart uses a home-directory path"
  assert_output --partial "orpheus-agent-b.service: WorkingDirectory uses a home-directory path"
}

@test "an EnvironmentFile that sets a home-directory path fails; a commented one does not" {
  printf '# OLD=/home/me/x\nGOOD=/opt/x\n' > "$SB/good.env"
  printf 'MODEL_DIR=/home/me/models\n' > "$SB/bad.env"
  unit orpheus-agent-a.service "EnvironmentFiles=$SB/good.env (ignore_errors=yes)"
  run "$CHECK" "$PREFIX"
  assert_success
  unit orpheus-agent-a.service "EnvironmentFiles=$SB/bad.env (ignore_errors=no)"
  run "$CHECK" "$PREFIX"
  assert_failure
  assert_output --partial "EnvironmentFile $SB/bad.env sets a home-directory path"
}

@test "a venv whose scripts or editable installs point into a home directory fails" {
  unit orpheus-agent-a.service
  venv orpheus-agent-a
  printf '#!/home/me/checkout/venv/bin/python\n' > "$V/bin/coverage"
  echo "/home/me/checkout/src" > "$V/lib/python3.9/site-packages/__editable__.pkg-1.0.pth"
  run "$CHECK" "$PREFIX"
  assert_failure
  assert_output --partial "2 file(s) depend on a home directory"
  assert_output --partial "bin/coverage (shebang)"
}

@test "an interpreter symlinked into a home directory (uv/pyenv Python) fails" {
  unit orpheus-agent-a.service
  venv orpheus-agent-a
  rm "$V/bin/python"
  ln -s /home/nobody-here/.local/share/uv/python/bin/python3.12 "$V/bin/python"
  run "$CHECK" "$PREFIX"
  assert_failure
  assert_output --partial "bin/python -> /home/nobody-here/.local/share/uv/python/bin/python3.12"
}

@test "an editable install recorded in direct_url.json or a setuptools finder fails" {
  unit orpheus-agent-a.service
  venv orpheus-agent-a
  echo '{"dir_info": {"editable": true}, "url": "file:///home/me/checkout/pkg"}' > "$V/lib/python3.9/site-packages/pkg-1.0.dist-info/direct_url.json"
  echo "MAPPING = {'pkg': '/home/me/checkout/src/pkg'}" > "$V/lib/python3.9/site-packages/__editable___pkg_1_0_finder.py"
  run "$CHECK" "$PREFIX"
  assert_failure
  assert_output --partial "2 file(s) depend on a home directory"
  assert_output --partial "(editable)"
}

@test "no systemctl and nothing deployed: skipped, not failed" {
  SYSTEMCTL="$SB/no-such-systemctl" run "$CHECK" "$SB/nowhere"
  assert_success
  assert_output --partial "unit checks skipped"
  assert_output --partial "venv checks skipped"
}
