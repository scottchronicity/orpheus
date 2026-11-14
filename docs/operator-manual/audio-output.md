# Audio output

This page covers getting Orpheus's sounds out of a speaker: the
`orpheus-audio-output` service, how to configure, install and roll it back, how
to read its health, and what to do when nothing plays. Choosing and playing
sounds (the request API, corollary-discharge windows) belongs to the
[audio playback agent](https://github.com/scottchronicity/orpheus/tree/main/agents/orpheus-agent-audio-playback).

## What the service does

`orpheus-audio-output` keeps the output ready for the playback agent. It
manages three things separately, each configured on its own:

- **The output device** (`output.type`). Today that is a Bluetooth speaker:
  it trusts the speaker at startup, connects it, and reconnects it when it
  drops.
- **The audio server** (`server.type`). Today that is PulseAudio, running as
  the playback agent's user at that user's usual socket
  (`/run/user/<uid>/pulse/native`). The service starts it, checks it, and
  restarts it if it stops.
- **The reconnect policy** (`reconnect`). Retries start at 10 s and double up
  to 60 s while something is down, then drop back as soon as it recovers.

Each poll it makes the speaker's sink PulseAudio's default and moves any
playing sound to it. If PulseAudio restarts while the speaker stays connected
and the new server gets no sink for it, the service reconnects the speaker
once so it renegotiates with the new server.

**The managed PulseAudio never touches the recording interface.** It loads
only the native-protocol and Bluetooth modules, and no ALSA or udev module, so
it never opens `/dev/snd`. The service checks this every poll: if the server it
runs ever holds an ALSA device or loads an ALSA module, it stops that server
and reports `unhealthy`. If it finds another PulseAudio holding ALSA devices,
such as a desktop session's, it reports that too.

If a PulseAudio is already running for the configured user, the service uses
it instead of starting another, and never stops it. The speaker connection is
never made to wait for any one user's PulseAudio, because the A2DP endpoint can
come from another user's audio server.

## Configure

Settings live under `audio_output` in `orpheus.yaml`. Environment overrides
use the usual form, for example
`ORPHEUS_AUDIO_OUTPUT__OUTPUT__BLUETOOTH__ADDRESS`.

```yaml
audio_output:
  enabled: true
  output:
    type: bluetooth
    bluetooth:
      address: "FC:58:FA:02:AF:28"   # the paired speaker
  server:
    type: pulseaudio
    pulseaudio:
      user: orpheus                  # the playback agent's user
  reconnect:
    enabled: true
    initial_delay_seconds: 10        # poll interval and first retry delay
    max_delay_seconds: 60            # retry ceiling
```

| Setting | Default | Meaning |
|---|---|---|
| `enabled` | `true` when the section exists | `false` installs the service but leaves it stopped. |
| `output.type` | `bluetooth` | The only output implemented so far. Anything else is rejected at startup. |
| `output.bluetooth.address` | — | Required. The speaker must already be paired (see below). |
| `server.type` | `pulseaudio` | The only server implemented so far. |
| `server.pulseaudio.user` | `orpheus` | Must be the user the playback agent runs as, or playback will not reach this server. |
| `reconnect.enabled` | `true` | `false` makes one attempt at startup and then only reports. |
| `reconnect.initial_delay_seconds` | `10` | How often the service polls, and the first retry delay. |
| `reconnect.max_delay_seconds` | `60` | The longest wait between retries. |

Check a configuration without changing anything:
`make -C services/orpheus-audio-output check-config`. An unknown key, an
unsupported type or an invalid address is reported by name. The running
service exits with code 78 on one and is not restarted.

### Self-playback tagging

The playback agent publishes a `started` event on
`orpheus/actuation/audio/playback` once the player reports that output has
started, followed by a `finished` event with the measured elapsed duration.
Both carry the same `playback_id`, `start_time`, source and sound identity. The
event correlator subscribes only when `corollary_discharge.enabled` is true
(default `false`). Its `buffer_seconds` pads the end of playback, and
`max_playback_seconds` bounds a start whose finish event is lost (default
300 seconds).

Corollary discharge tags an overlapping entity as self-generated; it does not
delete detections or evidence. A real animal heard while the speaker is active
remains in the database and in the entity's evidence. These playback events use
the configured event bus and are not a durable work queue, so a broker or agent
restart can still lose the tag. See the [corollary discharge settings](index.md#2-configuration)
and the [playback agent guide](https://github.com/scottchronicity/orpheus/tree/main/agents/orpheus-agent-audio-playback)
for request formats.

**Coming from `orpheus-bluetooth-autoconnect`:** you don't need to change
anything. While `orpheus.yaml` has no `audio_output` section, the service reads
`BLUETOOTH_SPEAKER_MAC` and `AUDIO_USER` from the old
`/etc/orpheus/bluetooth-autoconnect/config.env`, and logs that it is doing so.
Copy those values into `orpheus.yaml` when convenient. Keys set in
`orpheus.yaml` always win over the old file.

## Install, update, roll back

```bash
make -C services/orpheus-audio-output install-service   # sudo; also the update path
make -C services/orpheus-audio-output health            # latest health snapshot
make -C services/orpheus-audio-output rollback          # back to orpheus-bluetooth-autoconnect
```

`make services-install` and `make update-all` include the service.

**Preflight changes nothing on the host.** The installer builds the new code
and its venv in a staging directory next to the deployment, then checks:
- the configuration;
- the audio user;
- the tools (`bluetoothctl`, `pulseaudio`, `pactl`, `loginctl`, `runuser`);
- the PulseAudio modules (`module-bluetooth-discover`,
  `module-bluetooth-policy`, `module-native-protocol-unix`);
- that no real unit file sits where a mask must go.

Any problem stops it here, with "nothing on this host was changed".

Then, as one transaction:

1. **Swaps in the staged deployment,** keeping the previous one and its unit
   file aside. The staged venv's scripts, such as `pip`, are rewritten for the
   final path before the swap and checked after it.
2. **Masks the PulseAudio user's stock `pulseaudio.socket` and
   `pulseaudio.service`.** Stock PulseAudio loads `module-udev-detect` and takes
   the USB capture interface; the audio-motion setup already masks the service.
   It then **enables lingering** for that user, so `/run/user/<uid>`, where the
   socket lives, exists from boot whether or not anyone is logged in.
3. **Reloads that user's systemd manager,** which lingering starts, and stops
   its `pulseaudio.socket` if it was listening. It then **verifies** that the
   manager reports both units `masked` and the socket inactive, so a stock
   PulseAudio cannot be socket-activated. If the manager does not start, the
   masks cannot be verified and the install fails. A stock PulseAudio already
   running for the user is stopped.
4. **Retires `orpheus-bluetooth-autoconnect`,** keeping a backup of its unit
   and script, and disables any other unit that runs `bluetoothctl connect`
   for the same speaker, such as an early hand-made
   `bluetooth-speaker-connect.service`. For each, it records whether it was
   enabled and whether it was running.
5. **Routes the playback agent to the managed server** with the drop-in
   `orpheus-agent-audio-playback.service.d/50-orpheus-audio-output.conf`
   (`PULSE_SERVER`, `XDG_RUNTIME_DIR`, and `SDL_AUDIODRIVER=pulseaudio`, so the
   player fails rather than falling back to ALSA). It restarts the agent if it
   is running. Preflight already checked that the agent runs as the PulseAudio
   user.
6. **Starts the service.** Within 60 s it must report a ready audio server
   with capture isolation intact.

If any step fails, including step 6, the installer stops the new service,
puts back the previous deployment and unit file, undoes this run's host
changes, and returns every service it touched to the enabled and running
state it had before. An update that fails leaves the previous version running.

Every host change from a successful install is recorded in
`/var/lib/orpheus-audio-output/changes`. `make rollback` undoes exactly those
changes (lingering, masks, units, the playback drop-in) and puts `orpheus-bluetooth-autoconnect`
back. Each service ends up enabled and running only if it was before the
install. `make uninstall-service` does the same but leaves the old service
retired, still restorable with `make rollback`. A stock PulseAudio the
installer stopped is not restarted, because it would take the capture
interface again. Settings files are never deleted.

Pairing is not automatic. Pair a new speaker once by hand, with the speaker in
pairing mode:

```bash
bluetoothctl     # then: power on, agent on, scan on, pair XX:..., trust XX:..., quit
```

## Check on it

```bash
make -C services/orpheus-audio-output health
sudo journalctl -u orpheus-audio-output -n 50 --no-pager
```

The health snapshot is also published on `orpheus/audio/output/health` every
30 s, and whenever its status changes:

| Field | Meaning |
|---|---|
| `status` | `healthy` (routed to the speaker), `degraded` (server up, speaker not ready), `unhealthy` (server failing, or capture isolation at risk), `disabled`, `stopped` |
| `output.state` | `connected`, `disconnected`, `unpaired`, `missing`, `no_controller`, `unavailable` (BlueZ did not answer) |
| `server.state` / `server.managed` | `ready` / `failed` / `isolation_violation`; `true` if the service started this server, `false` if it is using one that was already running |
| `routing.state` | `routed`, `waiting_for_sink`, `route_failed`, `not_ready` |
| `capture_isolation.ok` | `false` if any PulseAudio holds an ALSA device or loads an ALSA module; `problems` and `other_audio_servers` say which |
| `counters` | speaker reconnects, server recoveries, routing changes, and speaker resets after a server restart, since start |

A healthy service logs nothing. It logs when a state changes, and repeats an
unchanged failure at most every 10 minutes.

## Troubleshooting

### Status `degraded`, output `disconnected`

The speaker is off, out of range or flat. The detail field carries BlueZ's
reason (for example `br-connection-page-timeout`). Switch it on and it connects
within a minute; `sudo systemctl restart orpheus-audio-output` retries at once.

### `bluetoothd` reports "Protocol not available"

`sudo journalctl -u bluetooth` shows `a2dp-sink profile connect failed ...:
Protocol not available` when no audio server has registered A2DP with BlueZ.
Check `server.state` in the health snapshot: if it is not `ready`, the journal
says why PulseAudio did not start.

### Output `missing` or `unpaired`

The pairing was lost (the speaker was reset, or paired to another host). Pair
it again as shown above. The service picks it up on its next poll.

### Status `unhealthy`, capture isolation not ok

Another PulseAudio has the recording interface open. `other_audio_servers`
names its process and user; it is usually a desktop session's PulseAudio.
Recording agents can then fail with "Device or resource busy". Stop that
session's PulseAudio. The service never starts one that does this.

### Sounds play from the wrong device, or not at all

Check that the playback drop-in is in place:
`systemctl cat orpheus-agent-audio-playback` should end with
`50-orpheus-audio-output.conf` and `PULSE_SERVER=unix:/run/user/<uid>/pulse/native`
for the PulseAudio user. While the speaker is connected, `pactl list short sinks`,
run as that user with that `PULSE_SERVER`, shows the speaker's sink as
`RUNNING` during a sound. While the speaker
is not routed, the playback agent reports each failed sound on
`orpheus/audio/playback/response` with `"status": "error"`.

### `bluetoothctl` is slow to start when run as root

Old versions of the autoconnect service grew root's
`/root/.cache/.bluetoothctl_history` to tens of megabytes. This service never
writes to it. The file holds only command history and is safe to delete:
`sudo rm /root/.cache/.bluetoothctl_history`.
