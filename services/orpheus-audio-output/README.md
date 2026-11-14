# orpheus-audio-output

Keeps Orpheus's audio output ready for `orpheus-agent-audio-playback`. The
output device is established, the audio server is running, and playback is
routed to the output. It replaces `orpheus-bluetooth-autoconnect`.

Operating it (configuration, install, health, rollback, troubleshooting) is in
the Operator's Manual: [Audio output](../../docs/operator-manual/audio-output.md).
This README is for changing it.

## Responsibilities and boundaries

| Part | Module | Owns | Implemented |
|---|---|---|---|
| Output device | `outputs.py` (`OutputDevice`) | Probing, establishing and describing the device (`Endpoint`), and the server capabilities it `requires` | `BluetoothOutput` (`bluetoothctl` in argument mode) |
| Audio server | `servers.py` (`AudioServer`) | Starting, checking, restarting and stopping the daemon; mapping an `Endpoint` to a sink; routing; capture-isolation checks; the `capabilities` it provides | `PulseAudioServer` |
| Lifecycle policy | `policy.py`, `manager.py` | Independent backoff per part, the order of each poll, throttled logs, health | `OutputManager` |
| Configuration | `config.py` | The `audio_output` section, legacy migration, validation | |

The playback agent keeps sound selection, player execution, response events and
corollary-discharge windows. This service publishes only its health
(`orpheus/audio/output/health`, plus `/run/orpheus-audio-output/health.json`).

An output and a server are separate choices. `build_server(config,
output.requires)` refuses a server whose `capabilities` lack what the output
needs, so an unsupported pair fails at startup with both settings named. There
is no combined backend, and no plugin registry. A new implementation is one
class plus one branch in `build_output` or `build_server`, plus its config
keys in `config.py`.

## How a poll runs (`OutputManager.tick`)

1. **Server.** Checked every poll while ready, and retried under its own
   backoff while not. `PulseAudioServer.ensure()` does three things:
   - adopts a PulseAudio already answering on the user's socket, and never
     stops it;
   - otherwise starts one as the configured user: `pulseaudio --daemonize=no
     -n -F <generated script>`, whose script loads `module-native-protocol-unix`
     plus, for Bluetooth outputs, `module-bluetooth-policy` and
     `module-bluetooth-discover`;
   - restarts it if it exits or stops answering.
2. **Capture isolation.** If the managed server holds an `/dev/snd/*` file
   descriptor or loads an ALSA, udev, OSS or JACK module, it is stopped and
   reported. Foreign PulseAudio processes holding sound devices are reported,
   not touched.
3. **Output.** Probed every poll and established under its own backoff. This is
   never gated on the server, because another user's audio server may provide
   the A2DP endpoint. Bluetooth keeps the field-proven sequence of the retired
   script: trust at startup; connect; on failure, scan for 10 s and connect
   once more.
4. **Routing.** Once the output is connected and the server ready, the
   output's sink becomes the default, and playing streams are moved to it.
   Routing is repeated whenever the default sink changes (for example, after a
   server restart). If the server restarted while the output stayed connected
   and no sink appears within `SINK_GRACE_POLLS`, `OutputDevice.reset()` drops
   the link once so the output renegotiates with the new server (Bluetooth:
   `bluetoothctl disconnect`). A sink missing without a restart is only
   reported, so the service never takes an endpoint from another user's
   server.

`pactl` always runs as the server's user with `PULSE_SERVER` set explicitly,
so a client never autospawns a stock PulseAudio. Every external command runs
with stdin at `/dev/null` and a hard timeout.

## Host lifecycle (`systemd/`)

`install-service.sh` has two phases.

**Preflight** changes nothing on the host. It builds the code and a venv in
`<deploy>.stage.*`, with non-editable installs so the venv can be renamed into
place. `relocate_venv` rewrites the staging path in the venv's generated
scripts (`pip`, entry points, `activate`), and after the rename `verify_venv`
and `pip --version` confirm every script still runs. Preflight then runs
`main check` and checks the audio user, tools, PulseAudio
modules and mask paths.

**The transaction** runs under an `ERR` trap. It swaps the deployment and then
runs the steps in `lifecycle.sh`:
- mask the user's stock PulseAudio units;
- enable lingering;
- reload the user's systemd manager and verify the masks (`LoadState=masked`,
  socket inactive). The manager must be running; if it does not start, the
  install fails;
- stop a stock instance;
- retire the old unit;
- disable competing units.

It then starts the service, and requires a ready server with capture
isolation intact within `HEALTH_WAIT_SECONDS`. If anything fails,
`restore_previous` reverses it all: the previous deployment and unit file come
back, this run's records (`changes.run`) are undone newest first, and every
unit returns to its recorded enabled/running state.

A successful run merges `changes.run` into `changes`, which
`uninstall-service.sh` and `make rollback` undo the same way. The unit runs as
root, because of BlueZ and starting the server as its user, and the managed
PulseAudio lives in the unit's cgroup.

## Tests

```bash
make install   # local venv
make test      # isolated: no Bluetooth, PulseAudio, broker or root needed
make lint
```

- `tests/test_config.py`: the YAML contract, legacy migration and precedence,
  environment overrides through `OrpheusConfig`, clear failures for
  unsupported or invalid settings, and compatibility validation.
- `tests/test_bluetooth_output.py`: state classification and the connect, scan
  and retry sequence against a stateful BlueZ fake; also commands never
  reading stdin, and timeouts.
- `tests/test_pulseaudio_server.py`: the generated script loads no ALSA or udev
  module; capture-isolation detection on a fake `/proc`; and real-process
  lifecycle with stand-in `pulseaudio` and `pactl` executables (start, killed
  and restarted, adoption, startup failure, unresponsive, missing runtime
  directory), plus routing.
- `tests/test_manager.py`: cold start, a quiet steady state, speaker drop and
  reconnect, backoff timing to the ceiling, a BlueZ outage, server
  termination, a reboot, connects not gated on the server, isolation
  handling, `reconnect.enabled: false`, and log volume over a day-long
  outage.
- `tests/test_main.py`: `check`, disabled mode, and the run loop with health
  publishing and SIGTERM.
- `tests/bats/audio-output-lifecycle.bats` and `audio-output-install.bats`
  (repo root): the host steps, and the full install/uninstall scripts, run in
  a sandbox root with stateful `systemctl`/user-manager mocks. They cover:
  preflight changing nothing; restore after a failed start, a capture
  isolation failure, a dying unit or unverifiable masks; a failed update
  keeping the previous version; and rollback restoring each unit's
  enabled/running state.

These cover the logic, not the hardware. Real A2DP connection, sink naming on
a given speaker, and the capture agents keeping their devices are confirmed on
the station.
