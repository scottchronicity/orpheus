#!/usr/bin/env bats
# Bird-detection and event-correlator installers: what they copy into the
# deployment and which interpreter/venv they leave behind. Run against a
# sandbox source tree full of debris (a dev venv, an old venv, venv-py312,
# .env, tests, caches) with a fake interpreter that can claim any version and
# builds a minimal venv. No real /opt, systemd, pip or network is touched.

load 'test_helper'

setup() {
  SB="$BATS_TEST_TMPDIR"
  export MOCK_LOG="$SB/calls"
  BIN="$SB/bin"
  mkdir -p "$BIN" "$SB/opt/platform" "$SB/systemd"
  export PLATFORM_DIR="$SB/opt/platform" SYSTEMD_DIR="$SB/systemd"

  # Fake interpreter: FAKE_PY sets the version it claims.
  cat > "$BIN/fakepython" <<'EOF'
#!/usr/bin/env python3
import os, pathlib, sys
ver = tuple(int(x) for x in os.environ.get("FAKE_PY", "3.9").split("."))
args = sys.argv[1:]
if args[:1] == ["-c"]:
    sys.version_info = ver + (0, "final", 0)
    exec(compile(args[1], "<c>", "exec"), {"__name__": "__main__"})
    sys.exit(0)
if args[:2] == ["-m", "venv"]:
    d = pathlib.Path(args[2])
    (d / "bin").mkdir(parents=True, exist_ok=True)
    sp = d / "lib" / f"python{ver[0]}.{ver[1]}" / "site-packages"
    sp.mkdir(parents=True, exist_ok=True)
    pip = d / "bin" / "pip"
    pip.write_text('#!/bin/bash\necho "venv-pip $*" >> "$MOCK_LOG"\n')
    pip.chmod(0o755)
    py = d / "bin" / "python"
    py.write_text(f'#!/bin/bash\nFAKE_PY={".".join(map(str, ver))} exec "{sys.argv[0]}" "$@"\n')
    py.chmod(0o755)
    (d / "bin" / "activate").write_text("")
    if os.environ.get("FAKE_PTH_HOME"):
        (sp / "__editable__.checkout.pth").write_text("/home/someone/checkout/src\n")
    sys.exit(0)
sys.exit(2)
EOF
  printf '#!/bin/bash\necho "systemctl $*" >> "$MOCK_LOG"\n' > "$BIN/systemctl"
  printf '#!/bin/bash\nexec "$@"\n' > "$BIN/sudo"
  printf '#!/bin/bash\necho "path-pip $*" >> "$MOCK_LOG"\n' > "$BIN/pip"
  chmod +x "$BIN"/*
  export PATH="$BIN:$PATH" PYTHON_BIN="$BIN/fakepython"
}

# make_agent <name>: a source tree with the real installer and lots of debris.
make_agent() {
  local name="$1"
  AGENT="$SB/src/agents/$name"
  mkdir -p "$AGENT/src/pkg" "$AGENT/systemd" "$AGENT/tests" "$AGENT/src/pkg/__pycache__"
  cp "$REPO_ROOT/agents/$name/systemd/install-service.sh" "$AGENT/systemd/"
  echo "[Unit]" > "$AGENT/systemd/$name.service"
  echo "x = 1" > "$AGENT/src/pkg/__init__.py"
  echo "junk" > "$AGENT/src/pkg/__pycache__/__init__.cpython-39.pyc"
  printf '[project]\nname = "x"\n' > "$AGENT/pyproject.toml"
  printf -- '-e ../../platform/orpheus-common\n-e .\n' > "$AGENT/requirements.txt"
  printf -- '-e ../../platform/orpheus-common\n-e .[onnx-cuda]\n' > "$AGENT/requirements-cuda.txt"
  echo "0.1.0" > "$AGENT/VERSION"
  for debris in venv oldvenv venv-py312 .venv; do
    mkdir -p "$AGENT/$debris/bin"
    echo "dev" > "$AGENT/$debris/bin/MARKER"
  done
  echo "SECRET=1" > "$AGENT/.env"
  echo "def test(): pass" > "$AGENT/tests/test_x.py"
  INSTALL="$SB/opt/agents/$name"
}

assert_payload_only() {
  [ -f "$INSTALL/src/pkg/__init__.py" ]
  [ -f "$INSTALL/pyproject.toml" ]
  [ -f "$INSTALL/systemd/$1.service" ]
  for debris in oldvenv venv-py312 .venv .env tests src/pkg/__pycache__; do
    [ ! -e "$INSTALL/$debris" ] || { echo "copied $debris" >&2; return 1; }
  done
  [ ! -e "$INSTALL/venv/bin/MARKER" ] || { echo "dev venv copied over the deployed one" >&2; return 1; }
}

# --- bird-detection -------------------------------------------------------------
@test "bird: deploys only the payload, never a working-tree or old venv" {
  make_agent orpheus-agent-bird-detection
  INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  assert_success
  assert_payload_only orpheus-agent-bird-detection
  grep -qx "venv-pip install -r requirements.txt" "$MOCK_LOG"
  grep -q "systemctl enable orpheus-agent-bird-detection" "$MOCK_LOG"
}

@test "bird: refuses a Python that is not 3.9 (python3 is 3.8 on JetPack 5)" {
  make_agent orpheus-agent-bird-detection
  FAKE_PY=3.8 INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  assert_failure
  assert_output --partial "requires Python 3.9"
  [ ! -e "$INSTALL" ]
}

@test "bird: rebuilds a deployed venv that references a home directory" {
  make_agent orpheus-agent-bird-detection
  mkdir -p "$INSTALL/venv/lib/python3.9/site-packages"
  echo "/home/orpheus/runtime/orpheus/agents/x/src" > "$INSTALL/venv/lib/python3.9/site-packages/__editable__.old.pth"
  INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  assert_success
  [ ! -e "$INSTALL/venv/lib/python3.9/site-packages/__editable__.old.pth" ]
}

@test "bird: a new venv that points into a home directory fails the install" {
  make_agent orpheus-agent-bird-detection
  FAKE_PTH_HOME=1 INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  assert_failure
  assert_output --partial "references a home directory"
  run grep -q "systemctl enable" "$MOCK_LOG"
  assert_failure
}

@test "bird: ONNX_RUNTIME picks the CUDA requirements, and rejects anything else" {
  make_agent orpheus-agent-bird-detection
  ONNX_RUNTIME=cuda INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  assert_success
  grep -qx "venv-pip install -r requirements-cuda.txt" "$MOCK_LOG"
  ONNX_RUNTIME=tensorrt INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  assert_failure
  assert_output --partial "ONNX_RUNTIME must be cpu or cuda"
}

@test "bird: needs the platform deployed first" {
  make_agent orpheus-agent-bird-detection
  PLATFORM_DIR="$SB/nowhere" INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  assert_failure
  assert_output --partial "orpheus-common is not deployed"
}

# --- event-correlator -------------------------------------------------------------
@test "correlator: a dev venv is never copied over the deployed one" {
  make_agent orpheus-agent-event-correlator
  FAKE_PY=3.12 INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  assert_success
  assert_payload_only orpheus-agent-event-correlator
  [ -x "$INSTALL/venv/bin/python" ]
}

@test "correlator: a deployed venv that references a home directory is rebuilt" {
  make_agent orpheus-agent-event-correlator
  FAKE_PY=3.12 INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  echo "/home/someone/checkout/src" > "$INSTALL/venv/lib/python3.12/site-packages/__editable__.x.pth"
  : > "$MOCK_LOG"
  FAKE_PY=3.12 INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  assert_success
  assert_output --partial "references a home directory"
  [ ! -e "$INSTALL/venv/lib/python3.12/site-packages/__editable__.x.pth" ]
}

@test "correlator: a clean, compatible deployed venv is kept" {
  make_agent orpheus-agent-event-correlator
  FAKE_PY=3.12 INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  echo keep > "$INSTALL/venv/KEEP"
  FAKE_PY=3.12 INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  assert_success
  [ -f "$INSTALL/venv/KEEP" ]
}

@test "correlator: a Python 3.9 venv left by the old layout is replaced" {
  make_agent orpheus-agent-event-correlator
  FAKE_PY=3.9 "$BIN/fakepython" -m venv "$INSTALL/venv"
  echo old > "$INSTALL/venv/OLD"
  FAKE_PY=3.12 INSTALL_DIR="$INSTALL" run bash "$AGENT/systemd/install-service.sh"
  assert_success
  assert_output --partial "Replacing the existing incompatible Python environment"
  [ ! -e "$INSTALL/venv/OLD" ]
  [ -d "$INSTALL/venv/lib/python3.12" ]
}
