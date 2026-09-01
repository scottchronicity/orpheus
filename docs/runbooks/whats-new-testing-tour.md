# What's new — the testing tour

A guided checklist of what this release added, ordered so you can verify it on a
deployed station. Part 1 needs no configuration changes. Part 2 is
one flag at a time (per the [rollout runbook](jetson-rollout.md) §5 — flip, watch,
move on; every flag's rollback is just turning it off again).

## Part 1 — already live after the deploy (no flags)

- [ ] **Charts fail honestly now.** Stop a backend briefly (or pull the network) —
  data pages show an error state instead of silently-blank charts. Restart; they recover.
- [ ] **Dashboard pacing knob works.** `dashboard.poll_interval` in orpheus.yaml now
  actually drives how often the UI polls (it was dead before). Double it; watch the
  network tab slow down. This is the lever if the dashboard ever makes the box feel busy.
- [ ] **Deploy health in one command:** `make verify-deploy` — every component ✅,
  services active. Run it whenever an update feels suspicious.
- [ ] **Retention moved out of the agents.** `systemctl status
  orpheus-storage-sweep.timer` — active, next elapse within 15 minutes. (Its
  `.service` is a one-shot and reads *inactive (dead)* between runs; that is
  correct.) Then `make storage-report`: a per-category table of size, ceiling and
  floor that deletes nothing. For the first 24 hours it is report-only, so if a row
  says it *would* remove something, that is the window to disagree with the ceiling
  — `storage.retention.categories.<key>.max_gb`. `sudo systemctl disable --now
  orpheus-storage-sweep.timer` stops all deletion if you want to think about it
  longer.
- [ ] **`make manifests TARGET=systemd`** prints an `orpheus.target` matching exactly
  the agents your config enables — sanity-check it lists what you expect to run.
- [ ] **Diagnostics page:** the presence panel exists (shows "not available" until
  Part 2 turns presence on); recent-errors panel; storage history with days-until-full.
- [ ] **Laptop bonus (macOS or Linux):** `SIM_MODE=replay make sim-up` +
  `make sim-fleet-up` runs the whole collective in containers and classifies the
  bundled robin/jay/crow clips with the real models — watch entities appear with
  zero hardware.

## Part 2 — flip one flag, observe, next

Order chosen so each observation is unambiguous.

1. [ ] **Per-agent tick** — set `agents.event-correlator.heartbeat_seconds: 10`,
   restart the correlator: its health card updates noticeably faster. Remove to revert.
2. [ ] **Corollary discharge** (`corollary_discharge.enabled: true`, restart
   correlator) — Orpheus stops counting its own playbacks as wildlife. Trigger a
   playback (see the audio-playback README's `orpheus/audio/playback/request`
   examples); the entity created from the sound the mic hears carries the
   **self-generated** tag on the Entities page (tagged, never dropped — the data
   stays for analysis). Off (the default): no playback subscription, no tagging.
3. [ ] **Presence** (`event_bus.presence_enabled: true`, restart agents) — the
   Diagnostics presence panel lists every live agent. The fun test: `kill -9` one
   agent; it drops off the panel within ~90s (the presence TTL is 3× the fleet's
   *largest* configured heartbeat, floored at the 30s default — the bucket TTL is
   shared, so step 1's 10s correlator override does not shrink it), then systemd
   restarts it and it reappears. That's the NATS replacement for MQTT's last-will.
4. [ ] **Weather** (`weather.enabled: true` + the station `url`) — skip this leg
   unless you are grounding the Ecowitt mapping yourself. `EcowittProvider._parse`
   raises `NotImplementedError` by design (the field names and units are
   vendor-specific and not captured here), and the ingest loop deliberately
   re-raises it, so `orpheus-weather` exits on its first poll and the card never
   populates. Once the mapping is grounded, the payoff is that every NEW entity
   carries the conditions it was heard under (`context.weather` — ask "do crows
   visit before a storm?" of the data later).
5. [ ] **Late-arrival enrichment** (`correlation.late_enrichment.enabled: true`,
   restart correlator) — when a slow classifier reports after the 3-second window,
   it now enriches the existing entity instead of creating a duplicate. Watch
   `entities_enriched` climb in the correlator health payload during busy periods;
   the Entities page should show fewer same-moment duplicates.
6. [ ] **Event-sourcing shadow** (`event_sourcing.shadow_publish_enabled: true`,
   nats only) — detections also land in a bounded durable stream (on dedicated
   `orpheus/domain/...` subjects, disjoint from the live topics). Verify with
   `make reconcile`: `db_only` entries are fine; any `stream_only` is a bug (report it).
7. [ ] **Rate limiting** (`ui.rate_limit_enabled: true`) — hold refresh on a data
   page: after ~300 requests/min you get polite 429s instead of a struggling box.
   Mostly matters for the future shared portal; fine to turn back off.

## Beyond this tour (documented elsewhere)

Health-KV serving migration (`ui.health_source` phases), the read-only mirror +
`ui.read_from_replica`, distributed config (`config_service`), the public data
export (`public.enabled`) — each has its own section in the
[Operator's Manual](../operator-manual/index.md).

## If anything misbehaves

One flag off = that feature fully reverted ([rollback runbook](jetson-rollback.md)
Level 1). Please jot down what you saw and open an issue for anything that looked wrong.
