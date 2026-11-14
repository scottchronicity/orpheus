# Runbook — full laptop verification (before any Jetson deploy)

Run this on the Mac after pulling a big branch (or before merging one). It catches
the overwhelming majority of bugs cheaply: all logic, config parsing, DB/schema
behavior, UI backend+frontend, the container collective, and the real-model
cascade. What it CANNOT catch (Jetson-only): ALSA capture, real cameras/RTSP,
ARM64 wheels, CUDA paths, systemd unit behavior, thermal/load. Those are what the
[Jetson rollout runbook](jetson-rollout.md) soak covers.

Estimated time: ~10 min for gates, +10–20 min for the container/fleet passes.

## 1. Fast gates (always)

```bash
git fetch origin && git status          # clean tree, expected branch
make dev-stack SVC=backplane            # start NATS first — without a live broker the
                                        # JetStream integration tests in orpheus-common
                                        # self-skip (~17 tests), silently un-testing the
                                        # transport layer this pass exists to verify
make lint                               # every component, ruff + eslint
make -C services/orpheus-backplane test  # test-all skips the backplane and
                                         # audio-output; run them yourself
make test-all                           # every component's suite (continues on error,
                                        # exits red at the end if any suite failed)
make test-bash                          # bats shell-script tests
make test-bdd                           # correlator BDD oracle (in-process, fast)
make guardrails                         # agent wiring / manifest catalog / docs nav / rule count
make docs-build                         # docs site builds strict
```

If GPS or the event correlator was installed into a custom virtualenv directory,
pass that directory to the root aggregate targets (for example,
`make lint GPS_VENV=venv-uv312 CORRELATOR_VENV=venv-uv312`). Each override is
scoped to its component; it does not redirect every component to one runtime.

Everything must be green. Known local-env exception: `orpheus-agent-bird-detection`'s
local venv may be broken (cross-repo editable + dead dylib — see 99-gotchas); its
suite runs in CI. If anything ELSE is red, stop and fix before proceeding.

### macOS audio boundary

The playback agent can use macOS CoreAudio through `afplay`; it does not need
PulseAudio, ALSA, Bluetooth tools, systemd, or CUDA. The playback command is an
agent setting. For a laptop run, select the native backend without editing the
shared deployment YAML:

```bash
ORPHEUS_AUDIO__PLAYBACK_COMMAND=afplay make -C agents/orpheus-agent-audio-playback run
```

That starts the agent and waits for requests on the configured event bus. It
does not play a sound by itself. The managed `orpheus-audio-output` service is a
Linux systemd service for the Jetson's Bluetooth/PulseAudio path; keep
`audio_output.enabled: false` on a Mac. The playback agent can still run
independently through CoreAudio. `afplay` supports ordinary file playback;
segment extraction and volume overrides remain `ffplay` capabilities.

The laptop can validate the real CoreAudio process path without an audible test
using the `native-silent-smoke` target. It synthesizes a short silent WAV in a
temporary directory and sends it through Orpheus's configured playback code:

```bash
make -C agents/orpheus-agent-audio-playback native-silent-smoke
```

This exercises the local audio backend, but does not verify speaker loudness,
Bluetooth routing, or acoustic capture. Unit tests use a controlled player and
produce no sound. For bus-level integration, run the event-correlator e2e suite
against a local, isolated NATS server (never a station broker):

```bash
nats-server -js -a 127.0.0.1 -p 45222 \
  -sd "$(mktemp -d /tmp/orpheus-e2e.XXXXXX)"  # stop with Ctrl-C after the test
# In another terminal, while that local server is running:
ORPHEUS_TEST_NATS_URL=nats://127.0.0.1:45222 \
  make -C agents/orpheus-agent-event-correlator test-e2e VENV=venv-uv312
```

The e2e playback agent uses a controlled, non-audible player. It publishes the
same `started`/`finished` actuation protocol as normal playback, and the real
correlator receives those events and the detection events over NATS, publishes
entities, and persists them in a temporary SQLite database. The `started` and
`finished` events share `playback_id` and `start_time`; finish duration is
measured from monotonic elapsed time. Interruption still publishes a measured
`finished` event, while a backend that fails before start has no actuation
window. Corollary discharge is disabled by default and only subscribes when
explicitly enabled. Overlapping wildlife is tagged and retained; unrelated
detections remain published and untagged.

The service-owned output manager, Bluetooth connection recovery, PulseAudio
capture isolation, systemd startup, ALSA capture, and CUDA are Linux/Jetson
capabilities. The Bluetooth/PulseAudio behavior was hardware-validated on the
Jetson; the macOS smoke and local-broker suite do not repeat that validation.

## 2. Deploy-health dry run

```bash
make verify-deploy
```

Expect ✅ per component venv import (bird ❌ acceptable per above), systemd checks
skipped (macOS), broker probe skipped (no deployed config on a laptop), models
check informational. (On a deployed box the same target smokes the `/opt/orpheus`
venvs systemd actually runs and probes the configured event-bus broker.)

## 3. The container collective (Simulacrum)

```bash
make dev-stop SVC=backplane # free the test broker ports before starting the isolated
                            # Simulacrum backplane (bound to host loopback only)
make sim-up                 # backplane + correlator + synthetic source (demo profile)
make sim-status             # services Up (healthy)
make sim-logs               # watch: correlator consuming detections, EntityEvents publishing
make sim-down
```

Then the REAL-model pass (models must exist in `artifacts/models/`):

```bash
SIM_MODE=replay make sim-up      # replays artifacts/audio-samples clips as audio.motion
make sim-fleet-up                # bird/crow/audio-events with real models + the UI
make sim-validate                # asserts the real-audio cascade lands an EntityEvent
make sim-down
```

`make sim-validate` checks the Docker Compose project, broker image, loopback-only
port bindings, and NATS server identity before it publishes test events. If a
production or unrelated broker owns the host endpoint, validation stops before
the mutating test suite runs.

This is the strongest laptop signal there is: real clips → real BirdNET/PANNs →
correlator → entities, in containers.

## 4. UI walkthrough (manual, ~5 min)

```bash
make run-ui                      # backend on :8082; or `make dev-stack` for the full stack
# Ctrl-C this UI before §5 — it holds :8082 and the default (empty) data root.
```

- Dashboard loads; health cards populate; no console errors.
- Diagnostics page: bird/audio-events history charts render; presence panel shows
  the muted "not available" note (expected without nats+presence on).
- Entities/Birds/Crows pages: filters work; a killed backend shows an error state,
  not silently-blank charts (the fetchJson behavior).
- Weather card: hidden (expected without a station configured).

## 5. Migration check — run the new code against the laptop's existing DB

The fast gates and sim run against fresh databases. If this laptop has a DB from a
previous run (`$ORPHEUS_DATA_ROOT/detections/orpheus.db`), just run the new code
against it — the schema migration happens on first open, so this exercises the
upgrade path on a real, already-populated DB without copying anything from the
Jetson (the two machines are independent).

```bash
# Point the check at the laptop's data root — bare `make verify-deploy` defaults to
# /data/orpheus (the Jetson layout) and silently SKIPS the data-read smoke on a Mac.
ORPHEUS_DATA_ROOT=$HOME/data/orpheus make verify-deploy
                        # data-read smoke: detections/entities counts, proves the migrated DB reads

# Same prefix here, or the dashboard opens a different (empty) database and you
# will be looking at a blank page at the exact step meant to prove the reads.
# Stop the §4 UI first, or you will be reading its (empty) database:
#   lsof -ti:8082 | xargs kill
ORPHEUS_DATA_ROOT=$HOME/data/orpheus make run-ui &
# ...and when you are done: lsof -ti:8082 | xargs kill
```

Green means the migration is clean on a populated DB. (No prior DB on this laptop?
Skip it — the migration itself is covered by the orpheus-common regression test
that opens a pre-`root_event_id` database; this step is just a real-data spot check.)

## 6. Sign-off

All of the above green ⇒ the branch is laptop-verified. Record the result in the PR
(gates + sim + e2e cascade). The Jetson is a separate machine with its own data —
its backup, shutdown, deploy, and soak are the [Jetson rollout runbook](jetson-rollout.md)
/ [one-page checklist](jetson-upgrade-checklist.md), not this laptop pass.
