# Changelog

## Unreleased

- The unit no longer sets `PULSE_SERVER`/`XDG_RUNTIME_DIR` from `%U`, which resolves to UID 0 in a system unit, so sounds never reached the user's PulseAudio. `orpheus-audio-output` installs a drop-in with the right paths.
- File-path and detection-ID playback runs to completion on the agent's event loop. It used to be cancelled about 10 ms after it started.
- Publishes a start marker as soon as the output backend starts, then a matching finish event with monotonic measured elapsed playback time. This lets the correlator account for early detections during long playback.
- Player failures after a request was accepted are published as an error response; they used to be logged only.

## 0.2.0 — 2026-08-25

- Publishes playback windows so the correlator can tag audio Orpheus played itself.
- Publishes through the event-bus abstraction; carries a log rate limit and syslog identity.
