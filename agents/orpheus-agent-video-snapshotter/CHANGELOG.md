# Changelog

## 0.3.0 — 2026-08-26

- Stopped deleting snapshots. `orpheus-storage-sweep` owns retention for every category; `video_snapshotter.retention_days` is no longer applied and the agent says so at startup.


## 0.2.0 — 2026-08-25

- Publishes through the event-bus abstraction; carries a log rate limit and syslog identity.
- Camera credentials no longer appear in debug logs.
