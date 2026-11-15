#!/usr/bin/env bats
# scripts/provision-python.sh — pinned interpreter outside any home directory.
# A fake uv lays out what `uv python install` would (an interpreter that
# reports FAKE_GOT as its version); nothing is downloaded or installed.

load 'test_helper'

TOOL="$REPO_ROOT/scripts/provision-python.sh"

setup() {
  SB="$BATS_TEST_TMPDIR"
  export PREFIX="$SB/opt/python" UV="$SB/uv" UV_LOG="$SB/uv.log"
  cat > "$UV" <<'EOF'
#!/bin/bash
if [ "$1" = "--version" ]; then echo "uv 0.0.0-fake"; exit 0; fi
echo "UV_NO_CONFIG=$UV_NO_CONFIG UV_CACHE_DIR=$UV_CACHE_DIR UV_PYTHON_INSTALL_DIR=$UV_PYTHON_INSTALL_DIR $*" >> "$UV_LOG"
ver="${!#}"; minor="${ver%.*}"
d="$UV_PYTHON_INSTALL_DIR/cpython-$ver-linux-$(uname -m)-gnu/bin"
mkdir -p "$d"
cat > "$d/python$minor" <<PY
#!/bin/bash
case "\$2" in
  *platform.python_version*) echo "\${FAKE_GOT:-$ver}" ;;
  *ensurepip*) [ -z "\$FAKE_NO_SSL" ] ;;
esac
PY
chmod +x "$d/python$minor"
EOF
  chmod +x "$UV"
}

@test "installs the pinned release under PREFIX with a stable symlink, isolated from user config and cache" {
  run "$TOOL"
  assert_success
  assert_output --partial "✅ CPython 3.12.13"
  link="$PREFIX/bin/python3.12"
  [ -L "$link" ]
  [ "$(readlink "$link")" = "$PREFIX/cpython-3.12.13-linux-$(uname -m)-gnu/bin/python3.12" ]
  grep -q "UV_NO_CONFIG=1 UV_CACHE_DIR=/" "$UV_LOG"
  grep -q "UV_PYTHON_INSTALL_DIR=$PREFIX python install --no-bin --no-registry 3.12.13" "$UV_LOG"
}

@test "dry run installs nothing" {
  run "$TOOL" --dry-run
  assert_success
  assert_output --partial "dry run: nothing was installed"
  [ ! -e "$PREFIX" ]
  [ ! -e "$UV_LOG" ]
}

@test "a PREFIX inside a home directory is refused" {
  PREFIX=/home/someone/python run "$TOOL"
  assert_failure
  assert_output --partial "inside a home directory"
}

@test "a floating version (3.12) is refused; the release must be exact" {
  PYTHON_VERSION=3.12 run "$TOOL"
  assert_failure
  assert_output --partial "must be an exact release"
}

@test "an interpreter that reports another version fails" {
  FAKE_GOT=3.12.1 run "$TOOL"
  assert_failure
  assert_output --partial "reports 3.12.1, expected 3.12.13"
}

@test "an interpreter missing a stdlib module the services need fails" {
  FAKE_NO_SSL=1 run "$TOOL"
  assert_failure
  assert_output --partial "missing a standard-library module"
}
