# Changelog

## 0.2.0 — 2026-08-25

- Runs on the Actor base, with bounded concurrent clip processing that is not cancelled mid-flight.
- Survives a missing GPU through a shared device-selection policy.
- Fixed a whitelist that was dropping eight bird-like AudioSet labels, including every corvid.
