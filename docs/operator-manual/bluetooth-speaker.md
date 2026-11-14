# Bluetooth speaker

This page covers keeping a Bluetooth speaker connected so Orpheus can play
sounds through it: the `orpheus-bluetooth-autoconnect` service, how it behaves
when the speaker or the Bluetooth stack is unavailable, and what to do when the
speaker never connects. What gets played, and the playback request API, are in
the [audio playback agent's README](https://github.com/scottchronicity/orpheus/tree/main/agents/orpheus-agent-audio-playback).

## What the service does

`orpheus-bluetooth-autoconnect` is a small root service that supervises one
paired speaker. Every poll it asks BlueZ for the speaker's state, and:

- **Connected:** does nothing, and logs nothing.
- **Not connected:** connects, then makes the speaker PulseAudio's default
  output for the audio user and moves any playing streams to it.
- **Unavailable** (speaker off or out of range, no Bluetooth controller,
  bluetoothd not answering): logs why, and retries with a doubling delay —
  10 s, 20 s, 40 s, then every 60 s. The delay drops back to 10 s as soon as
  the speaker is back.

A failed connect is followed by a short discovery scan and a second attempt.
The service survives `bluetooth.service` restarts: each check is a fresh
`bluetoothctl` call with a timeout, so a restarting or wedged bluetoothd shows
up as a logged retry rather than a stuck service.

Playback goes through PulseAudio: the speaker only accepts a connection while a
PulseAudio with its Bluetooth module is running (for the audio user, or in a
desktop session), and the playback agent plays to the audio user's PulseAudio.
This service does not start PulseAudio.

The speaker has to be **paired once by hand**. The service trusts and reconnects
a paired speaker; it does not pair new ones (pairing needs the speaker in
pairing mode and someone to confirm it).

## Install and configure

```bash
# First install, naming the speaker
BLUETOOTH_SPEAKER_MAC=XX:XX:XX:XX:XX:XX sudo make -C services/orpheus-bluetooth-autoconnect install
```

Settings live in `/etc/orpheus/bluetooth-autoconnect/config.env`:

| Setting | Default | Meaning |
|---|---|---|
| `BLUETOOTH_SPEAKER_MAC` | — (set at install) | The paired speaker. |
| `AUDIO_USER` | `orpheus` | The user whose PulseAudio plays to the speaker. The playback agent runs as this user. |
| `RECONNECT_DELAY` | `10` | Seconds between checks while the speaker is healthy. |
| `MAX_RECONNECT_DELAY` | `60` | Longest wait between retries while it is unavailable. |

After editing the file: `sudo systemctl restart orpheus-bluetooth-autoconnect`.
Reinstalling (`make update`, `make update-all`) keeps your edited file. Passing
`BLUETOOTH_SPEAKER_MAC` or `AUDIO_USER` to the install rewrites it and saves the
old one as `config.env.bak`.

An invalid MAC or timing value stops the service with exit code 78 instead of
restarting it; `systemctl status` shows it failed and the journal names the
setting.

## Check on it

```bash
sudo journalctl -u orpheus-bluetooth-autoconnect -n 30 --no-pager
bluetoothctl info XX:XX:XX:XX:XX:XX        # Paired / Trusted / Connected
```

A healthy speaker produces no new log lines. Each state change is logged once
(`state: disconnected -> connected`), and each failed retry logs the reason and
the next delay.

## Troubleshooting

### Speaker never connects: "Protocol not available"

The service logs `Failed to connect ... even after cache refresh`, perhaps with
`Hint: no PulseAudio socket for orpheus`, and `sudo journalctl -u bluetooth`
shows `a2dp-sink profile connect failed for XX:XX:...: Protocol not available`.

BlueZ is saying that nothing on the host has registered an A2DP audio
endpoint, which means no PulseAudio with its Bluetooth module is running. The
speaker itself is fine. Retries cannot succeed until an audio server is up.
Check:

```bash
pgrep -a pulseaudio                               # is any PulseAudio running, and as whom?
ls -l /run/user/$(id -u orpheus)/pulse/native     # the socket the playback agent uses
```

Start PulseAudio the way it ran when playback last worked on this host, and the
service connects on its next retry. Be careful with the capture interface: the
[audio-motion agent's README](https://github.com/scottchronicity/orpheus/tree/main/agents/orpheus-agent-audio-motion)
masks the PulseAudio user service (`systemctl --user mask pulseaudio`) because
PulseAudio can claim the USB interface the recording agents read with ALSA
("Device or resource busy"). After starting PulseAudio, confirm the recording
agents still have their devices.

### Speaker is off, flat or out of range

The journal shows `Failed to connect ...: org.bluez.Error.Failed` (often
`br-connection-page-timeout`) and growing retry delays. Nothing to fix on the
host: switch the speaker on or bring it into range, and it reconnects within
one retry delay (at most a minute). Restart the service to retry at once.

### "is not known to BlueZ" or "not paired"

The pairing was lost (the speaker was reset or paired to another host). Put the
speaker in pairing mode and pair it once:

```bash
bluetoothctl
# then, inside bluetoothctl:
power on
agent on
scan on            # wait for the speaker to appear
pair XX:XX:XX:XX:XX:XX
trust XX:XX:XX:XX:XX:XX
quit
```

The service connects it on its next retry.

### `bluetoothctl` is slow to start when run as root

Versions of the service before this one fed commands to `bluetoothctl` on
stdin, and each call appended to root's history file
`/root/.cache/.bluetoothctl_history`, which can grow to tens of megabytes. The
service no longer writes to it, but the existing file still slows down
interactive `bluetoothctl` sessions run as root. It holds only command history,
and it is safe to delete:

```bash
sudo ls -lh /root/.cache/.bluetoothctl_history
sudo rm /root/.cache/.bluetoothctl_history
```

### Sounds play from the wrong output, or not at all

The service selects the speaker as the default output only once it is
connected. While the speaker is unavailable, a playback request is accepted
(`"message": "Playback started"`), and the player's failure follows as a
second, `"status": "error"` response on `orpheus/audio/playback/response`.
Watch that topic, or the playback agent's journal, to see why a sound did not
play.

## Rollback

The service is self-contained. To stop it: `sudo systemctl disable --now
orpheus-bluetooth-autoconnect`. To return to an earlier version, check out that
commit and reinstall it. Earlier versions rewrite `config.env` on every
install, so name your speaker when you do:
`BLUETOOTH_SPEAKER_MAC=XX:XX:XX:XX:XX:XX make -C services/orpheus-bluetooth-autoconnect install`.
