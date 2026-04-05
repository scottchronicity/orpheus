#!/usr/bin/env bash
# Tests for shared Makefile includes (make/common_*.mk)
#
# Validates deploy, python, lint, and service shared logic plus
# integration with all component Makefiles. Runs without sudo by
# stubbing it out.
#
# Usage:  bash tests/make/test_shared_make.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMPDIR_BASE="$(mktemp -d)"
PASS=0
FAIL=0

cleanup() { rm -rf "$TMPDIR_BASE"; }
trap cleanup EXIT

pass() { PASS=$((PASS + 1)); echo "  ✓ $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  ✗ $1"; }

# ---------------------------------------------------------------------------
# Helper: create a minimal Makefile that includes common_deploy.mk
# ---------------------------------------------------------------------------
setup_fixture() {
    local name="$1"
    local deploy_root="$2"
    local src_dir="${3:-src/}"
    local extra_files="${4:-pyproject.toml requirements.txt}"

    local dir="$TMPDIR_BASE/$name"
    mkdir -p "$dir/$src_dir" "$deploy_root/src"

    # Create source fixtures
    echo "print('hello')" > "$dir/${src_dir}main.py"
    echo '[project]' > "$dir/pyproject.toml"
    echo 'requests' > "$dir/requirements.txt"

    # Stub sudo as passthrough (no actual privilege escalation)
    mkdir -p "$dir/bin"
    cat > "$dir/bin/sudo" << 'STUB'
#!/usr/bin/env bash
"$@"
STUB
    chmod +x "$dir/bin/sudo"

    # Write the test Makefile
    cat > "$dir/Makefile" << EOF
SERVICE_NAME       := test-service
DEPLOY_ROOT        := $deploy_root
DEPLOY_SRC_DIR     := $src_dir
DEPLOY_EXTRA_FILES := $extra_files

include $REPO_ROOT/make/common_deploy.mk
EOF

    echo "$dir"
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
echo "Testing make/common_deploy.mk"
echo ""

# -- Test 1: deploy syncs source files --------------------------------------
echo "  deploy target:"

DEPLOY_ROOT_1="$TMPDIR_BASE/deploy1"
mkdir -p "$DEPLOY_ROOT_1/src"
FIXTURE_1="$(setup_fixture test1 "$DEPLOY_ROOT_1")"

output="$(cd "$FIXTURE_1" && PATH="$FIXTURE_1/bin:$PATH" make deploy 2>&1)" || true
if [ -f "$DEPLOY_ROOT_1/src/main.py" ]; then
    pass "rsyncs source files to DEPLOY_ROOT/src/"
else
    fail "rsyncs source files to DEPLOY_ROOT/src/"
fi

# -- Test 2: deploy copies extra files --------------------------------------
if [ -f "$DEPLOY_ROOT_1/pyproject.toml" ] && [ -f "$DEPLOY_ROOT_1/requirements.txt" ]; then
    pass "copies DEPLOY_EXTRA_FILES to DEPLOY_ROOT"
else
    fail "copies DEPLOY_EXTRA_FILES to DEPLOY_ROOT"
fi

# -- Test 3: deploy fails when DEPLOY_ROOT doesn't exist --------------------
FIXTURE_3="$(setup_fixture test3 "$TMPDIR_BASE/nonexistent")"
# setup_fixture creates the deploy_root dir; remove it so we can test the missing-dir check
rm -rf "$TMPDIR_BASE/nonexistent"
output="$(cd "$FIXTURE_3" && PATH="$FIXTURE_3/bin:$PATH" make deploy 2>&1)" && rc=0 || rc=$?
if [ $rc -ne 0 ] && echo "$output" | grep -q "not found"; then
    pass "fails with clear error when DEPLOY_ROOT missing"
else
    fail "fails with clear error when DEPLOY_ROOT missing (rc=$rc)"
fi

# -- Test 4: custom DEPLOY_SRC_DIR works ------------------------------------
DEPLOY_ROOT_4="$TMPDIR_BASE/deploy4"
mkdir -p "$DEPLOY_ROOT_4/src"
FIXTURE_4="$(setup_fixture test4 "$DEPLOY_ROOT_4" "backend/src/")"
mkdir -p "$FIXTURE_4/backend/src"
echo "app = True" > "$FIXTURE_4/backend/src/app.py"

output="$(cd "$FIXTURE_4" && PATH="$FIXTURE_4/bin:$PATH" make deploy 2>&1)" || true
if [ -f "$DEPLOY_ROOT_4/src/app.py" ]; then
    pass "respects custom DEPLOY_SRC_DIR"
else
    fail "respects custom DEPLOY_SRC_DIR"
fi

# -- Test 5: rsync --delete removes stale files -----------------------------
echo "stale" > "$DEPLOY_ROOT_1/src/old_file.py"
output="$(cd "$FIXTURE_1" && PATH="$FIXTURE_1/bin:$PATH" make deploy 2>&1)" || true
if [ ! -f "$DEPLOY_ROOT_1/src/old_file.py" ]; then
    pass "rsync --delete removes stale files from deploy"
else
    fail "rsync --delete removes stale files from deploy"
fi

# ---------------------------------------------------------------------------
echo ""
echo "Testing make/common_python.mk"
echo ""

# -- Test 6: common_python.mk provides default variables --------------------
FIXTURE_PY="$TMPDIR_BASE/test_python"
mkdir -p "$FIXTURE_PY"
cat > "$FIXTURE_PY/Makefile" << EOF
include $REPO_ROOT/make/common_python.mk

.PHONY: print-vars
print-vars:
	@echo "SRC_DIR=\$(SRC_DIR)"
	@echo "TEST_DIR=\$(TEST_DIR)"
	@echo "PYTHON_SYSTEM=\$(PYTHON_SYSTEM)"
	@echo "VENV=\$(VENV)"
EOF

output="$(cd "$FIXTURE_PY" && make print-vars 2>&1)"
if echo "$output" | grep -q "SRC_DIR=src" && echo "$output" | grep -q "TEST_DIR=tests"; then
    pass "common_python.mk provides default SRC_DIR and TEST_DIR"
else
    fail "common_python.mk provides default SRC_DIR and TEST_DIR"
fi

# -- Test 7: variables can be overridden before include ----------------------
FIXTURE_PY2="$TMPDIR_BASE/test_python_override"
mkdir -p "$FIXTURE_PY2"
cat > "$FIXTURE_PY2/Makefile" << EOF
SRC_DIR := lib
TEST_DIR := spec
include $REPO_ROOT/make/common_python.mk

.PHONY: print-vars
print-vars:
	@echo "SRC_DIR=\$(SRC_DIR)"
	@echo "TEST_DIR=\$(TEST_DIR)"
EOF

output="$(cd "$FIXTURE_PY2" && make print-vars 2>&1)"
if echo "$output" | grep -q "SRC_DIR=lib" && echo "$output" | grep -q "TEST_DIR=spec"; then
    pass "variables can be overridden before include"
else
    fail "variables can be overridden before include"
fi

# ---------------------------------------------------------------------------
echo ""
echo "Testing make/common_service.mk"
echo ""

# -- Test 8: common_service.mk defines all expected targets ------------------
FIXTURE_SVC="$TMPDIR_BASE/test_service"
mkdir -p "$FIXTURE_SVC"
cat > "$FIXTURE_SVC/Makefile" << EOF
SERVICE_NAME := test-svc
include $REPO_ROOT/make/common_service.mk
EOF

targets="$(cd "$FIXTURE_SVC" && make -pn 2>/dev/null | grep -E '^[a-z].*:' | cut -d: -f1 | sort -u)"
expected_targets="install-service uninstall-service start stop restart status logs service-start service-stop service-restart service-status service-logs service-logs-static"
all_found=true
for t in $expected_targets; do
    if ! echo "$targets" | grep -qw "$t"; then
        all_found=false
        break
    fi
done
if $all_found; then
    pass "common_service.mk defines all expected targets"
else
    fail "common_service.mk defines all expected targets"
fi

# ---------------------------------------------------------------------------
echo ""
echo "Testing Makefile include paths"
echo ""

# -- Test 9: all component Makefiles parse without errors --------------------
all_parse=true
for dir in \
    agents/orpheus-agent-audio-motion \
    agents/orpheus-agent-audio-playback \
    agents/orpheus-agent-bird-detection \
    agents/orpheus-agent-crow-detection \
    agents/orpheus-agent-event-correlator \
    agents/orpheus-agent-video-motion \
    agents/orpheus-agent-video-snapshotter \
    agents/orpheus-agent-video-timelapser \
    services/orpheus-dashboard \
    services/orpheus-gps \
    services/orpheus_ui \
    services/orpheus_ui/backend; do
    if ! make -C "$REPO_ROOT/$dir" -n help >/dev/null 2>&1; then
        fail "Makefile parses: $dir"
        all_parse=false
    fi
done
if $all_parse; then
    pass "all 12 component Makefiles parse without errors"
fi

# -- Test 10: all component Makefiles have deploy target ---------------------
all_have_deploy=true
for dir in \
    agents/orpheus-agent-audio-motion \
    agents/orpheus-agent-audio-playback \
    agents/orpheus-agent-bird-detection \
    agents/orpheus-agent-crow-detection \
    agents/orpheus-agent-event-correlator \
    agents/orpheus-agent-video-motion \
    agents/orpheus-agent-video-snapshotter \
    agents/orpheus-agent-video-timelapser \
    services/orpheus-dashboard \
    services/orpheus-gps \
    services/orpheus_ui; do
    if ! make -C "$REPO_ROOT/$dir" -n deploy >/dev/null 2>&1; then
        fail "deploy target exists: $dir"
        all_have_deploy=false
    fi
done
if $all_have_deploy; then
    pass "all 11 deployable Makefiles have deploy target"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
TOTAL=$((PASS + FAIL))
echo "Results: $PASS/$TOTAL passed"
if [ $FAIL -gt 0 ]; then
    echo "FAILED"
    exit 1
else
    echo "ALL PASSED"
    exit 0
fi
