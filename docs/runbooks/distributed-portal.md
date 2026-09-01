# Runbook — the portal (UI) on its own host

Run the Orpheus UI on a separate host so heavy reads (dashboards, queries) never
touch the live Jetson DB. This is the read host for the **read-only data portal**
(see [`../designs/read-only-portal.md`](../designs/read-only-portal.md)).

Design: [`../designs/distributed-deployment.md`](../designs/distributed-deployment.md).

## What's wired today vs forthcoming

- **Today:** you can install the UI on its own host and point it at the backbone.
  The **mirror** (snapshot → push of a read-only DB replica) is shipped
  (`orpheus-mirror`, ships with orpheus-common), and so is the read flag:
  `ui.read_from_replica: true` points the UI's reads at the **replica** instead
  of the live DB (read-only open over the mirror path; if the replica is missing
  or broken the UI falls back to the live DB with a warning — see the
  [Operator's Manual §7](../operator-manual/index.md) for the fallback semantics).
- **Forthcoming:** the privacy-projected **public** site (the
  `orpheus-public-export` dataset exists; its hosted site does not yet).

## Step 1 — the mirror (on the Jetson)

```bash
# Snapshot the live DB and push a read-only replica to the portal host.
# Nothing extra to install on an already-deployed Jetson — the orpheus-mirror
# CLI ships with orpheus-common. Configure
# mirror.{enabled,transport,dest,interval_seconds} in orpheus.yaml, then:
/opt/orpheus/platform/orpheus-common/venv/bin/orpheus-mirror --once   # console script in
                          # the deployed venv — it is not on your PATH
```

The replica lands on the portal host; the mirror never write-locks or mutates the
live DB. Simplest no-second-host variant: `transport: local`, `dest` on the same
box, for contention relief without a separate portal host.

Repeating the snapshot is your job: no service unit ships for the mirror, and
`mirror.enabled` only reserves the setting for a future one. Run `orpheus-mirror`
from cron, a timer, or a unit you write, at whatever interval your dashboard
freshness needs.

## Step 2 — the UI (on the portal host)

```bash
cd ~/runtime/orpheus && git pull   # the git checkout; /opt is an rsync deploy tree
make install-host COMPONENTS="ui" BACKBONE=nats://nuc.local:4222
make services-start
```

The UI unit reads `/opt/orpheus/config/.env` (the backbone URL) like any agent.

## Step 3 — point the UI at the replica (on the portal host)

**This is the step that is easy to miss.** `mirror.staging_path` is a *per-host*
setting, and the UI resolves the replica from **its own host's** value — not from
anything the sending box configured. On the Jetson it names where the snapshot is
written; on the portal host it must name where the push *lands*, which is the `dest`
you set in step 1. Set both keys in the portal host's `orpheus.yaml`:

```yaml
ui:
  read_from_replica: true
mirror:
  staging_path: /data/orpheus/mirror/orpheus.db   # where step 1's push lands HERE
```

Leave `staging_path` empty on the reader and the UI silently reads the live database
instead — which on a portal host does not exist, so it creates an empty one and the
dashboard is blank with data flowing normally on the Jetson. Nothing on screen tells
you which database is being served, so confirm it from the journal and the filesystem
rather than guessing:

```bash
sudo systemctl restart orpheus-ui
ls -l /data/orpheus/mirror/orpheus.db     # the replica actually arrived
journalctl -u orpheus-ui --since -2m | grep -i replica
```

Do not read silence from that grep as success. The UI warns only when
`mirror.staging_path` is set *and* the file behind it is missing; if the path is
empty the check short-circuits and it falls back to the live database saying
nothing at all — which is the mistake this step exists to catch. Confirm both
halves explicitly instead:

```bash
# staging_path must be set on THIS host, not just on the pusher
sed -n '/^mirror:/,/^[a-z]/p' /opt/orpheus/config/orpheus.yaml | grep -E 'staging_path|^mirror'
# must print an UNCOMMENTED staging_path; it sits six lines below `mirror:`
ls -l /data/orpheus/mirror/orpheus.db     # and the file it names must exist
```

With both true and no warning in the journal, the UI is reading the replica.

## Step 4 — verify

```bash
journalctl -u orpheus-ui -n 50 | grep "Connected to NATS"   # live updates over the backbone
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8082/api/health
# expect 401 — the endpoint is JWT-gated, so a 401 means the API is up;
# log in via the UI for actual data
```

## Step 5 — reverse proxy / TLS (pointer only)

The portal is the most likely thing you'll expose beyond the LAN. Front it with
your reverse proxy + TLS. **Owner-managed; out of scope.** (The public,
privacy-filtered site is a separate read-only-portal deliverable — data-only,
location/time coarsened — not this runbook.)

## Rollback

`# 1. Stop the snapshot schedule you created in Step 1 (your cron entry or timer).
#    `mirror.enabled` does not gate it — no service unit ships.
# 2. Point the UI back at the live DB, or it keeps serving a frozen replica with
#    nothing on screen to say so: set ui.read_from_replica: false in this host's
#    orpheus.yaml.
sudo sed -i '/^ORPHEUS_EVENT_BUS__NATS_URL=/d' /opt/orpheus/config/.env` +
`make -C services/orpheus_ui restart`. Stop the mirror by setting
`mirror.enabled: false` (or stopping `orpheus-mirror`).
