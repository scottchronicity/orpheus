#!/usr/bin/env bats
# workers/orpheus-worker-panns/requirements_hashed.py: the worker venv installs
# with pip --require-hashes, every pin carrying the tested wheels' SHA-256.

load 'test_helper'

WORKER="$REPO_ROOT/workers/orpheus-worker-panns"
TOOL="$WORKER/requirements_hashed.py"

@test "every constraint pin gets its recorded hashes, and torch is the local NVIDIA wheel" {
  run python3 "$TOOL" /wheels/torch-nv.whl
  assert_success
  pins=$(grep -cE '^[^#[:space:]][^#]*==' "$WORKER/constraints.txt")
  [ "$(printf '%s\n' "$output" | wc -l)" -eq "$pins" ]
  ! printf '%s\n' "$output" | grep -v -- '--hash=sha256:[0-9a-f]\{64\}'
  printf '%s\n' "$output" | grep -qx -- '/wheels/torch-nv.whl --hash=sha256:5112e2ef5051f1003ae2ffb545ae596377df66979d62a954d774f18009064dbe'
  # numpy is listed twice in wheels.sha256; it gets its one hash once.
  [ "$(printf '%s\n' "$output" | grep -E '^numpy==' | grep -o -- '--hash=' | wc -l)" -eq 1 ]
}

@test "a pin with no recorded hash fails instead of installing unhashed" {
  cp "$TOOL" "$WORKER/constraints.txt" "$BATS_TEST_TMPDIR/"
  grep -v '^[0-9a-f]* *numpy-' "$WORKER/wheels.sha256" > "$BATS_TEST_TMPDIR/wheels.sha256"
  run python3 "$BATS_TEST_TMPDIR/requirements_hashed.py" /wheels/torch-nv.whl
  assert_failure
  assert_output --partial "no recorded wheel hash for numpy=="
}

@test "the worker install uses pip --require-hashes from the generated file" {
  grep -q -- 'requirements_hashed.py' "$WORKER/Makefile"
  grep -q -- '--require-hashes' "$WORKER/Makefile"
  ! grep -qE 'pip install -c constraints.txt' "$WORKER/Makefile"
}
