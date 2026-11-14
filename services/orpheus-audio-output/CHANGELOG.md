# Changelog

## 0.1.0 — Unreleased

- New `orpheus-audio-output` service, replacing `orpheus-bluetooth-autoconnect`. It keeps the configured output ready for playback, with three independently configured parts: the output device (`audio_output.output.type: bluetooth`), the audio server (`audio_output.server.type: pulseaudio`), and the reconnect policy (`audio_output.reconnect`).
- Runs its own PulseAudio for the configured user. That instance loads only the native-protocol and Bluetooth modules, never an ALSA module, so it cannot take the capture interface. It adopts a PulseAudio that is already running for that user instead of replacing it.
- Reads `/etc/orpheus/bluetooth-autoconnect/config.env` for any values `orpheus.yaml` does not set. The installer retires the old unit.
- Reports health on `orpheus/audio/output/health` and in `/run/orpheus-audio-output/health.json`.
