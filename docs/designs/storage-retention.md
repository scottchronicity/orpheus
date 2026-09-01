# Storage retention

How a station decides what to delete when the disk fills, and what it refuses to
delete no matter what.

**Status: built.** `orpheus-storage-sweep` ships as a one-shot on a 15-minute
timer (`platform/orpheus-common/systemd/orpheus-storage-sweep.{service,timer}`,
engine in `orpheus_common/storage/sweep.py`). The three agents that used to
delete — audio-motion, video-motion, video-snapshotter — no longer delete
anything. The Diagnostics storage panel reads the sweep's report rather than the
agents' health payloads. The open questions below were answered with the
defaults this document proposed; each answer is recorded inline.

## The problem

Cleanup today is per-directory. Each agent compares its own directory against
`storage.retention.max_size_gb` (700 GB) and sweeps when it crosses 95%. The disk
those directories share is not per-directory, so every category can sit
comfortably inside its budget while the filesystem underneath runs out.

Measured on the production station (1.8 TB ext4, 662 GB used, 1.1 TB available):

| Category | Size | Files | Oldest | Growth | Who cleans it |
|---|---|---|---|---|---|
| `audio/audio_motion` | 77.6 GB | 26,504 | 8 days | 9.1 GB/day | audio-motion: size budget |
| `video/video_motion` | 39.2 GB | 22,829 | 3.5 months | 0.3 GB/day | video-motion: size budget |
| `video/snapshots` | 281.2 GB | 238,280 | 7 months | 1.4 GB/day | snapshotter: 547-day age purge |
| `video/timelapses` | 296.5 GB | 58,985 | 7 months | 1.5 GB/day | **nobody** |
| detections DB | 5.35 GB | — | — | 12 MB/day | nobody |

Three things follow from that table.

**Only two categories respond to disk pressure at all**, and they are the small
ones. 578 GB — 87% of everything stored — sits in snapshots and timelapses, which
the free-space guard cannot touch. Under pressure the station would delete most of
its audio and motion video while the bulk of the disk sat untouched. That is the
"deleting the wrong shit" failure, and it is the current behaviour.

**Every agent computes the shortfall independently.** Two agents each free the
whole deficit for themselves, so a 37 GB shortfall costs 74 GB of recordings.
Four categories would cost four times. No agent can see the others, so no agent
can take a fair share.

**The two categories with no effective ceiling are the ones that will fill the
disk.** The snapshotter's 547-day purge is inert until mid-2027 and settles near
750 GB; timelapses have no cleanup code at all. Together they climb ~2.9 GB/day.
Audio hits its own 700 GB trigger in about 65 days and then self-cycles
between 500 and 665 GB, claiming a third of the disk. Non-root writers hit ENOSPC
in roughly six to nine months.

## Shape: one sweeper, on a timer

One component owns every deletion. It runs as a **one-shot command on a systemd
timer**, not a resident daemon:

- Nothing to supervise, nothing to leak, no bus dependency, no memory footprint
  between runs — it matters on a board where three model agents already carry soft
  memory caps.
- No in-flight state to lose: each run reads the disk, decides, deletes, exits. A
  reboot mid-sweep costs nothing.
- **Overrun:** systemd will not start a second instance of a running one-shot
  service; the trigger is skipped and the next fires on schedule. A `flock` on
  `$ORPHEUS_DATA_ROOT/.storage-sweep.lock` covers the other direction, so an
  operator running it by hand cannot collide with the timer.
- **Cadence: 15 minutes.** At 12.3 GB/day the station moves 128 MB between runs,
  so the cadence is not about normal growth — it is about a runaway. A stuck
  ffmpeg or a retry loop writing 100× normal is still caught with the reserve
  intact. The sweep is a stat-walk plus arithmetic; on 346,000 files it costs
  seconds.

**The agents stop deleting.** `_periodic_cleanup` in audio-motion and video-motion
and the inline age purge in video-snapshotter are removed. The per-directory size
budget is not lost — it becomes the sweeper's per-category ceiling, enforced by
something that can see the whole disk. One writer of deletions is the point: two
mechanisms sweeping the same directory is how a shortfall gets double-counted.

**Transition.** The agent changes and the sweeper ship in the same release, and
the deploy updates agents before enabling the timer, so no window exists where
both run. If one does occur — a partial upgrade, an agent that did not restart —
the failure is bounded: the sweeper's ceilings match the budgets the agents were
enforcing, so the worst case is a redundant pass, not a double eviction.

## What it enforces

### Reserve

ext4 already reserves 5% (~93 GB) for root, so the box stays administrable and
loggable no matter what Orpheus does. Non-root writers — every Orpheus service —
hit ENOSPC at about 1.68 TB while that 93 GB remains.

An Orpheus-level reserve is therefore **not** what keeps the machine alive. Being
honest about what it adds: **earlier warning and a gentler failure.** Hitting the
filesystem wall means writes fail mid-clip, SQLite errors, and agents crash-loop.
Stopping short of it means the sweeper acts while everything still works.

**`storage.retention.reserve_gb: 100`.** Note that `min_free_space_percent: 10`
is also set, and the sweep takes the **stricter** of the two — so on the 1.8 TB
station described here the effective reserve is about 180 GiB, not 100 GB, and
the arithmetic in this section assumes the smaller number. `make storage-report`
prints the effective figure. At 12.3 GB/day the 100 GB figure is eight days of
runway between "the sweeper cannot keep up" and "writes start failing" — enough
for an operator to notice an alarm and intervene. It also covers what needs
temporary room: ffmpeg scratch during timelapse assembly, DB plus WAL growth, and
snapshot bursts.

### Ceilings and floors

Every category gets both: a ceiling it is trimmed back to in normal operation, and
a floor of recent history that pressure cannot take.

**The two knobs are in different units on purpose, and the table shows both.** A
ceiling is a size — "never occupy more than this much disk". A floor is a
duration — "always keep at least this much recent history". They answer different
questions, so `max_gb` is a size and `floor_days` is in **days**. The
middle columns translate each into the other at the station's current growth rate,
because that rate is the only thing connecting them.

Every size below is **GiB** (1024³ bytes) — what `df -h`, the dashboard and
`make storage-report` all show. The config keys keep their `_gb` spelling
because renaming them would silently reset the ceilings on stations that
already have them set.

| Category | Ceiling `max_gb` | Ceiling as days | Floor `floor_days` | Floor as size | Rate |
|---|---|---|---|---|---|
| `audio_motion` | **600 GB** | ≈ 66 days | **30 days** | ≈ 273 GB | 9.1 GB/day |
| `video_motion` | **60 GB** | ≈ 200 days | **90 days** | ≈ 27 GB | 0.3 GB/day |
| `snapshots` | **450 GB** | ≈ 321 days | **90 days** | ≈ 126 GB | 1.4 GB/day |
| `timelapses` | **450 GB** | ≈ 300 days | **90 days** | ≈ 135 GB | 1.5 GB/day |

The day-equivalents move as the rate moves: if audio's rate doubles, its 600 GB
ceiling becomes a 33-day window without anyone changing a setting. That is the
ceiling working as intended — see below.

**Keep the floor well clear of the ceiling.** Where the two nearly coincide, one
of them is doing no work. A 60-day audio floor would be ≈546 GB against a 600 GB
ceiling, leaving a 54 GB evictable band — effectively a fixed-size category with
no room for pressure to act. The proposed 30-day floor leaves 273–600 GB of
evictable history, which is the band the fair-share rounds draw from.

### Are ceilings necessary at all?

A fair question, since a reserve plus floors is already a complete safety story:
categories grow freely, pressure trims whatever sits above its floor, and the disk
never fills. **That design would be sufficient.** Ceilings buy two things it does
not have.

**Predictability.** Without a ceiling, "how much audio history do I have?" has no
answer independent of what the other categories did this month. With one, audio is
600 GB and the operator can convert that to days at the current rate. A recording
appliance whose retention depends on unrelated subsystems is hard to reason about
and harder to promise anything about.

**Blast-radius containment, which is the real argument.** Suppose audio's rate
doubles — a detection threshold change, a windy month, a new microphone. Under
reserve-plus-floors, audio grows until the disk hits the reserve, then the sweeper
takes the deficit from whichever categories sit furthest above their floors: audio
consumes snapshot and timelapse history to fund its own growth, silently, and the
operator discovers it as "why do I only have three months of snapshots now?".
Under ceilings, audio stops at 600 GB and **its own** history shortens from 66 days
to 33. The category that changed behaviour is the category that pays. That is the
property worth the extra knob.

The cost of ceilings is that they leave the disk deliberately not-full: at the
proposed numbers, ~82 GB of slack above the reserve that no category may claim.
That is the price of the two properties above, and it is adjustable — raising every
ceiling proportionally trades predictability for history.

Ceilings sum to 1560 GB against ~1642 GB allocatable (1762 GB non-root, less the
100 GB reserve and ~20 GB of models, backups and the database). Floors sum to
561 GB — that is what survives maximum pressure.

**The arithmetic the operator should see.** Three months of every category costs
1107 GB, which fits. What does not fit is today's policy set: snapshots settling
at 750 GB under their 547-day purge, plus timelapses growing without a ceiling,
plus audio's 700 GB budget. The disk is not too small — two categories simply have
no ceiling. Adding ceilings everywhere makes 90-day floors comfortable.

**What the operator gives up** at the proposed numbers: audio history beyond about
66 days, and snapshots capped near 10 months rather than the 18 their current
547-day setting implies. Keeping 90 days of audio instead is possible — it costs
819 GB and squeezes snapshots and timelapses to about 380 GB each, roughly eight
months apiece. That is the trade, and it is the owner's to make.

**Worth noting separately:** audio is 74% of all growth, at 3,313 clips/day — one
every 26 seconds. Tuning the detection threshold or holdoff would cut the dominant
consumer more cheaply than any retention policy.

### Eviction order

1. **Ceilings first.** Any category over its ceiling is trimmed to it, oldest
   first, regardless of how much free space there is. This is the steady-state
   mechanism and the one that runs almost every time.
2. **Then pressure, fairly.** If free space is still below the reserve, take from
   categories above their floor in rounds — a bounded chunk (512 MB) from each
   eligible category per round, oldest first, proportional to how far each sits
   above its floor. Rounds stop the moment the deficit is covered. This is the
   "one of each" the owner asked for: a category that is barely above its floor
   contributes little, one sitting far above contributes most, and no category is
   the only thing deleted.
3. **Floors are absolute.** When every category is at its floor and free space is
   still short, the sweep **does not** breach a floor. It logs at CRITICAL, emits
   an agent error the dashboard's error feed shows, and stops. The operator gets a
   loud, actionable failure instead of silently losing the recent past to a disk
   anomaly — which is the case the floors exist for.
4. `min_file_age_hours` remains a hard floor throughout: a clip still being
   written is never a candidate.

## Logs

### Correcting the premise

This section was first drafted on the belief that journald defaults to 10% of the
filesystem — ~180 GB on this disk — and was therefore a live threat. **That is
wrong, and it changes the conclusion.** `systemd-journald.conf(5)`: `SystemMaxUse=`
"defaults to 10% of the size of the respective file system, but is capped at 4G."
Journald has never been able to take more than 4 GiB by default.

The field data agrees. The journal lives on the 94 GB root filesystem, not on
`/data`; the station already has `SystemMaxUse=2G` set by hand, and is using
143 MB of it. The noisiest unit produces 3.4 MB/day. **Journald is not what fills
this disk, and was not going to be.**

Whatever once "logged so much it took up the whole disc" was therefore almost
certainly *not* journald under its defaults. The candidates that genuinely are
unbounded are worth naming, because that is where the effort belongs:

- **Docker's `json-file` driver**, which has no size limit unless one is set, on a
  box that runs the Simulacrum.
- **Any service writing its own log files** outside the journal.
- Journald on a *small* root partition, where the 4 GiB cap is most of the disk.

So the design goal shrinks: not "rescue the disk from journald", but "make sure a
runaway Orpheus service cannot drown the journal that would explain it, and do it
without rewriting the machine's logging policy."

### What is per-unit already

`LogRateLimitIntervalSec=` and `LogRateLimitBurst=` are **per-unit** directives —
no system-wide file, no namespace, nothing to opt into. Setting
`LogRateLimitIntervalSec=30` and `LogRateLimitBurst=2000` on the Orpheus units
bounds what any single agent can emit, and normal operation runs three orders of
magnitude below it. When it engages, journald records `Suppressed N messages`, so
the operator learns a flood happened and loses only the individual lines inside
that window.

**This ships regardless of what follows.** It is the whole of the per-service
protection that costs nothing and breaks nothing.

### Option A — log namespaces

`LogNamespace=orpheus` (systemd 245+) puts our units' logs in a separate journal
instance with its own `/etc/systemd/journald@orpheus.conf`, carrying its own
`SystemMaxUse` and `MaxRetentionSec`. We would bound our own logs precisely,
on every install, without touching the machine's policy — exactly the property the
owner asked for.

**The cost is the part that decides it.** `journalctl -u orpheus-agent-audio-motion`
stops working. Every command needs `--namespace=orpheus`. That breaks:

- **The dashboard's Service Logs panel**, which shells out to
  `journalctl -u <service>` (`services/orpheus_ui/backend/src/orpheus_ui/api/diagnostics.py`).
  It would return empty — a log viewer that silently shows nothing.
- **Every runbook**: `jetson-rollout.md`, `jetson-rollback.md`,
  `jetson-upgrade-checklist.md`, `cross-classifier-identity-deploy.md`,
  `distributed-portal.md`, `distributed-agents-split.md`,
  `distributed-backbone-on-nuc.md`.
- **Every quickstart and deployment doc** that shows a `journalctl` line —
  `JETSON_QUICKSTART.md`, `INSTALLATION.md`, `DEPLOYMENT.md`, plus six component
  READMEs and the agent-instruction files.
- **Agent source comments and the soak checklists** that tell an operator what to
  grep for.
- **Every support instruction ever given**, and the muscle memory of the one person
  who currently operates a station.

That is 39 files carrying 78 `journalctl` references, plus a UI feature that fails
silently rather than loudly.

**Availability makes it worse.** ADR 0004 pins the Jetson to Ubuntu 20.04, which
ships **systemd 245 — the first release that has `LogNamespace=` at all.** There is
no margin: the station runs the earliest implementation of the feature. And on any
older systemd, an unknown unit directive is *logged as a warning and ignored* — the
unit starts normally and its logs go to the default journal. So the failure mode is
**silent and open**: we would believe our logs were capped by a namespace
configuration that was never applied. A safety mechanism that fails open without
saying so is worse than no mechanism.

**Verdict: not worth it.** We would break every documented operator command and a
UI panel, on the earliest possible systemd, with a silent-failure path on older
ones — to bound something that is already bounded at 4 GiB and currently using
143 MB.

### Option B — opt-in system-wide drop-in

Keep `/etc/systemd/journald.conf.d/10-orpheus.conf` (`SystemMaxUse=2G`,
`MaxRetentionSec=2month`) but **never install it silently**:

- The deploy does not write it. `make verify-deploy` inspects the effective
  journald configuration and reports what it finds: the effective `SystemMaxUse`,
  current journal size, and whether an Orpheus drop-in is present.
- When no explicit limit is configured, it prints a **warning, not a failure**:
  what the default is, what it means on this filesystem, and the one command that
  applies our recommendation (`make install-log-bounds`).
- Warn, do not prevent. An operator who ignores it gets a bounded journal anyway,
  because the default is bounded; they just have less say in where the bound sits.
- Removing the file and restarting `systemd-journald` restores the system default,
  with nothing in Orpheus depending on it.

This keeps every `journalctl` command working, never rewrites a policy the operator
did not ask for, and still puts the number in front of them.

### Recommendation

Ship **per-unit rate limits** (no ceremony, no breakage) plus **Option B**
(warn, offer, do not impose). Skip namespaces: the operator-experience cost is
large, the version floor is exactly at the minimum, and the threat they would
mitigate is already capped by systemd itself.

Treat **Docker's `json-file` driver** as the real member of this class — genuinely
unbounded, on hardware that runs containers. Same rules: `verify-deploy` reports
it, `make` offers to set `max-size`/`max-file` in `daemon.json`, and the operator
decides.

## Root filesystem — what shipped

The Logs analysis above ended in a recommendation. This is what was built from
it, after field forensics settled two questions the analysis could only guess at.

### What the forensics found

- **rsyslog is the mechanism.** It is active and enabled, `ForwardToSyslog` is
  unset (Ubuntu's default is on), and `/etc/logrotate.d/rsyslog` rotates syslog
  daily keeping seven, with **no `size` or `maxsize`**. Between rotations the
  file is unbounded — and the archive timestamps show rotation demonstrably
  *skipped for nine to ten days* in August, so "between rotations" can mean days.
  Runaway logger → journal → mirror → `/var/log/syslog` → 94 GB root disk gone.
- **The journal on that station is volatile.** `/var/log/journal` does not exist,
  so `Storage=auto` keeps it in `/run` — RAM. The configured `SystemMaxUse=2G` is
  therefore **inert**, the journal holds roughly 27 hours in ~144 MB, and it is
  erased on every boot. Journald could not have filled that disk because it never
  touched it. It also means the evidence from the original incident was gone by
  construction, which is why nobody could say afterwards what had happened.

The second finding inverts part of the earlier recommendation: **`ForwardToSyslog=no`
on its own would be harmful here.** With a RAM-only journal it removes the only
durable copy, leaving 27 hours of history and nothing after a crash.

### What was built

Default-on, no opt-in, because none of it touches host policy:

| Bound | Value | Reasoning |
|---|---|---|
| Per-unit log rate limit | `LogRateLimitBurst=500` / `LogRateLimitIntervalSec=30s` on all 15 units (9 agents, 5 services, and the storage sweep) | systemd's default is 10,000/30s. At ~250 B/message that default permits ~5.7 GB/day *per unit*; 500/30s permits ~360 MB/day, against a measured normal load of ~35 MB/day across every agent — about 100× headroom per unit. A crash-loop traceback (RestartSec=10, ~30 lines a restart ≈ 90 per interval) passes untouched. |
| Syslog identity | `SyslogIdentifier=<unit>` on all 15 units (9 agents, 5 services, and the storage sweep) | Agents previously reached syslog as anonymous `python` and were ~90% of its volume. Attribution is half of incident response. |
| Container logs | `max-size: 20m`, `max-file: 3` on every service in both compose files | Docker's `json-file` driver is otherwise unbounded. |
| Dev-stack log files | trim at 50 MB, keep the last 2000 lines | Services append with `>>`, so the trim must truncate **in place** — renaming would leave the writer feeding the renamed inode while the visible file stayed empty. |

Opt-in, because it rewrites host-wide policy (`make install-log-bounds`), and in
this order because each step makes the next one safe:

1. `Storage=persistent` (+ create `/var/log/journal`) — turns the existing size
   cap from inert into real, and keeps forensics across the crash you want to
   investigate.
2. `SystemMaxUse=1G`, `SystemKeepFree=2G`, `MaxRetentionSec=2month` — a bound
   that now applies to something.
3. `ForwardToSyslog=no` — removes the unbounded mirror, safe only *after* step 1.

An operator who relies on `/var/log/syslog` should skip it and bound their own
rotation instead; the drop-in says so and gives the one-liner.

### What is still not bounded

- **`/var/log/syslog` on a station that does not opt in.** The rate limits shrink
  the worst case by ~20×, but the file still has no size ceiling. This is the
  residual risk, and it is deliberate: silently rewriting a host's logging policy
  is not a package's decision.
- **Anything else on the root filesystem we do not own** — the OS, apt caches,
  coredumps, another tenant's software. `verify-deploy` reports root-fs headroom
  so the number is at least visible.
- **A burst inside one rate-limit interval.** The limit caps sustained volume,
  not a single 500-message spike.
- **The `SystemKeepFree` interaction**: journald respects it, rsyslog does not.

### How an operator finds out

`make verify-deploy` reports, every run: root-filesystem free space (warning under
10%), whether each installed unit actually carries a rate limit (catching drift
between the shipped unit and the installed one), whether the journal is volatile,
and whether the opt-in drop-in is present — naming the exact command when it is
not. It warns; it never fails the target for a choice the operator is entitled to
make.

## Operator story

- **Configure:** `storage.retention.reserve_gb`, and per-category `max_gb` /
  `floor_days`. Existing keys keep working; `min_free_space_percent`, if set, is
  read as a percentage of total and the larger of it and `reserve_gb` wins.
- **See before it acts:** `make storage-report` (wrapping
  `orpheus-storage-sweep --dry-run`) prints every category with its size, ceiling,
  floor, what the next sweep would remove, and the timestamp window that would go.
  Safe to run by hand at any time — the lock file keeps it from colliding with the
  timer.
- **When it acts:** a WARNING naming the category, files and bytes removed, the
  oldest and newest timestamps removed, free space before and after, and a CSV
  manifest of every path. An operator can reconstruct exactly what disappeared.
- **Disable:** `systemctl disable --now orpheus-storage-sweep.timer`, or
  `storage.retention.sweep_enabled: false`. Both leave every file in place.

## Rollout

**On the production station today, the first run deletes nothing.** Every category
is under the proposed ceiling (audio 78/600, video 39/60, snapshots 281/450,
timelapses 297/450) and free space is 1.1 TB against a 100 GB reserve. The sweeper
reports and exits — the mechanism proves itself on real data before it ever has
cause to act.

A station shaped differently could have cause on day one, so **the first 24 hours
after install are report-only** (`first_run_grace_hours`, default 24): each sweep
writes the report, logs at CRITICAL with the command to review it, and deletes
nothing. At a 15-minute cadence that is roughly ninety-six reporting runs before
the first enforcing one. `orpheus-storage-sweep --force` ends the window early,
and does so for good rather than for one run.

**Reversibility:** additive config keys with defaults, so an existing config
parses unchanged and a rollback needs no migration.

Three things that sentence used to get wrong, and an operator reading it at 2am
deserves the accurate version:

- `sweep_enabled: false` does **not** restore the previous behaviour. The agents'
  own cleanup was removed in the same release, so switching the sweep off means
  *nothing on the station deletes recordings at all* and every category grows
  until the disk fills. It is a way to stop deletion while you think, not a way
  to go back.
- The on-disk layout **does** change: the sweep writes
  `.storage-sweep-state.json`, `.storage-sweep.lock` and `.storage-sweep-manifests/`
  under the data root. Nothing needs migrating, but they are there.
- The first-run grace lives in that state file, which sits with the data rather
  than the deployment, so it **survives a rollback**. Roll back, spend a week
  tuning ceilings, redeploy, and the grace is already spent: the first sweep
  after the redeploy enforces immediately with no review window. To get the
  window back, delete `$ORPHEUS_DATA_ROOT/.storage-sweep-state.json` before
  redeploying.

## Open questions — answered

Each was resolved by taking the default this document proposed. They are the
numbers worth a decision rather than a silent choice, so the choice is recorded
rather than left implied by the code.

1. **Audio floor — 30 days (273 GB) or 90 (819 GB)?** 90 days of audio squeezes
   snapshots and timelapses to roughly eight months each. **Answered: 30 days**,
   on the grounds that audio is 74% of growth and the clips are already
   classified. `storage.retention.categories.audio_motion.floor_days: 30`.
2. **Reserve — 100 GB?** Eight days of runway. Larger buys more warning and costs
   history. **Answered: 100 GB.** `storage.retention.reserve_gb: 100`. Stations
   configured before this key existed still have `min_free_space_percent` set, so
   the sweep reconciles the two by taking whichever is stricter — an upgrade
   cannot silently loosen a guard an operator already tightened.
3. **Journald — warn-and-offer, or leave it entirely alone?** **Answered: Option
   B**, shipped separately with the per-unit rate limits and the persistent,
   capped journal. Nothing in the sweep depends on it.
4. **Floor breach — never, or with a loud warning?** **Answered: never.** A floor
   is absolute in both directions: a ceiling it will not let the sweep reach logs
   CRITICAL and leaves the ceiling breached, and being under the reserve with
   every category at its floor logs CRITICAL and exits 2, which shows the timer's
   unit as failed. The alternative trades a guaranteed recent history for
   surviving an anomaly without operator action, and the loss is not reversible.
5. **First-run grace — one cycle (15 minutes) or 24 hours?** **Answered: 24
   hours.** `storage.retention.first_run_grace_hours: 24`. Every sweep inside the
   window decides exactly what it would delete, deletes nothing, publishes the
   report, and — only if it would have removed something — logs CRITICAL naming
   `make storage-report`. `orpheus-storage-sweep --force` ends the grace early.

### What an operator does with it

| Want | Command |
|---|---|
| See what would be deleted | `make storage-report` |
| Sweep now, outside the timer | `make storage-sweep` |
| Start enforcing before the grace ends | `orpheus-storage-sweep --force` |
| Stop every deletion on the station | `sudo systemctl disable --now orpheus-storage-sweep.timer` |
| Stop it without touching systemd | `storage.retention.sweep_enabled: false` |
| See what a past sweep removed | `$ORPHEUS_DATA_ROOT/.storage-sweep-manifests/` |

Disabling the sweep stops deletion but not measurement: it still surveys and
publishes, so the dashboard keeps showing what is growing. Silence would read as
"nothing is growing", which is how the timelapse directory reached 297 GB
unnoticed in the first place.

## Out of scope

- **Database retention.** `detections_days` is still parsed and unapplied; the DB
  grows 12 MB/day and is not a threat on this timescale. Row retention is its own
  design — deleting detections has consequences entities and the dashboard care
  about, unlike deleting a clip.
- **Age windows.** `raw_audio_days` / `raw_video_days` stay accepted and
  unapplied. Ceilings and floors are the mechanism; enforcing the age windows as
  written would delete eleven months of clips on a station whose window says 30
  days.
- **Deployment hygiene**, noted but not designed here: the root filesystem carries
  a 2.1 GB stale venv, a 123 MB quarantine directory and a 1.1 GB pip cache with
  no owner.
