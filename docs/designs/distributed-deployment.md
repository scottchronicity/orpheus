# Distributed Deployment: home-lab ops layer

**Status:** Implemented — E1–E7 shipped (`make install-host` / `make install-backbone`,
per-host `.env` backbone wiring, the `check-installable` CI guard, compose validation
via `make sim-distributed-validate`, and the distributed runbooks); E8 stays deferred
by design. Single-host local-YAML deployment stays the default; everything here is
additive and reversible to today's exact behavior.

**Builds on** [ADR 0018](../adr/0018-distributed-backplane-and-config-service.md)
(topology-as-config; per-host `nats_url`; loopback default; remote listener
requires TLS+auth) and [the distributed/config-service design](distributed-and-config-service.md)
(Phase sequencing). This doc does **not** restate those — it specializes them
into a concrete, testable **ops layer**: the make targets, the docker-compose
validation, and the runbook set the owner asked for. Where this doc and ADR 0018
disagree on what's left to build, **this doc is corrected against the tree** (see
§5: the cold-broker mechanism is already shipped; the gap is factory plumbing).

---

## 1. Design decisions

The owner walks host-to-host installing **subsets** of the services, each
pointing back at the NATS/JetStream backbone. The backbone may live on the Jetson
or on a separate NUC; the read-only portal may be its own host. These decisions
make that real without a config daemon and without disturbing the single-host box.

### D1 — Composition is explicit per host; the Makefile is role-free; runbooks name the recipes

The operator declares, per host, exactly which components run there and where the
backbone is:

```
make install-host COMPONENTS="crow-detection bird-detection event-correlator" \
                  BACKBONE=nats://nuc.local:4222
```

We reject a fixed **role enum** (`PROFILE=agents-only | backplane+services`, the
deferred idea in ADR 0018 §"install profiles") in the *build system*:

- A role enum is a second naming system you must keep correct as components are
  added; `COMPONENTS="..."` **is** the mapping — nothing to sync. ADR 0018 says
  "topology is config, never code"; a role enum smuggles topology back into code.
- Home-lab subsets are combinatorial (2^n) and a moving target. Naming a handful
  guarantees next month's real subset isn't on the list. Explicit composition has
  no "not on the list" failure mode.
- It degrades to today with zero new vocabulary: `make install` (unchanged) is
  the all-in-one; there is no "default role" to define.

The honest cost — you can't say "the standard agent box" in one word — is paid in
**documentation, not code**: the runbooks (§4) name the blessed topologies in
prose and give each a one-line `install-host` invocation. Humans want named
recipes; the build system wants an explicit list.


### D2 — Backbone placement: a deliberate choice, defaulting to "wherever the DB is"

The backbone is the NATS/JetStream broker. It may run on the Jetson or the NUC —
the software does not care; `install-backbone` runs the broker wherever it's
invoked. The **recommended** co-location, encoded only as runbook guidance:

- Put the broker **with the `event-correlator` + UI + DB** on one host. The
  correlator writes the DetectionDB and the UI reads it; co-locating keeps the DB
  on one box (the contention concern → resolved by a read-only mirror for remote
  readers). This is the "backbone box" in the headline split.
- `event-correlator` placement is a **judgment call, not a law**. It is correct
  with the DB for the contention split; a future heavy-correlation workload could
  want it standalone. We do not build for that now (YAGNI) — `install-host` makes
  it a one-word change if it ever matters.
- The `event-correlator` systemd unit hard-orders `After=/Wants=
  orpheus-backplane.service orpheus-agent-bird-detection.service
  orpheus-agent-crow-detection.service`. On a split where detectors are remote,
  those `Wants=` are **inert but latent coupling** — not "cosmetic." `After=` on a
  missing unit is a no-op and `Wants=` on a missing unit is a no-op, so the split
  works; but if someone later co-locates a detector on the backbone, the stale
  `Wants` resurfaces and re-introduces ordering. We **defer** the fix (drop-in
  `topology.conf` "when a 2nd host is real" — ADR 0018) and **document** the
  latency, rather than calling it harmless.

### D3 — Config model: per-host `nats_url` in the existing `.env` EnvironmentFile; default local

The per-host secret — *where is the backbone* — is the env var
`ORPHEUS_EVENT_BUS__NATS_URL` (double underscore), the seam ADR 0018 mandates and
the Simulacrum already proves (`docker/orpheus.sim.yaml`). The override chain
is shipped and end-to-end:

- `EventBusConfig.nats_url` defaults to `nats://127.0.0.1:4222`
  (`config.py::EventBusConfig`).
- `_apply_env_overrides()` splits `EVENT_BUS__NATS_URL` on `__` into
  `event_bus.nats_url` (`config.py::_apply_env_overrides`), applied **after** YAML so env wins
  (`config.py::OrpheusConfig.load`).
- `NatsBus._server_list()` comma-splits for failover (`event_bus_nats.py::NatsBus._server_list`).

**We reuse the existing host-local env-file convention, not a new file.**
`orpheus-gps.service:15-16` already reads **two** optional files —
`EnvironmentFile=-/opt/orpheus/config/.env` and `EnvironmentFile=-/.env`. So
`/opt/orpheus/config/.env` is the established per-host env surface. `install-host`
writes `ORPHEUS_EVENT_BUS__NATS_URL=...` into **that** file (idempotent
upsert of the one key), and every role-member unit gets the **same**
`EnvironmentFile=-/opt/orpheus/config/.env` line gps already uses. One
convention, one file. (An earlier draft proposed a separate `topology.env`/
`backbone.env`; that fragments per-host config into two files an operator must
disambiguate — rejected. Reuse the one that exists.)

The leading `-` makes the file optional: **absent file ⇒ no env var ⇒ code
default `127.0.0.1:4222` ⇒ single-host byte-identical to today.** That is the
reversibility floor. There is no `bootstrap.yaml` and no config daemon (ADR 0018
rejects both); shared config still comes from `/opt/orpheus/config/orpheus.yaml`,
and only the one host-specific secret lives in `.env`.

### D4 — Security posture: LAN-trust v1; remote listener gated; TLS/auth owner-managed

- **v1 = trusted home LAN.** A `sensor-node` pointing at a backbone over the LAN
  may defer TLS — the owner accepts this for a trusted segment.
- **The one software guardrail:** the broker installer **refuses to enable a
  `0.0.0.0` listener without an auth file present** (ADR 0018). The shipped
  loopback `nats.conf` is never edited; opening the listener selects a separate
  `nats.distributed.conf`. Monitoring (`:8222`) stays loopback **in that file**,
  not merely as a runbook check.
- **TLS/auth/cert lifecycle and any reverse proxy are owner-managed.** Runbooks
  *mention* where they belong (one line, a pointer) and **do not detail** them.
  For an untrusted segment, TLS+auth is mandatory before opening the listener; the
  refusal gate keeps an accidental open broker from shipping silently.

### D5 — Everything additive and reversible

`make install` / `services-install` are untouched. New targets are pure additions.
The unit edit is one optional `-` line. The remote listener is a separate file.
Per-host rollback is one delete (`.env` line or file) + restart → loopback. No
schema change, no data migration.

---

## 2. Makefile target spec

Two new root-level targets, both thin dispatchers over the **existing**
per-component `install-<name>` (`Makefile:103-167`) and per-component
`install-service` sub-targets (`make/common_service.mk`). No new install
engine, no per-component conditionals inside sub-Makefiles. `install`
(`Makefile:100`) and `services-install` (`Makefile:614-630`) stay exactly as they
are.

### 2.1 The canonical component set

Short-names are the suffixes the existing `install-<name>` rules already use. The
authoritative project list is `PYTHON_PROJECTS`/`ALL_PROJECTS` (`Makefile::PYTHON_PROJECTS`/`ALL_PROJECTS`),
but those hold **paths** (`agents/orpheus-agent-bird-detection`), not short-names.
So a short-name↔path map is genuinely **new** here — be honest about it (an
earlier draft over-claimed "the list already exists"; it exists as paths, the
short-names are a new, factored-once mapping). The map is the same `-C <path>`
each `install-<name>` rule already hardcodes; we factor it once as `dir_of`:

```makefile
# Canonical installable component short-names (single source for validation).
INSTALLABLE := common ui gps audio-motion audio-playback audio-events \
               video-motion video-snapshotter video-timelapser \
               bird-detection crow-detection event-correlator \
               bluetooth-autoconnect
```

**`bluetooth-autoconnect` is included.** `services-install` (`Makefile:614-630`)
installs it (BT-speaker autoconnect; pairs with `audio-playback`). It is
**service-only** — it has a systemd unit but no dev `install-<name>` target — so
`install-host` installs it via `install-service` only (no dev-venv step). Omitting
it (as both candidate drafts did) silently drops a real service from any host that
does playback; this set is the full 14 minus the broker (the broker is
`install-backbone`, §2.3).

### 2.2 `install-host COMPONENTS="..." [BACKBONE=nats://host:4222]`

**Args:**
- `COMPONENTS` — space-separated short-names. **Required.**
- `BACKBONE` — `nats://host:port` (comma-list allowed for failover). Optional;
  **absent ⇒ loopback default = today's behavior.**

**Order of operations (root-safety first — see §2.4):**
1. **Validate** every name in `COMPONENTS` against `INSTALLABLE`. Unknown name ⇒
   `exit 2` with the valid list printed, **before any install runs** (a typo never
   half-installs a box). Name validation only — **no topology-sanity check** (KISS;
   the agent-guided runbook owns "is the backbone reachable?").
2. **Run the non-root install steps** — `install-common` always, then each
   requested `install-<name>` (dev venv). These inherit the existing root
   rejection (`platform/orpheus-common/Makefile:40-44` et al).
3. **Write `.env`** (`upsert-backbone-env`, §2.5) **only when `BACKBONE` is set** —
   and only *after* the non-root steps, so a `sudo`-tripped run can't leave a
   half-written `.env` orphaned.
4. Run each requested `install-service` (systemd; sudo internal to the script),
   `common` first.

```makefile
install-host:
	@test -n "$(COMPONENTS)" || { echo "ERROR: COMPONENTS=... required"; exit 2; }
	@for c in $(COMPONENTS); do \
	  echo "$(INSTALLABLE)" | tr ' ' '\n' | grep -qx "$$c" || \
	    { echo "ERROR: unknown component '$$c'. Valid: $(INSTALLABLE)"; exit 2; }; \
	done
	@$(MAKE) install-common                      # shared lib, non-root, always
	@for c in $(COMPONENTS); do \
	  [ "$$c" = common ] && continue; \
	  [ "$$c" = bluetooth-autoconnect ] && continue; \
	  $(MAKE) install-$$c || exit $$?; \
	done
	@$(if $(BACKBONE),$(MAKE) upsert-backbone-env BACKBONE="$(BACKBONE)")
	@$(MAKE) -C platform/orpheus-common install-service
	@for c in $(COMPONENTS); do \
	  [ "$$c" = common ] && continue; \
	  $(MAKE) -C $$(call dir_of,$$c) install-service || exit $$?; \
	done
	@echo "Installed subset: $(COMPONENTS) -> backbone $${BACKBONE:-loopback default}"
```

`common` is always installed first (mirrors the ordering at `Makefile:616,
703-727` and `install-service.sh`). Each agent venv is self-contained, so
there is **no forced cross-component install dependency** — `event-correlator`
does **not** drag in detectors (it consumes their events over NATS from another
host; that's the whole point of subsets). This is install dependency only, not
runtime topology.

### 2.3 `install-backbone [LISTEN=...] [AUTH_FILE=...]`

A friendlier alias over the existing broker install (`install-backplane` →
`install-python` is broker-only; `Makefile:164-167`) plus the broker
`install-service` and the listener gate:

1. Delegate to `make -C services/orpheus-backplane install-service`.
2. **Default = shipped `nats.conf`** (loopback `127.0.0.1:4222`, never edited).
3. If `LISTEN` exceeds loopback, select `nats.distributed.conf` and **refuse to
   enable without `AUTH_FILE`** present (ADR 0018). `:8222` stays loopback in that
   file. On a trusted LAN the owner may defer TLS; the refusal-without-auth gate is
   the floor (D4).

Named `install-backbone` to match the owner's vocabulary and to read correctly
when the broker is the only thing on a host (the NUC case).

### 2.4 Root-safety contract for the new targets

`make install` rejecting root is preserved: `install-host`'s dev steps call
`install-<name>` → per-component `install` (root-rejected); its systemd steps call
`install-service` → `sudo bash systemd/install-service.sh` (sudo internal). **Do
not run `install-host`/`install-backbone` as root.** Validation + name checks run
first, and `.env` is written only after the root-sensitive dev steps, so a
mistaken `sudo make install-host` trips the existing rejection inside
`install-common` **before** anything is written — no orphaned `.env`, no partial
state.

### 2.5 `upsert-backbone-env`

Idempotently sets the single key in the existing file:

```
# /opt/orpheus/config/.env  (managed key; file may hold other host-local vars)
ORPHEUS_EVENT_BUS__NATS_URL=nats://nuc.local:4222
```

Absent `BACKBONE` ⇒ not called ⇒ nothing written ⇒ loopback default. Rollback =
remove the key (or the file) + restart.

### 2.6 CI guard (anti-rot)

The component set is curated and can drift. Add a CI check that asserts **every
component installed by `services-install` (`Makefile:614-630`) appears in
`INSTALLABLE`** (and vice-versa, modulo the broker). This is broader than "every
`install-<name>` appears" — it catches **service-only** components like
`bluetooth-autoconnect` that have no dev `install-<name>` target, which is exactly
where the first draft's omission hid.

---

## 3. docker-compose validation (how the Makefiles get "tested")

`docker-compose.dev.yml` already proves the *mechanism* — `fleet` agents reach a
non-loopback broker by hostname (`docker/orpheus.sim.yaml`,
`docker-compose.dev.yml`). It does **not** prove (a) the backbone as a
separately-addressable host found by a stable name decoupled from compose service
discovery, (b) a *partial* fleet pointing at a backbone "elsewhere" driven by the
**production** env seam, or (c) cold-broker reconnect.

Add a small **overlay** (`docker-compose.distributed.yml`) — not a rewrite —
plus `sim-distributed-*` targets mirroring `sim-*` (`Makefile:674-695`):

1. **Backbone as a named host.** Give `orpheus-backplane` a network alias
   (`backbone-nuc`) so agents resolve it by a stable name standing in for a real
   hostname, not the compose service name.
2. **Subset = a service group that omits the rest**, e.g. an "audio host"
   (`audio-motion audio-events`) and a "corvid host"
   (`crow-detection bird-detection event-correlator`). Drive each via the
   **production env seam** so the test exercises the literal string `install-host`
   writes:
   ```yaml
   environment:
     ORPHEUS_EVENT_BUS__NATS_URL: "nats://backbone-nuc:4222"
   ```
   This closes the Makefile↔runtime loop (the exact `config.py` override
   path, not a compose-only YAML shortcut).
3. **Movable backbone.** Point the alias at a different service to simulate
   "backbone on the Jetson" vs "on the NUC" — same agent config, different URL,
   proving topology is just the URL.
4. **Cold-broker / reconnect — the teeth.** Start a subset **before** the
   backbone; assert the agent comes up "disconnected" and attaches when the
   backbone appears. **This test passes only once the §5 E3 factory plumbing
   lands** — it asserts config→factory→bus, not bus internals (which are already
   tested at `test_event_bus_nats.py` (the cold-broker tests)).

```
make sim-distributed-up        # backbone alias + subset groups via env URL
make sim-distributed-validate  # cross-"host" pub/sub + cold-broker reconnect
make sim-distributed-down
```

CI runs **both** `sim-up` (single-host default, unchanged) and
`sim-distributed-up` so the split can't regress the monolith. No Jetson required.

---

## 4. Runbook set plan

The Makefile is role-free; the **runbooks name the blessed topologies**. Each is
its own file under `docs/runbooks/` (the repo convention,
`cross-classifier-identity-deploy.md`), one named recipe = one
`install-host`/`install-backbone` invocation set + verification. Reverse-proxy/TLS
are **mentioned, not detailed** (owner-managed).

| # | Runbook | Backbone on | Essence |
|---|---|---|---|
| 0 | All-on-Jetson (today, default) | Jetson, loopback | `make install` — unchanged baseline; the rollback target. A one-line pointer added to `DEPLOYMENT.md`, not a new file. |
| 1 | `distributed-backbone-on-nuc.md` | NUC | NUC: `install-backbone`; Jetson: `install-host COMPONENTS="<sense+act+correlator>" BACKBONE=nats://nuc:4222` |
| 2 | `distributed-agents-split.md` | one host | Same `install-host` on two boxes (audio box + video box) with the same `BACKBONE=`. Short variant of #1. |
| 3 | `distributed-portal.md` | wherever | Portal box: `install-host COMPONENTS="ui" BACKBONE=nats://backbone:4222` (UI unit reads the DB directly, `orpheus-ui.service:3-4`; this is where the read-only DB mirror lands). |

The runbooks are written and in the nav:
[backbone on the NUC](../runbooks/distributed-backbone-on-nuc.md),
[agents split across hosts](../runbooks/distributed-agents-split.md), and
[the portal on its own host](../runbooks/distributed-portal.md). `install-host`,
`install-backbone` and `nats.distributed.conf` all exist. The skeleton below is
the template they were built from.

### Skeleton — `docs/runbooks/distributed-backbone-on-nuc.md`

```
# Runbook: Backbone on the NUC, sensing + correlation on the Jetson

## Preconditions
- NUC + Jetson on the same LAN; Jetson resolves nuc.local (or use the IP).
- git pull on both; `make check-models` on the Jetson (it holds the models).
- Trust tier: trusted home LAN may defer TLS (owner-managed); an untrusted
  segment needs TLS+auth BEFORE opening the listener (details: owner-managed).

## Step 1 — Backbone (on the NUC)
  make install-backbone LISTEN=0.0.0.0 AUTH_FILE=/opt/orpheus/config/nats.auth
  # The installer REFUSES a 0.0.0.0 listener without an auth file (ADR 0018).
  # nats.auth = a NATS `authorization {}` block (user/pass + per-role subject
  # permissions). Obtain from the owner; this runbook does not generate creds.
  make -C services/orpheus-backplane service-start
  Verify: curl -s http://127.0.0.1:8222/healthz   # monitoring stays loopback

## Step 2 — Agent subset (on the Jetson)
  make install-host \
    COMPONENTS="audio-motion audio-events bird-detection crow-detection event-correlator" \
    BACKBONE=nats://nuc.local:4222
  # Upserts ORPHEUS_EVENT_BUS__NATS_URL into /opt/orpheus/config/.env.
  make services-start    # or start only the installed units

## Step 3 — Verify the split
  Jetson: journalctl -u orpheus-agent-crow-detection -f
    -> "Connected to NATS url=nats://nuc.local:4222" (NOT 127.0.0.1)
  NUC: correlator emits EntityEvents; UI (:8082) shows live detections.
  Restart the broker briefly; confirm agents reconnect (NatsBus retry loop).

## Step 4 — Reverse proxy / TLS (pointer only)
  Exposing the UI/portal off-LAN: front it with your reverse proxy + TLS.
  Owner-managed; out of scope.

## Rollback (reversible)
  Jetson: remove ORPHEUS_EVENT_BUS__NATS_URL from /opt/orpheus/config/.env
          (or the file) + `make services-restart`
    -> agents fall back to loopback default; single-host behavior restored.
  Full revert: re-run `make install` on the Jetson.
```

The agent-walkthrough is exactly this: pick the topology runbook → run one target
→ set `BACKBONE=` → verify → (rollback known).

---

## 5. Software gaps → sequenced flywheel epics

Ordered: **make-target work first, then compose validation, then runbooks.**
Each is `[small]`/`[big]` with file:line and builds on what exists. Corrected
against the tree — note E3 is **narrower** than both candidate drafts claimed.

| # | Epic | Size | Evidence (file:line) | Work |
|---|---|---|---|---|
| **E1** | `install-host` + `install-backbone` + `upsert-backbone-env` + `dir_of` + `INSTALLABLE` | **big** | `Makefile::install` (fixed set), `Makefile::services-install`, `:103-167` (per-component targets), `:29,31` (paths, not short-names) | Add the dispatcher targets (§2). Validate names; root-safety order (§2.4); reuse `.env` (§2.5). Add to `.PHONY`. |
| **E2** | Units read the existing `.env` EnvironmentFile | **small** | `orpheus-agent-bird-detection.service:1-21` (no `EnvironmentFile=`); only `orpheus-gps.service:15-16` has the two `.env` lines | Add **one** optional line `EnvironmentFile=-/opt/orpheus/config/.env` to each role-member unit (agents + correlator + ui), mirroring gps. Missing file = no-op = loopback. Prefer a shared drop-in template installed by `install-service` over hand-editing 13 units (one lift, not N one-offs). |
| **E3** | Thread `connect_required` config → factory → bus | **small** | **Mechanism already shipped + tested**: `event_bus_nats.py`; `test_event_bus_nats.py` (the cold-broker tests). **True gap:** `event_bus.py::_make_nats_bus` `_make_nats_bus()` builds `NatsBus(url, client_id=…, will_topic=…, will_payload=…)` and **never passes `connect_required`** → it stays `True` → cold-broker path is dead code in prod. `EventBusConfig` (`config.py`) has no such field. | Add `EventBusConfig.connect_required: bool` (default `True`); pass it in `_make_nats_bus`. What shipped is simpler than the host-derived rule this originally proposed: the field is `Optional[bool] = None`, and unset means **never fatal on any URL**, loopback included — a restart before the broker is up self-heals. Set `true` to hard-fail instead. This is the design's **only genuine code change** — and it is ~2 lines + one field, NOT the multi-part NatsBus hardening both drafts billed. |
| **E4** | CI guard against role/component rot | **small** | §2.6; first-draft blind spot = service-only `bluetooth-autoconnect` | Assert every `services-install` component ∈ `INSTALLABLE` (covers service-only units), and every `INSTALLABLE` agent appears in `services-install`. |
| **E5** | `nats.distributed.conf` + listener-refusal gate | **big** | `services/orpheus-backplane/config/` holds only `nats.conf`+`mosquitto.conf`; no distributed conf | Add `nats.distributed.conf` (`listen: 0.0.0.0:4222`, `:8222` loopback baked in, TLS+auth placeholders). `install-backbone` selects it on `LISTEN` and **refuses without `AUTH_FILE`** (ADR 0018). Loopback `nats.conf` never edited. |
| **E6** | docker-compose distributed overlay + `sim-distributed-*` | **big** | `docker-compose.dev.yml` (service-name-only net; no alias/external net); `Makefile:674-695` (`sim-*`) | Add `docker-compose.distributed.yml` (network alias, subset groups via env URL) + targets (§3). The cold-broker test here is what proves E3. CI runs `sim-up` AND `sim-distributed-up`. |
| **E7** | Write the runbooks | **small** ×3 | §4; depends on E1+E5 | Author runbooks #1–#3 + the `DEPLOYMENT.md` pointer once the targets exist. |
| **E8** | Correlator unit topology drop-in (deferred) | **small** | `event-correlator.service:3-4` `After=/Wants= …detectors` | "When a 2nd host is real": `<unit>.service.d/topology.conf` drop-in to drop the stale local detector `Wants` on a backbone box. Inert-but-latent today (D2) — don't fix preemptively. |

**Sequence:** E1 → E2 → E3 → E4 (make layer; E1–E4 make the trusted-LAN split
*deployable and robust*) → E5 (untrusted-segment listener) → E6 (validation;
proves E3) → E7 (runbooks) → E8 (deferred). E1–E4 are the "now" bucket; E5/E8 are
the "when a 2nd host is real / human-gated" bucket (ADR 0018 sequencing). E3 has
the teeth — without it, any distributed topology is brittle to a broker restart.

---

## 6. Owner-gates

1. **Trusted-LAN deferral is owner-accepted.** A sensor-node pointing at a
   `0.0.0.0` backbone with user/pass on a home LAN is fine *only because the owner
   says so*. The moment that segment is untrusted, E5's TLS/auth/cert lifecycle is
   mandatory and is **not automated here** — owner-owned. The listener-refusal gate
   is the one guardrail that prevents an accidental open broker.
2. **`/opt/orpheus/config/.env` is unencrypted on disk.** Holds a URL today;
   possibly creds once TLS lands. Acceptable on a trusted LAN per D4; otherwise the
   owner's TLS/auth layer carries the secret burden.
3. **`nats.auth` content is owner-supplied.** The runbook states the floor (NATS
   `authorization {}` block) but does not generate credentials.
4. **No GitHub pushes / no deploys without explicit permission** (standing rule).
   These epics land as revertible commits; the Jetson/NUC tail is human-gated.
