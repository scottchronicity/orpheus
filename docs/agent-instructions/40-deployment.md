# 40 — Deployment

Operator-side procedures live in
[`docs/runbooks/`](https://github.com/scottchronicity/orpheus/blob/main/runbooks/). This file orients you when an agent
needs to think about deployment (rare — mostly tests + design).

## The current major deploy

[`docs/runbooks/cross-classifier-identity-deploy.md`](../runbooks/cross-classifier-identity-deploy.md)
is the operator runbook for the cross-classifier-identity work
shipping in the `detectallanimals` branch. Walks through:

- Pre-deploy backup
- Pull + install (`git pull && git lfs pull && make install`)
- Auto-running schema migrations
- Optional backfill of legacy detections via
  [`tools/maintenance/backfill_root_event_ids.py`](https://github.com/scottchronicity/orpheus/blob/main/tools/maintenance/backfill_root_event_ids.py)
- Service restart order — the runbook owns it
- Verification (Diagnostics page, Entity drawer, /equivalences page)
- Rollback (forward-compatible — new columns/tables stay unused on
  old binary)
- Tuning (orpheus.yaml knobs)

## Target environments

- **Jetson Orin NX** — production. ARM64, Tegra GPU, 16 GB RAM.
  Systemd-managed services. ORPHEUS_DATA_ROOT=/data/orpheus.
- **Mac dev box** — development. x86_64 (Intel) or ARM64 (Apple
  Silicon). Locally-launched processes. ORPHEUS_DATA_ROOT often
  ~/data/orpheus.

Code must work on both. Use `$ORPHEUS_DATA_ROOT` for all persistent
paths. Don't hardcode `~/...` or `/data/orpheus`.

## Systemd unit files

Each agent has its own unit file at `agents/<agent>/systemd/*.service`.
Template in [`30-recipes-adding-agent.md`](30-recipes-adding-agent.md).

Service install via `make services-install` (sudo).

## LFS pull on Jetson

The Jetson must have Git LFS installed and run `git lfs pull` to
fetch the model checkpoints from `artifacts/models/`. The PANNs
checkpoint is 312 MB.

If LFS is missing, model load fails with a confusing "PyTorch can't
unpickle" error. Always check `git lfs pull` ran cleanly before
investigating model errors.

## See also

- [`docs/runbooks/cross-classifier-identity-deploy.md`](../runbooks/cross-classifier-identity-deploy.md)
- [`docs/DEPLOYMENT.md`](../DEPLOYMENT.md) — general Orpheus deployment
- [`docs/JETSON_QUICKSTART.md`](../JETSON_QUICKSTART.md) — Jetson-specific
  setup
- [`30-recipes-adding-agent.md`](30-recipes-adding-agent.md) — systemd
  unit-file template
