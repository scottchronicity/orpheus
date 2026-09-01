#!/usr/bin/env bash
# Shared helpers for the bats suites in tests/bats/*.bats.
#
# Loaded from each .bats file with `load 'test_helper'`. Pulls in the
# bats-support + bats-assert libraries that `make test-bash` bootstraps into
# tests/bats/lib/ (pinned shallow clones — see the test-bash target for why
# they are not git submodules), and provides the sandbox helpers the suites
# use to exercise real scripts without mutating real repo files.
#
# Works with the macOS-bundled bash 3.2 (no associative arrays, no mapfile);
# bats-core itself supplies the bash that actually runs the tests.

# Absolute paths, derived from this file, so the suites run from any cwd.
BATS_HELPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$BATS_HELPER_DIR/../.." && pwd)"
export REPO_ROOT

# Fail with a pointer to the bootstrap instead of a cryptic "load" error when
# someone runs bats directly before the libraries exist.
if [ ! -f "$BATS_HELPER_DIR/lib/bats-support/load.bash" ] \
   || [ ! -f "$BATS_HELPER_DIR/lib/bats-assert/load.bash" ]; then
  echo "bats-support / bats-assert not found under tests/bats/lib/." >&2
  echo "Run 'make test-bash' — it bootstraps them (pinned shallow clones)." >&2
  return 1
fi

load "$BATS_HELPER_DIR/lib/bats-support/load"
load "$BATS_HELPER_DIR/lib/bats-assert/load"

# make_bump_sandbox — copy scripts/bump-version.sh into a throwaway "repo"
# under this test's private tmpdir. The script derives repo_root from its own
# location (dirname "$0"/..), so running the copy confines every VERSION /
# CHANGELOG write to the sandbox — the real repo's files are never touched.
# Sets: SANDBOX_REPO (the fake repo root) and BUMP (the script copy to run).
make_bump_sandbox() {
  SANDBOX_REPO="$BATS_TEST_TMPDIR/repo"
  mkdir -p "$SANDBOX_REPO/scripts"
  cp "$REPO_ROOT/scripts/bump-version.sh" "$SANDBOX_REPO/scripts/bump-version.sh"
  chmod +x "$SANDBOX_REPO/scripts/bump-version.sh"
  BUMP="$SANDBOX_REPO/scripts/bump-version.sh"
}

# add_component <path> <version> — create a component dir with a VERSION file
# inside the sandbox (mirrors e.g. platform/orpheus-common/VERSION).
add_component() {
  mkdir -p "$SANDBOX_REPO/$1"
  printf '%s\n' "$2" > "$SANDBOX_REPO/$1/VERSION"
}
