# Runbooks

Operator-facing, step-by-step procedures. Each is one named topology or task with
the exact commands, verification, and a rollback. Reverse proxy / TLS are always
**owner-managed** (a one-line pointer, never detailed here).

Every runbook here is in the site nav under Operator's Manual → Runbooks; this page
is the same list with a sentence on when to reach for each.

## Upgrading a running station

Read these in order. The rehearsal is the cheap step that catches most of what would
otherwise bite you on the Jetson.

| Runbook | When |
|---|---|
| [Laptop verification](laptop-verification.md) | Before any Jetson deploy. Rehearse the branch on the laptop against its own populated database — a real-data spot check that catches migration problems cheaply. |
| [Jetson upgrade checklist](jetson-upgrade-checklist.md) | The whole rollout on one screen. Start here if you have done this before. |
| [Jetson rollout](jetson-rollout.md) | The full procedure with backups and a soak, and the detail behind every line of the checklist. **Start here if you are upgrading an existing install.** |
| [Jetson rollback](jetson-rollback.md) | Something is wrong. Three escalation levels: flip a feature flag, return to the pre-deploy tag, or restore data. |
| [What's new — testing tour](whats-new-testing-tour.md) | After a clean soak, to turn the new features on one at a time and watch each one. |

## Tuning and adjacent tooling

- [Getting the most from a local Ollama box](ollama-local-llm.md) — running a local
  LLM alongside Orpheus, and what it is and is not good for.

## Deployment topologies (home-lab distributed)

Design: [`../designs/distributed-deployment.md`](../designs/distributed-deployment.md).

| Topology | Backbone | When |
|---|---|---|
| **All-on-Jetson** (baseline) | Jetson, loopback | The default. `make install` — single host, no `.env` backbone line. This is the rollback target for every split below. |
| [Backbone on the NUC](distributed-backbone-on-nuc.md) | NUC | Take the broker's load off the Jetson; let other hosts join. The headline split. |
| [Agents split across hosts](distributed-agents-split.md) | one host | Run subsets on multiple boxes (audio host, video host) against one backbone. |
| [Portal on its own host](distributed-portal.md) | wherever | UI/read host so heavy reads never touch the live Jetson DB (the read-only data portal). |

The mechanics behind all of these:
`make install-host COMPONENTS="..." BACKBONE=nats://host:4222` installs a subset on
a host and points it at a movable backbone; `make install-backbone LISTEN=... AUTH_FILE=...`
opens the broker to the LAN (refusing to do so without auth). Validate the wiring
in docker with `make sim-distributed-validate` (no real hosts needed).

## Branch / migration runbooks

- [Deploying the cross-classifier-identity branch](cross-classifier-identity-deploy.md)
