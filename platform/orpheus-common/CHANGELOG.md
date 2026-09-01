# Changelog

## 0.4.0 — 2026-08-26

- `orpheus-storage-sweep`: one component that owns every deletion under the data root, run as a systemd one-shot on a 15-minute timer. Enforces per-category ceilings first, then relieves disk pressure by taking from each category above its floor in proportion to what it has to give.
- Retention floors are absolute: the sweep never deletes inside `floor_days` or `min_file_age_hours`, and logs CRITICAL rather than breaching one to satisfy a ceiling or a reserve.
- The first sweep after an install reports what it would delete and deletes nothing, for `storage.retention.first_run_grace_hours` (24h by default).
- New `storage.retention` keys: `sweep_enabled`, `reserve_gb`, `sweep_interval_minutes`, `first_run_grace_hours`, and per-category `categories.<key>.{max_gb,floor_days}`. `reserve_gb` and the older `min_free_space_percent` are reconciled by taking whichever is stricter.
- `StorageCleanup` and `cleanup_old_files_by_age` remain as per-directory helpers, but nothing runs them on a timer any more.
- A connect attempt against a cold broker is bounded instead of open-ended, so a service that starts before the backplane now comes up disconnected and attaches when the broker appears, rather than failing to connect at all.
- Subscriptions the broker never accepted are re-applied after a reconnect and by a periodic sweep, and the bus reports which subjects it is subscribed to versus still waiting on.


## 0.3.0 — 2026-08-25

- Event-bus abstraction with a NATS + JetStream backend (default) and mosquitto as a fallback, including request/reply, key/value, durable streams, key/value-TTL presence, and retain-as-last-value.
- Actor base composing the agent lifecycle, with an injectable clock, periodic tasks, and per-instance identity.
- Cross-classifier identity, the entity-type taxonomy, equivalence discovery, and latent state-space memory.
- Storage cleanup with a low-disk guard; layered configuration with a pluggable backend; event-sourcing shadow publication and reconciliation; read-only database mode, mirror snapshots, and the public projection.
- Schema migrations are additive and wait out a concurrent migration on first open.
