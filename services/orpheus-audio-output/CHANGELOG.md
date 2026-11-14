# Changelog

## 0.1.0 — Unreleased

- New `orpheus-audio-output` service, replacing `orpheus-bluetooth-autoconnect`. It keeps the configured output ready for playback, with three independently configured parts: the output device (`audio_output.output.type: bluetooth`), the audio server (`audio_output.server.type: pulseaudio`), and the reconnect policy (`audio_output.reconnect`).
- Runs its own PulseAudio for the configured user. That instance loads only the native-protocol and Bluetooth modules, never an ALSA module, so it cannot take the capture interface. It adopts a PulseAudio that is already running for that user instead of replacing it.
- Reads `/etc/orpheus/bluetooth-autoconnect/config.env` for any values `orpheus.yaml` does not set. The installer retires the old unit.
- The installer is transactional. Preflight (staged build, config, user, tools, PulseAudio modules, mask paths) changes nothing on the host. Any later failure, including no ready server or broken capture isolation within 60 s of starting, restores the previous deployment, unit file and host changes. Each touched unit returns to its previous enabled and running state, and rollback restores those states too.
- The user's stock PulseAudio masks are verified through that user's systemd manager after a reload (`LoadState=masked`, socket inactive).
- If PulseAudio restarts while the speaker stays connected and no sink appears, the speaker is reconnected once so A2DP renegotiates with the new server.
- Points the playback agent at the managed server through a drop-in (`PULSE_SERVER`, `XDG_RUNTIME_DIR`, `SDL_AUDIODRIVER=pulseaudio`), and checks in preflight that the agent runs as the PulseAudio user. Found in the Jetson acceptance test: the playback unit's `/run/user/%U` resolves to UID 0, so playback never reached the user's PulseAudio.
- Reports health on `orpheus/audio/output/health` and in `/run/orpheus-audio-output/health.json`.
