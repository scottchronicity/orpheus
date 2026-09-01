# Changelog

## 0.3.0 — 2026-08-26

- Stopped deleting audio clips. `orpheus-storage-sweep` owns retention for every category; `storage.retain_days` is no longer applied here and the agent says so at startup.


## 0.2.0 — 2026-08-25

- Publishes through the event-bus abstraction; dual-writes health to the key/value plane and shadow-publishes to the durable stream, both off by default.
- Storage cleanup honors the shared retention policy and the low-disk guard.
- Fixed a doubled prefix in the bus client identifier.
