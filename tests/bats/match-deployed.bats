#!/usr/bin/env bats
# scripts/match-deployed.py — find the commit a deploy tree matches, and
# whether deploying REV would revert it. Uses a throwaway Git repository and
# deploy prefix; nothing outside BATS_TEST_TMPDIR is read or written.

load 'test_helper'

TOOL="$REPO_ROOT/scripts/match-deployed.py"

setup() {
  SB="$BATS_TEST_TMPDIR"
  R="$SB/repo"
  P="$SB/opt"
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.invalid GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.invalid
  export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
  git init -q "$R"   # no -b: Git 2.25 (Ubuntu 20.04 / JetPack 5) predates it
  git -C "$R" symbolic-ref HEAD refs/heads/main
  mkdir -p "$R/agents/orpheus-agent-x/src/x" "$R/platform/orpheus-common/src/c"
  echo "v = 1" > "$R/agents/orpheus-agent-x/src/x/__init__.py"
  echo "c = 1" > "$R/platform/orpheus-common/src/c/__init__.py"
  echo "static/" > "$R/platform/orpheus-common/.gitignore"
  git -C "$R" add -A && git -C "$R" commit -q -m "base"
  git -C "$R" checkout -q -b production
  echo "v = 2  # local-only fix" > "$R/agents/orpheus-agent-x/src/x/__init__.py"
  git -C "$R" commit -q -am "local-only fix"
  git -C "$R" checkout -q main
  echo "c = 2" > "$R/platform/orpheus-common/src/c/__init__.py"
  git -C "$R" commit -q -am "release work"
  # Deployed: the production fix for x, the base for common, plus build output.
  mkdir -p "$P/agents/orpheus-agent-x/src/x" "$P/platform/orpheus-common/src/c/__pycache__" "$P/platform/orpheus-common/src/static"
  git -C "$R" show production:agents/orpheus-agent-x/src/x/__init__.py > "$P/agents/orpheus-agent-x/src/x/__init__.py"
  git -C "$R" show main~1:platform/orpheus-common/src/c/__init__.py > "$P/platform/orpheus-common/src/c/__init__.py"
  echo junk > "$P/platform/orpheus-common/src/c/__pycache__/__init__.cpython-39.pyc"
  echo built > "$P/platform/orpheus-common/src/static/app.js"
}

match() { run python3 "$TOOL" --repo "$R" --prefix "$P" "$@"; }

@test "names the commits each component matches, ignoring caches and gitignored build output" {
  match
  assert_success
  assert_output --partial "✅ agents/orpheus-agent-x/src: matches 1 commit(s): $(git -C "$R" rev-parse --short production) "
  assert_output --partial "✅ platform/orpheus-common/src: matches"
}

@test "deploying a branch without the local-only commit is flagged as a revert" {
  match --against main
  assert_failure
  assert_output --partial "❌ agents/orpheus-agent-x/src: deployed code matches"
  assert_output --partial "which main does not contain; deploying it would revert those changes"
  assert_output --partial "✅ platform/orpheus-common/src: main contains the deployed code"
}

@test "a branch that merged the local-only commit keeps everything" {
  git -C "$R" checkout -q -b reconciled main
  git -C "$R" merge -q --no-edit production
  match --against reconciled
  assert_success
  refute_output --partial "❌"
}

@test "an edited deployed file has no exact match and is named" {
  echo "hotfix = True" >> "$P/agents/orpheus-agent-x/src/x/__init__.py"
  match
  assert_failure
  assert_output --partial "❌ agents/orpheus-agent-x/src: no exact match; closest differs in 1 file(s): x/__init__.py"
}

@test "an unknown revision is an error, not a pass" {
  match --against no-such-branch
  [ "$status" -eq 2 ]
  assert_output --partial "is not a commit"
}

@test "an unreadable component is reported, not skipped" {
  [ "$(id -u)" -ne 0 ] || skip "root can read anything"
  mkdir -p "$P/services/orpheus-y/src"
  chmod 000 "$P/services/orpheus-y"
  match
  chmod 755 "$P/services/orpheus-y"
  assert_failure
  assert_output --partial "orpheus-y is not readable as this user; rerun with sudo"
}
