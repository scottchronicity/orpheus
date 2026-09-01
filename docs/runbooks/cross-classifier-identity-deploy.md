# Runbook — deploying the cross-classifier-identity branch

Operator-side checklist for the work on the `detectallanimals` branch.
Order matters — schema migrations land first; backfill happens after;
agent restarts happen last.

## Before you touch anything

1. Confirm you have a recent backup of
   `/data/orpheus/detections/orpheus.db` (the DetectionDB + entities
   tables live here). All the migrations in this branch are additive
   and idempotent but it costs nothing to have a rollback.
2. Confirm you've got the new `orpheus.example.yaml` knobs reflected
   in your live `orpheus.yaml`, or that you're happy with the defaults
   (the system will use defaults if the new keys are absent).

## Deploy sequence

### 1. Pull + install

Follow [jetson-rollout](jetson-rollout.md) §0–§3 for the pull, backup, tag and
install. Running `make install` alone leaves the deployed venvs stale: the
component deploys reinstall orpheus-common from `/opt`, not from the tree, so
the agents run old code even though you pulled. This page adds only the
branch-specific steps below.

### 2. Schema migration runs automatically

On first run of any orpheus-common consumer, `ensure_schema_updates()`
adds the new columns/tables. Nothing for you to do — but you can
verify by inspecting the DB:

```bash
sqlite3 /data/orpheus/detections/orpheus.db ".schema detections" \
  | grep -E "intervals_json|taxonomy_namespace|taxonomy_id|root_event_id"
# Should show all four columns.
sqlite3 /data/orpheus/detections/orpheus.db ".schema entities" \
  | grep event_signature
# Should show event_signature TEXT.
sqlite3 /data/orpheus/detections/orpheus.db ".tables" \
  | grep -E "taxonomy_equivalence|taxonomy_non_equivalence"
# Both tables should exist.
```

### 3. Backfill root_event_id on legacy rows

Required if you have detection rows from before this branch landed
(otherwise the chain endpoint + auto-discovery won't see them).

```bash
# Dry-run first to see what'll change.
# Run as orpheus with the deployed interpreter: the system python has no
# orpheus_common, and running as root leaves a root-owned WAL the agents
# cannot write to.
sudo -u orpheus ORPHEUS_DATA_ROOT=/data/orpheus \
  /opt/orpheus/platform/orpheus-common/venv/bin/python tools/maintenance/backfill_root_event_ids.py --dry-run

# If the numbers look right, run for real.
# Run as orpheus with the deployed interpreter: the system python has no
# orpheus_common, and running as root leaves a root-owned WAL the agents
# cannot write to.
sudo -u orpheus ORPHEUS_DATA_ROOT=/data/orpheus \
  /opt/orpheus/platform/orpheus-common/venv/bin/python tools/maintenance/backfill_root_event_ids.py
```

Idempotent — safe to re-run if anything got skipped on a broken chain.

### 4. Restart agents

```bash
sudo systemctl restart orpheus-agent-audio-motion
sudo systemctl restart orpheus-agent-bird-detection
sudo systemctl restart orpheus-agent-crow-detection
sudo systemctl restart orpheus-agent-event-correlator
sudo systemctl start orpheus-agent-audio-events     # new — first-time start
sudo systemctl restart orpheus-ui
```

Then refresh the dashboard in the browser to pick up the new
frontend bundle.

### 5. Verify

#### A. Each agent comes up clean

```bash
sudo systemctl status orpheus-agent-{audio-motion,bird-detection,crow-detection,event-correlator,audio-events}
journalctl -u orpheus-agent-audio-events --since "5 minutes ago"
# Look for "Loading PANNs Cnn14_DecisionLevelMax" + "online" health
# publication; no OOM crashes.
```

#### B. Correlator subscribes to all three detection topics

```bash
journalctl -u orpheus-agent-event-correlator --since "5 minutes ago" | \
  grep "Subscribed to detection topic"
# Should show 3 lines: bird, crow, audio.
```

#### C. A real audio.motion event flows through

Talk into a microphone, watch:

```bash
# Needs the NATS CLI, which Orpheus does not install:
#   go install github.com/nats-io/natscli/nats@latest
# Without it, watch the journal instead:
#   journalctl -u orpheus-agent-event-correlator -f | grep -i EntityEvent
nats sub 'orpheus.entities.animal'
```

You should see one Entity emerge a few seconds later with `evidence`
containing multiple classifier observations and `event_signature.audio_motion_source_ids`
listing the originating motion event(s).

#### D. UI Entity drawer

Open any Entity in the UI:
- Event Lineage card shows audio_motion_source_ids + sensors + time
  span.
- Evidence section shows per-classifier rows (BirdNET / PANNs /
  crow-tools) each with their own species + taxonomy + intervals.
- Detection chain panel (expand it) returns the full lineage.

#### E. Auto-discovery worker is running

```bash
nats sub 'orpheus.system.auto-discovery.health'
```

The first scan publishes after `auto_discovery.interval_seconds`
(default 6h). To trigger immediately:

- UI: hit "Scan now" on the `/equivalences` page.
- API: `# admin-only. Get a token from the UI: DevTools -> Network -> any /api call ->
# the Authorization header.
curl -X POST -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{}' http://localhost:8082/api/equivalences/scan`

Expected response shape:
```json
{
  "ran_at": "...",
  "total_proposals": N,
  "recorded": M,
  "skipped_existing": ...,
  "skipped_blocked": ...,
  "proposals": [...]
}
```

#### F. Equivalences page

Browse to `/equivalences`. After a few days of operation you should
see auto-accepted equivalences appearing (Jaccard ≥ 0.9). Pending
review proposals (Jaccard 0.6-0.9) await human approval.

## Rollback

Code rollback is [jetson-rollback](jetson-rollback.md) Level 2, against the
pre-deploy tag you made in rollout §2 — quiesce first, then swap. No database
work is needed. The new columns and tables stay in the DB and the old binary
reads them untouched:

- `root_event_id` columns just sit as NULL on new rows.
- `event_signature` column ditto on entities.
- `taxonomy_equivalence` table sits unused.

You don't need to drop columns or tables.

## Tuning

All knobs live under `correlation:` in `orpheus.yaml`:

```yaml
correlation:
  window_seconds: 3.0          # Layer 2 cluster window
  auto_discovery:
    enabled: true
    interval_seconds: 21600    # 6h
    lookback_days: 7
    accept_threshold: 0.9      # ≥ this auto-accepts
    propose_threshold: 0.6     # ≥ this and < accept = pending_review
    min_cooccurrences: 5
```

After about a week of live operation you'll have enough data to know
whether to tighten / loosen these. The user-facing review queue on
`/equivalences` is the best signal — too many junky proposals →
raise `min_cooccurrences` or `propose_threshold`.

## When something goes wrong

- **No Entities appearing** → correlator likely isn't subscribed to
  the right topics. Check `correlation.input_topics` in orpheus.yaml.
- **Entity has only one piece of evidence even though multiple agents
  fired** → check `window_seconds`. If agents are slow (PANNs taking
  >3s) you may need to widen it. The /equivalences page will also be
  empty if cross-agent co-occurrence isn't being captured.
- **Auto-discovery never proposes anything** → check that detections
  actually have `taxonomy` set (legacy agents from before Layer 1
  would have NULL); check that the lookback window has enough events
  to clear `min_cooccurrences`.
- **Chain endpoint returns 404** → either the `root_event_id` isn't
  set on those legacy rows (run the backfill) or the audio.motion
  event was never persisted to the DB.

## Related docs

- Full design: `docs/designs/cross-classifier-identity.md`
- ADR: `docs/adr/0011-temporal-localisation-and-taxonomy-references.md`
- Live-test harness: `tools/integration/README.md`
