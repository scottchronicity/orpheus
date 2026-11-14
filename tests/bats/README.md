# Bash script tests (bats-core)

[bats-core](https://github.com/bats-core/bats-core) suites for the repo's
shell scripts. One `.bats` file per script (or logical group); shared
fixtures/sandbox helpers live in `test_helper.bash`.

## Running

```bash
make test-bash
```

First run bootstraps bats-core + bats-support + bats-assert (pinned release
tags, shallow clones) into the gitignored `tests/bats/lib/` — a deliberate
deviation from git submodules to avoid clone friction; see the `test-bash`
target in the root Makefile. Later runs skip the bootstrap. Reset with
`rm -rf tests/bats/lib`.

## What's tested

- **`audio-output-lifecycle.bats`**, **`audio-output-install.bats`** — the
  audio output installer and rollback (`services/orpheus-audio-output/systemd/`):
  - the individual host steps: lingering; masking the audio user's stock
    PulseAudio units and verifying them through its systemd manager; retiring
    `orpheus-bluetooth-autoconnect` and units connecting the same speaker;
  - the full install script: preflight changes nothing, and a failed install
    restores the previous installation and each unit's enabled/running state;
  - rollback.

  Both run against a sandbox root built by `audio_output_helper.bash`.
- **`bump-version.bats`** — `scripts/bump-version.sh`: patch/minor/patch
  SemVer bumps, argument + VERSION-file validation, and the CHANGELOG stub
  (create + prepend). Tests run a sandbox copy under `BATS_TEST_TMPDIR`;
  the real repo's VERSION/CHANGELOG files are never touched.

Deliberately **not** covered: `docker/sim-distributed-validate.sh` — it is
pure docker-compose side-effects end to end (its first statements set an
EXIT trap that runs `docker compose down` and call `$COMPOSE config`), with
no arg parsing or pure logic to test without a docker daemon. It is
exercised for real by `make sim-distributed-validate`.

## Conventions

- Sandbox everything: copy the script under test into `BATS_TEST_TMPDIR`
  (see `make_bump_sandbox`) so tests can never mutate real repo files.
- Scripts under test must stay macOS bash 3.2-compatible; bats-core brings
  its own bash for the tests themselves.
