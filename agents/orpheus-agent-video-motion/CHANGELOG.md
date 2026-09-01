# Changelog

## 0.3.0 — 2026-08-26

- Stopped deleting motion clips. `orpheus-storage-sweep` owns retention for every category; `storage.retain_days` is no longer applied here and the agent says so at startup.


## 0.2.0 — 2026-08-25

- Publishes through the event-bus abstraction; health and cleanup follow the shared policies.
- Camera credentials no longer appear in capture logs.
