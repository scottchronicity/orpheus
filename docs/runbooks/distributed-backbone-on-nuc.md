# Runbook — backbone on the NUC, sensing + correlation on the Jetson

Move the messaging backbone (NATS/JetStream broker) onto a separate box (a NUC),
and run the sensing + correlation agents on the Jetson pointing back at it. This
is the headline split: it takes the broker's load off the Jetson and lets other
hosts (a public portal, more sensor nodes) join the same backbone later.

Design: [`../designs/distributed-deployment.md`](../designs/distributed-deployment.md).
Everything here is **reversible** — removing one env line restores single-host.

## Preconditions

- NUC + Jetson on the same LAN; the Jetson can resolve `nuc.local` (or use the IP).
- `git pull` on both; `make check-models` on the **Jetson** (it holds the models).
- **Trust tier:** a trusted home LAN may defer TLS (owner-managed). An untrusted
  segment needs TLS + auth **before** opening the listener — the installer refuses
  to open the listener without an auth file regardless (see Step 1). Reverse proxy
  / TLS are **yours to manage** and out of scope here.

## Step 1 — the backbone (on the NUC)

```bash
cd ~/runtime/orpheus && git pull   # the git checkout; /opt is an rsync deploy tree
# Provide a NATS authorization block (user/pass + per-role subject perms).
# This runbook does NOT generate credentials — obtain/author nats.auth yourself.
sudo mkdir -p /etc/orpheus/backplane   # /opt/orpheus/config is created by the
                                       # platform installer, which a backbone-only
                                       # host never runs
sudoedit /etc/orpheus/backplane/nats.auth        # an `authorization { ... }` block

make install-backbone LISTEN=0.0.0.0:4222 AUTH_FILE=/etc/orpheus/backplane/nats.auth
# The installer REFUSES a non-loopback listener without AUTH_FILE (ADR 0018),
# deploys nats.distributed.conf (LAN listener + the auth include; monitoring stays
# loopback), and leaves the shipped loopback config untouched.
make -C services/orpheus-backplane restart
```

Verify the broker is up (monitoring stays loopback, so run this **on the NUC**):

```bash
curl -s http://127.0.0.1:8222/healthz    # -> {"status":"ok"}
```

### Upgrading a backbone that is already open to the LAN

`/etc/orpheus/backplane/nats.conf` is seeded on first install and left alone after
that, so a later `make install-backbone` with no arguments does not revert your LAN
listener — it installs the code and leaves the config as you left it. What it does
*not* do is re-apply `LISTEN`/`AUTH_FILE`: those only take effect on an invocation
that passes them. So an upgrade is either:

```bash
make install-backbone                        # keeps the existing nats.conf as-is
```

or, if you are changing the listener or rotating the auth file, the full form again:

```bash
make install-backbone LISTEN=0.0.0.0:4222 AUTH_FILE=/etc/orpheus/backplane/nats.auth
```

Either way, confirm afterwards rather than assuming:

```bash
grep -E '^listen|include' /etc/orpheus/backplane/nats.conf   # LAN listener + nats.auth include
make -C services/orpheus-backplane restart
```

## Step 2 — the agent subset (on the Jetson)

```bash
cd ~/runtime/orpheus && git pull   # the git checkout; /opt is an rsync deploy tree
make install-host \
  COMPONENTS="audio-motion audio-events bird-detection crow-detection event-correlator" \
  BACKBONE=nats://nuc.local:4222
# install-host writes ORPHEUS_EVENT_BUS__NATS_URL=nats://nuc.local:4222 into
# /opt/orpheus/config/.env, which every agent unit now reads.
make services-start          # or start only the units you installed
```

## Step 3 — verify the split

```bash
# Jetson: the agents connected to the REMOTE broker, not localhost.
journalctl -u orpheus-agent-crow-detection -n 50 | grep "Connected to NATS"
#   -> url=nats://nuc.local:4222   (NOT 127.0.0.1)

# NUC: the correlator produces EntityEvents; the UI shows live detections.
# Bounce the broker briefly and confirm the agents reconnect on their own:
make -C services/orpheus-backplane restart   # on the NUC
journalctl -u orpheus-agent-crow-detection -f # on the Jetson -> "NATS reconnected"
```

A Jetson agent that boots **before** the NUC broker is up will start "disconnected"
and attach when the broker appears (it won't crash) — that's by design for a remote
backbone.

## Step 4 — reverse proxy / TLS (pointer only)

Exposing anything off-LAN, or securing an untrusted segment: front it with your
reverse proxy + TLS and put TLS on the broker listener. **Owner-managed; out of
scope for this runbook.**

## Rollback (reversible)

```bash
# Jetson: drop the backbone pointer -> agents fall back to the loopback default.
sudo sed -i '/^ORPHEUS_EVENT_BUS__NATS_URL=/d' /opt/orpheus/config/.env
make services-restart
# Full revert: re-run `make install` on the Jetson (single-host, all-in-one).
```
