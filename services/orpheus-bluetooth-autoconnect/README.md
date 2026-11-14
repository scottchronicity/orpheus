# Orpheus Bluetooth Auto-Connect Service

Keeps one paired Bluetooth speaker connected to an Orpheus host and routes
PulseAudio output to it, so `orpheus-agent-audio-playback` can play through it.

Operating it — install, settings, log messages, and what to do when the
speaker never connects — is in the Operator's Manual:
[Bluetooth speaker](../../docs/operator-manual/bluetooth-speaker.md). This
README covers how the service is built and tested.

## Behaviour

`scripts/orpheus-bluetooth-connect.sh` is a supervision loop run by
`orpheus-bluetooth-autoconnect.service` as root. Each `poll_once`:

1. Reads the device state with `bluetoothctl info <MAC>`:
   `connected`, `disconnected`, `unpaired`, `missing` (unknown to BlueZ),
   `no_controller`, or `unavailable` (bluetoothd did not answer within
   `BT_COMMAND_TIMEOUT`).
2. **Connected:** if audio was not routed yet (or routing failed), retries
   routing; otherwise does nothing and logs nothing.
3. **Otherwise:** skips the attempt when there is no controller, BlueZ is
   unavailable, or (with `REQUIRE_AUDIO_SERVER=true`) the audio user has no
   PulseAudio socket. Without an audio server nothing offers an A2DP endpoint
   and bluetoothd fails every connect with `Protocol not available`. If it
   does not skip, it powers the controller on if needed, trusts the device if
   needed, and connects. The first failed connect of an outage (or one for a
   device BlueZ has lost) runs one `SCAN_SECONDS` discovery scan and retries.
4. **After connecting:** waits up to `SINK_WAIT_SECONDS` for
   `bluez_sink.<MAC>.a2dp_sink`, sets it as the default sink, and moves
   playing streams to it, all as `AUDIO_USER` via `su`.
5. Sets the next delay: `RECONNECT_DELAY` while healthy, doubling per
   consecutive failure up to `MAX_RECONNECT_DELAY`.

Design constraints, each tied to a field failure:

- **`bluetoothctl` only in argument mode, always under `timeout`.** Piping
  commands into interactive `bluetoothctl` makes it load, append to and
  rewrite readline history on every call. As root every few seconds, that file
  grew to 31 MB, and each call then took about 48 s at the unit's 64 MB / 10 %
  CPU limits.
- **No `set -e`.** A failing command substitution (for example
  `pactl set-default-sink` while PulseAudio restarts) used to kill the loop.
  Every failure is handled explicitly instead.
- **Probing for the audio server is side-effect free.** It checks for the
  socket file and never runs `pactl info`, because a client connect can
  autospawn PulseAudio, which claims the capture interface on stations that
  keep it stopped.
- **Stop is immediate.** Sleeps run in the background under `wait`, so
  SIGTERM does not wait out a 5-minute backoff.
- The unit restarts the script whenever it exits, with no start limit. The
  exception is exit 78 (invalid configuration), which leaves the unit failed.

Configuration is read from `/etc/orpheus/bluetooth-autoconnect/config.env`
(`ORPHEUS_BLUETOOTH_CONFIG` overrides the path), falling back to the
environment. `install.sh` writes that file on first install and keeps it on
reinstall unless `BLUETOOTH_SPEAKER_MAC` or `AUDIO_USER` is passed explicitly.
The script itself is installed unmodified to `/usr/local/bin/orpheus-bluetooth-connect`.

## Files

| Path | Description |
| ------ | ------------- |
| `/etc/systemd/system/orpheus-bluetooth-autoconnect.service` | Systemd service unit |
| `/usr/local/bin/orpheus-bluetooth-connect` | Connection supervision script |
| `/etc/orpheus/bluetooth-autoconnect/config.env` | Configuration file |

## Make targets

```bash
make install     # sudo; first install or reinstall (keeps config.env)
make status      # systemctl status
make logs        # follow the journal
make health      # running / enabled / errors in the last hour
make test        # pytest static checks + the behaviour suite
make uninstall   # remove the unit (config kept); `make clean` also removes config
```

## Tests

- `tests/bats/bluetooth-autoconnect.bats` (repo root) is the behaviour suite.
  It drives `poll_once` against stateful mocks of `bluetoothctl`, `su` and
  `id`, and covers: startup connect and routing; a quiet healthy poll; a
  speaker dropping and reconnecting; an unavailable speaker's backoff and scan
  policy; no audio server; a hung or restarted bluetoothd; a missing or
  powered-off controller; lost pairing; untrusted devices; set-default-sink
  failures; bad `AUDIO_USER` values; config-file loading; exit 78 on bad
  config; and prompt SIGTERM. Run it with `make test-bash` here or at the repo
  root. CI runs it in the `test-bash` job.
- `tests/test_bluetooth_autoconnect.py` holds static guards: no piped
  `bluetoothctl`, no `set -e`, and no duplicate or misplaced unit keys.

Neither touches real Bluetooth, PulseAudio or system configuration. Hardware
behaviour, meaning real pairing, A2DP profile setup and sink naming on a given
speaker, still needs checking on the device.

## MQTT Topics

**Subscribes to:** Nothing. **Publishes to:** Nothing.

This service does not use the event bus. It manages the Bluetooth connection at
the OS level so that the audio sink exists for `orpheus-agent-audio-playback`.

## Requirements

- `bluez` (`bluetoothctl` 5.5x; installed by `install.sh` if missing)
- PulseAudio (or pipewire-pulse) with Bluetooth support, running as `AUDIO_USER`
- systemd; Python 3.9+ for the test suite
