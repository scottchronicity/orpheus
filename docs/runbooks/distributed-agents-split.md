# Runbook — agents split across multiple hosts

Run different subsets of agents on different boxes, all pointing at one backbone.
For example an **audio host** (a Pi near a feeder) and a **video host** (a camera
box), each installing only what it runs. This is the same mechanism as
[backbone-on-the-NUC](distributed-backbone-on-nuc.md) — just `install-host` on more
than one box with the same `BACKBONE=`.

Design: [`../designs/distributed-deployment.md`](../designs/distributed-deployment.md).

## Preconditions

- All hosts on the same LAN; each can resolve the backbone host (`nuc.local` / IP).
- The backbone is already up (see [backbone-on-the-NUC](distributed-backbone-on-nuc.md)
  Step 1). The correlator lives wherever the DB + UI do (the "backbone box").
- `git pull` on each host; run `make check-models` on any host that installs a
  model-bearing agent (bird/crow/audio-events).

## Step 1 — audio host

```bash
cd ~/runtime/orpheus && git pull   # the git checkout; /opt is an rsync deploy tree
make install-host COMPONENTS="audio-motion audio-events" BACKBONE=nats://nuc.local:4222
sudo systemctl start orpheus-agent-audio-motion orpheus-agent-audio-events
# Start only what this host installed. `make services-start` starts the whole
# monorepo with no error tolerance, so on a single-purpose host it aborts on the
# first unit that is not installed here — usually the backplane.
```

## Step 2 — video host

```bash
cd ~/runtime/orpheus && git pull   # the git checkout; /opt is an rsync deploy tree
make install-host COMPONENTS="video-motion video-snapshotter video-timelapser" \
  BACKBONE=nats://nuc.local:4222
sudo systemctl start orpheus-agent-video-motion orpheus-agent-video-snapshotter \
  orpheus-agent-video-timelapser        # only what this host installed, per above
```

Each host installs **only** its components (validated against the known set before
anything is installed) and writes the same `ORPHEUS_EVENT_BUS__NATS_URL` into its
own `/opt/orpheus/config/.env`. There is no cross-host install dependency — an
agent consumes the others' events over the backbone, not by being co-installed.

## Step 3 — verify

```bash
# On each host: its agents connected to the backbone.
journalctl -u orpheus-agent-audio-events -n 50 | grep "Connected to NATS"
#   -> url=nats://nuc.local:4222
# On the backbone box: the correlator fuses detections from all hosts into entities.
```

## Notes

- **Multiple instances of one type** (e.g. audio-motion on several hosts) do
  **not** get distinct on-bus identities. The `instance_id` seam in the actor
  identity reads `ORPHEUS_AGENT_INSTANCE_ID` and appends it to the client id and
  health topic, but `install-host` never writes that variable, and audio-motion,
  audio-playback and video-motion hardcode their client id instead of deriving
  it. Set `ORPHEUS_AGENT_INSTANCE_ID` per host in `/opt/orpheus/config/.env` for
  the agents built on the actor base (audio-events, bird-detection,
  crow-detection, event-correlator); the other three collide until they adopt it.
- Reverse proxy / TLS for any off-LAN exposure: **owner-managed** (pointer only).

## Rollback

Per host: `sudo sed -i '/^ORPHEUS_EVENT_BUS__NATS_URL=/d' /opt/orpheus/config/.env`
then restart this host's own units — `sudo systemctl restart 'orpheus-agent-*'`
(falls back to loopback — i.e. that host expects a
local broker; for a pure sensor host you'd instead stop its units).
