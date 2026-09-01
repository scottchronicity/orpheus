#!/usr/bin/env bats
# scripts/bump-version.sh — SemVer bump + CHANGELOG stub (docs/adr/0014).
#
# Every test runs a sandbox COPY of the script against fixture components
# under BATS_TEST_TMPDIR (see make_bump_sandbox in test_helper.bash), so the
# real repo's VERSION / CHANGELOG files are never mutated.

load 'test_helper'

setup() {
  make_bump_sandbox
}

# --- argument validation ----------------------------------------------------

@test "no arguments: exits 2 with usage" {
  run "$BUMP"
  assert_failure 2
  assert_output --partial "Usage:"
}

@test "one argument: exits 2 with usage" {
  run "$BUMP" platform/orpheus-common
  assert_failure 2
  assert_output --partial "Usage:"
}

@test "three arguments: exits 2 with usage" {
  run "$BUMP" platform/orpheus-common patch extra
  assert_failure 2
  assert_output --partial "Usage:"
}

@test "invalid bump part: exits 2, names the bad part, leaves VERSION alone" {
  add_component agents/demo 1.2.3
  run "$BUMP" agents/demo banana
  assert_failure 2
  assert_output --partial "must be major, minor, or patch (got 'banana')"
  assert_equal "$(cat "$SANDBOX_REPO/agents/demo/VERSION")" "1.2.3"
}

# --- VERSION file validation ------------------------------------------------

@test "missing VERSION file: exits 1 and names the expected path" {
  run "$BUMP" agents/no-such-component patch
  assert_failure 1
  assert_output --partial "no VERSION file"
  assert_output --partial "agents/no-such-component/VERSION"
}

@test "non-SemVer VERSION (v-prefix): exits 1, file untouched" {
  add_component agents/demo v1.2.3
  run "$BUMP" agents/demo patch
  assert_failure 1
  assert_output --partial "not strict SemVer"
  assert_equal "$(cat "$SANDBOX_REPO/agents/demo/VERSION")" "v1.2.3"
}

@test "non-SemVer VERSION (pre-release suffix): exits 1" {
  add_component agents/demo 1.2.3-rc1
  run "$BUMP" agents/demo patch
  assert_failure 1
  assert_output --partial "not strict SemVer"
}

# --- happy paths: the three bump parts ---------------------------------------

@test "patch bump: 1.2.3 -> 1.2.4" {
  add_component agents/demo 1.2.3
  run "$BUMP" agents/demo patch
  assert_success
  assert_output --partial "Bumped agents/demo: 1.2.3 -> 1.2.4 (patch)"
  assert_equal "$(cat "$SANDBOX_REPO/agents/demo/VERSION")" "1.2.4"
}

@test "minor bump resets patch: 1.2.3 -> 1.3.0" {
  add_component agents/demo 1.2.3
  run "$BUMP" agents/demo minor
  assert_success
  assert_output --partial "Bumped agents/demo: 1.2.3 -> 1.3.0 (minor)"
  assert_equal "$(cat "$SANDBOX_REPO/agents/demo/VERSION")" "1.3.0"
}

@test "major bump resets minor and patch: 1.2.3 -> 2.0.0" {
  add_component agents/demo 1.2.3
  run "$BUMP" agents/demo major
  assert_success
  assert_output --partial "Bumped agents/demo: 1.2.3 -> 2.0.0 (major)"
  assert_equal "$(cat "$SANDBOX_REPO/agents/demo/VERSION")" "2.0.0"
}

@test "multi-digit components bump numerically: 9.10.19 patch -> 9.10.20" {
  add_component agents/demo 9.10.19
  run "$BUMP" agents/demo patch
  assert_success
  assert_equal "$(cat "$SANDBOX_REPO/agents/demo/VERSION")" "9.10.20"
}

@test "VERSION with surrounding whitespace still parses" {
  mkdir -p "$SANDBOX_REPO/agents/demo"
  printf '  1.2.3\n\n' > "$SANDBOX_REPO/agents/demo/VERSION"
  run "$BUMP" agents/demo patch
  assert_success
  assert_equal "$(cat "$SANDBOX_REPO/agents/demo/VERSION")" "1.2.4"
}

@test "VERSION is rewritten as a POSIX text file (single line + trailing newline)" {
  add_component agents/demo 0.1.0
  run "$BUMP" agents/demo patch
  assert_success
  # printf-x sentinel: command substitution strips trailing newlines, the x
  # preserves them so we can assert the file is exactly "0.1.1\n".
  assert_equal "$(cat "$SANDBOX_REPO/agents/demo/VERSION"; printf x)" "$(printf '0.1.1\nx')"
}

# --- CHANGELOG stub -----------------------------------------------------------

@test "creates CHANGELOG.md with a dated stub when missing" {
  add_component agents/demo 0.1.0
  run "$BUMP" agents/demo minor
  assert_success
  local changelog="$SANDBOX_REPO/agents/demo/CHANGELOG.md"
  assert [ -f "$changelog" ]
  run cat "$changelog"
  assert_line --index 0 "# Changelog"
  assert_output --partial "## 0.2.0 — $(date +%Y-%m-%d)"
  assert_output --partial "_Describe the change here._"
}

@test "prepends the stub to an existing CHANGELOG (header kept, old entries below)" {
  add_component agents/demo 1.0.0
  local changelog="$SANDBOX_REPO/agents/demo/CHANGELOG.md"
  printf '# Changelog\n\n## 1.0.0 — 2026-01-01\n\n- old entry\n' > "$changelog"
  run "$BUMP" agents/demo patch
  assert_success
  run cat "$changelog"
  assert_line --index 0 "# Changelog"
  assert_output --partial "## 1.0.1 — $(date +%Y-%m-%d)"
  assert_output --partial "- old entry"
  # The new entry must land ABOVE the old one (prepend, not append).
  local new_at old_at
  new_at="$(grep -n '^## 1\.0\.1' "$changelog" | cut -d: -f1)"
  old_at="$(grep -n '^## 1\.0\.0' "$changelog" | cut -d: -f1)"
  assert [ "$new_at" -lt "$old_at" ]
}

@test "success output points at both files it wrote" {
  add_component agents/demo 2.5.9
  run "$BUMP" agents/demo patch
  assert_success
  assert_output --partial "VERSION:   $SANDBOX_REPO/agents/demo/VERSION"
  assert_output --partial "CHANGELOG: $SANDBOX_REPO/agents/demo/CHANGELOG.md"
}
