# Changelog

## 0.2.0 — 2026-08-25

- Runs on the Actor base, with shutdown-flush behavior pinned by tests.
- Correlates by shared source rather than co-occurrence, derives and emits entity types, and joins fresh weather context onto emitted entities.
- Corollary discharge tags entities overlapping Orpheus's own playback; late-arrival enrichment folds a slow classifier into the right entity; latent state-space memory records what was present. All off by default.
- Expiry failures are counted and survivable rather than silently killing the timer.
