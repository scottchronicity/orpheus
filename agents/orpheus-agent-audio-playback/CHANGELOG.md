# Changelog

## Unreleased

- File-path and detection-ID playback runs to completion on the agent's event loop. It used to be cancelled about 10 ms after it started.
- Waits for playback to end before publishing the playback window, so `duration_seconds` is the real playback time rather than about 0 s.
- Player failures after a request was accepted are published as an error response; they used to be logged only.

## 0.2.0 — 2026-08-25

- Publishes playback windows so the correlator can tag audio Orpheus played itself.
- Publishes through the event-bus abstraction; carries a log rate limit and syslog identity.
