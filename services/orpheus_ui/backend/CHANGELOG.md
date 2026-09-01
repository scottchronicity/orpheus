# Changelog

## 0.4.0 — 2026-08-26

- The storage headroom panel reads the sweep's published report instead of the motion agents' health payloads, so every recording category now shows a ceiling and a floor — including timelapses, which previously showed as having nothing that cleaned them.
- The panel says whether anything is actually deleting: enforcing, reporting only during the first-run grace, disabled, or never run.
- The free-space guard is reported in bytes (the reserve) rather than as a percentage, and calls out the case where the disk is below the reserve with every category at its floor.
- A failure while starting the optional health key/value consumer no longer leaves the dashboard connected to the event bus but subscribed to nothing, quietly serving a cache that would never update again.
- The bus diagnostics endpoint reports subscribed and pending subjects, so a service that is listening can be told apart from one that is merely connected.


## 0.3.0 — 2026-08-25

- Entities, Audio Events, Equivalences, and Diagnostics APIs; storage history with a fill projection; health served from either the bus or the key/value plane.
- History and stats endpoints aggregate from raw rows instead of building a model per row, and the entities queries use a covering index with server-side sampling.
- Security: path containment on the single-page-app and clip routes, administrator-only account creation, debug configuration and write endpoints, always-on sign-in rate limiting, and no credentials on the login page.
- The accounts database follows the configured data root.
