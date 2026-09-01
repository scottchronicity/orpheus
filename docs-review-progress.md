# Docs review — pre-release pass

Scope: the 22 findings that block a public release, from
`~/Desktop/orpheus_docs_review1_aug31/`. The other 156 findings ship later.

Branch: `docs/pre-release-fixes`, off `summer-update`. Docs only — no code
changes in this pass.

**Batch 1 (pre-release 22): applied 21 · parked 1.**
**Batch 2 (runbooks remainder): RB-01, RB-03…RB-07, RB-10, RB-12…RB-22 applied.**

## Group 1 — runbook safety (04-runbooks.md)

- RB-02 — DONE. `orpheus-storage-sweep.timer` is now stopped in the cold-cutover
  full stop and in §3 of the rollout, re-armed in §4 and in the checklist's
  deploy block. The cutover's confirmation command dropped `--state=running`,
  which hides an armed timer (its state is `waiting`).
- RB-08 — DONE. Level 3 now copies the suspect DB and its `-wal` aside before
  the restore overwrites them.
- RB-09 — DONE. The single paste-able fence is split into four blocks with
  `BATCH` / `TARGET` / `DEPLOYED` hoisted to the top as assignments, and the
  section headings carry checkboxes.
- RB-11 — DONE. `/opt/orpheus/config/.env` is backed up in both the rollout §1
  and the checklist §1.

## Batch 2 — runbooks remainder (04-runbooks.md)

RB-01, RB-03, RB-04, RB-05, RB-06, RB-07, RB-10, RB-12, RB-13, RB-14, RB-15,
RB-16, RB-17, RB-18, RB-19, RB-20, RB-21, RB-22 — all applied.

Decisions taken without asking:
- RB-19 wanted the Ollama page **moved** out of `runbooks/`. File moves are out
  of scope, so the page stays where it is and only the "Asking an assistant to
  plan this for you" section was deleted — it was advice about writing prompts,
  not about Orpheus.
- RB-07's checklist half: `make storage-sweep ARGS=--force`, not `FORCE=1`. The
  target passes `$(ARGS)` to `SWEEP_BIN`; I checked rather than copying the
  review's phrasing.
- RB-03 introduced `$DEPLOYED` in rollout §0 and `$BATCH` in §2, and I defined
  `BATCH` where it is first used rather than leaving an undefined variable.

## Group 2 — install and deploy paths (03-operator-and-install.md)

- OP-01 — DONE (docs-side, per instruction). Both pages now point at
  `sudo ./systemd/install.sh` and state that `make update` overwrites the live
  config and currently cannot run at all. The Makefile bug itself is unfixed —
  see Notes.
- OP-03 — DONE. The Windows page gives the pinned binary download instead of
  `make install-backbone`, which is a systemd installer on the one platform the
  same page says has no systemd.
- OP-04 — DONE. The broker row is out of the "install these first" table on
  both Linux and Windows, with a note that it comes after the clone and after
  Python.
- OP-05 — DONE. macOS no longer claims `afplay`; the shipped default is
  `ffplay`, ffmpeg is no longer marked optional, and the override is named.
- OP-06 — DONE. DEPLOYMENT's first-time setup now uses `make services-install`
  instead of a hand-rolled list that omitted every classifier and the
  correlator.
- OP-07 — DONE. The credential step moved into the Configure section, before
  `make dev-stack`, on all three quickstarts — seeding is guarded on an empty
  user table, so it was unactionable where it sat.
- OP-09 — DONE. Uninstall leads with `systemctl disable --now 'orpheus-*'` and
  removes `*.timer` as well as `*.service`, so the storage-sweep timer no longer
  survives the uninstall.
- OP-14 — DONE. `orpheus-agent-video-motion` added to INSTALLATION's video
  block; DEPLOYMENT's is superseded by the `services-install` fix in OP-06.
- OP-17 — DONE. The Jetson page leads with `make services-install` and the
  per-component list keeps `audio-events`, which it had dropped.

## Batch 1b — operator/install remainder (03-operator-and-install.md)

OP-02, OP-08, OP-10, OP-11, OP-12, OP-13, OP-15, OP-16, OP-18, OP-19, OP-20,
OP-21, OP-22, OP-23, OP-24 — all applied.

Decisions taken without asking:
- **OP-02 (JetPack).** Per instruction, the quickstart no longer asserts a
  version at all. It points at `platform/jetson-orin-nx-yahboom/README.md` as
  the authority for the board's OS and JetPack, and states the Python
  requirement in terms of what `make/common_python.mk` actually enforces —
  `PYTHON_SYSTEM` defaults to `python3.9`, `PYTHON_REQUIRED_VERSION` is 3.9.5 —
  with both cases covered: use the image's interpreter if it ships one, else
  install 3.9.5 with uv and set `PYTHON_SYSTEM`.
- **OP-12** wanted `LOGGING.md` moved to Coding & Contributing. Moves are out of
  scope, so the page keeps its place and gained the four things an operator
  actually clicks "Logging" for: `journalctl`, `LOG_LEVEL`, `make dev-logs`, and
  where dev logs land.
- **OP-16** deleted three four-bullet benefit lists. Kept the one operational
  fact (a crashed agent cannot take the dashboard down) and pointed the
  reasoning at ARCHITECTURE and the ADRs.

## Batch 3 — contributing / agent instructions (08-...)

CC-01 … CC-25, CC-27 … CC-30 applied.

- **CC-26 PARKED.** It asks for a sixth audience row ("Coding agent") in
  `docs/contributing/voice-and-audience.md`. That file is explicitly off-limits
  for this pass. The finding is good and worth doing later: the standard names
  coding agents as an audience in its second sentence, then gives them no
  profile, which is why agent-facing pages drift toward contributor prose.
- CC-03 corrected a line I had introduced myself in the earlier pass — I wrote
  that four jobs are never gated; only `guardrails` is.
- CC-28 and CC-29 delete rather than rewrite: ~180 lines of generic pytest
  advice built on `Detector` / `MyFeature` symbols that exist nowhere in the
  repo, and three CI sections of four-bullet padding with unverifiable
  "Duration" figures. Both pages keep a pointer to the real thing.

## Batch 4 — architecture and ADRs (05-...)

AR-01 through AR-10, AR-16 applied, plus the ADR status discipline.

**Three index pages created** (your extra item, and AR-16): `docs/adr/README.md`
with the full status table and every superseded record marked,
`docs/designs/README.md`, and `docs/agent-instructions/README.md` — one line per
child per the hub rule. All three are in the nav, and the build now emits
`index.html` for `/adr/`, `/designs/` and `/agent-instructions/`, which is what
makes the directory links from ST-03 resolve on GitHub Pages rather than 404.

Status corrections: 0001 → Superseded, 0015 → superseded in part by 0017 (its
`"mqtt"` default is contradicted by the code), 0018 → Accepted/partially
implemented, with `Superseded in part by` back-pointers added to 0003 and 0005.

## Group 3 — front-door honesty (02-front-door.md)

- FD-01 — DONE. The comparison page's headline differentiator claimed a
  "daily active crows" count and per-individual re-identification. Neither
  ships: an entity is a same-source group of overlapping observations
  (ADR 0013), there is no daily bucketing on the Crows page, and grep across
  the UI finds no such metric. Replaced with what the correlator actually does.
- FD-02 — DONE. "Trivially extensible … no changes required elsewhere" is
  contradicted by the repo's own add-an-agent recipe, which exists because
  agents shipped half-wired. The decoupling claim is kept; the wiring is now a
  named checklist.
- FD-03 — DONE. The README's three-step CI checklist was a drifted copy missing
  three of the six required edits. Replaced with a link to the canonical list.
- FD-05 — DONE. index.md promised all four quickstarts reach a working
  dashboard; the README and the macOS page both say two are unverified.

## Group 4 — README voice pass (02-front-door.md)

- FD-11 — DONE. "Engineering Highlights" was three paragraphs of unverifiable
  self-assessment about the author's own code — "design sensibility", "the key
  insight", "most implementations reach for X; this one is cleaner", with no
  cost stated anywhere. Reduced to three one-line pointers under "Where to
  start reading".
- FD-12 — DONE. All four spots: the marketing H2 between the H1 and the real
  description, "incredible work" in an attribution section, "utilizes" → "uses",
  and the closing rule-of-three tagline the page had already said properly at
  the top.

## Group 5 — dead links (01-site-and-links.md)

- ST-02 — DONE. 13 links across seven pages repointed at the published site
  pages: `../CONTRIBUTING.md` → `contributing.md`, `../AGENTS.md` →
  `agents-index.md`, and the same treatment for CHANGELOG / SECURITY / README.
  Verified in the built HTML — a quickstart now renders `href="../contributing/"`.

  Deliberately **not** touched: `docs/contributing.md` and `docs/agents-index.md`
  contain `{! include-markdown "../CONTRIBUTING.md" !}` — those are filesystem
  paths for the plugin, not links, and rewriting them would break the build.
  Also skipped `docs/README.md` (excluded from the build; the link is correct
  for a GitHub reader) and `docs/copilot-workspace-instructions/` (not in nav,
  not named in the finding).

- ST-03 — PARTIAL. Fixed the four links that are wrong purely by depth:
  `agent-instructions/20-architecture.md` (`../designs/`, `../adr/`) and
  `40-deployment.md` (`../runbooks/`) now use `../../`. Two rows of the
  finding's table did not exist on disk — `whats-new` and `operator-manual`
  have no bare `runbooks/` link. The remaining rows are parked, below.

## Batches 6-8 — front door, site mechanics, and the tail

FD-04, FD-06 through FD-10, FD-13, FD-14, FD-17 through FD-20; ST-01, ST-04,
ST-05; AR-11 through AR-15, AR-17 through AR-29; DA-08 through DA-22; DB-01
through DB-21.

The link work is worth naming: source-tree pointers are now absolute GitHub
URLs, which resolve from all three reading modes, and `docs/_hooks.py` gained
the other half — links between root files, which get inlined into stub pages
under different names, now rewrite to the page that publishes them. With those
fixed there was no reason to keep link validation off, so
`validation.links.not_found` is `warn` rather than `ignore`. Under `--strict`
that makes a broken relative link fail the build. The count is zero, which also
answers the ST-03 question parked in the earlier pass.

## Questions

1. **ST-03, the root-file rows — how should `docs/adr/` links behave on both
   surfaces?** `CONTRIBUTING.md`, `AGENTS.md` and `README.md` are read on GitHub
   *and* inlined into the site. On GitHub their `docs/adr/` links are correct.
   On the site, `docs/_hooks.py` rewrites `](docs/` → `](`, giving `adr/`, which
   from `/orpheus/docs/contributing/` resolves one level too deep and 404s.
   There is no single relative path correct on both surfaces, so this needs
   either a smarter rewrite in `_hooks.py` or an index page to link instead —
   both code/config changes, and outside a docs-only pass.

2. **`adr/`, `designs/` and `agent-instructions/` have no index page.** The
   ST-03 path fix now points at the right location, but there is no page there.
   The review recorded these as returning 200, which is true of the local
   preview — `http.server` renders directory listings — and will **not** be true
   on GitHub Pages. The review's own note says the durable fix is an index page,
   which is AR-16 and not in this pass. Worth settling before release: it is the
   difference between a working link and a 404 on the public site.

## Notes

Noticed while working, not acted on — none are in this pass.

- **OP-01 is a real Makefile bug, still unfixed.** `platform/orpheus-common`'s
  `force-update-config` copies `config/orpheus.yaml` relative to its own
  directory, which does not exist — the repo's only config dir is `config/` at
  the root. `make update` aborts on the `cp` and never reaches the restart. The
  same Makefile reaches the root config correctly at line 113 as
  `../../config/orpheus.example.yaml`. The docs now steer around it; the target
  is still broken for anyone who runs it.
- **`README.md` has a doubled horizontal rule** (two consecutive `---`) above
  what is now "Where to start reading". It predates this pass.
- **RB-09's fix is a larger diff than its neighbours.** Splitting the
  checklist's single bash fence into four blocks *is* the fix — the danger was
  that the block invited a wholesale paste — but it touches more lines than the
  other three findings in that group combined.
- **The Jetson quickstart still says JetPack 5.x** (OP-02, not in this pass)
  while `platform/jetson-orin-nx-yahboom/README.md` says JetPack 6.0+ on Ubuntu
  24.04, whose system Python is 3.12. The page also forbids installing Python
  via uv, which on JetPack 6 would be the only way to get 3.9.5. Two pages
  disagree about the reference hardware, and settling it needs a fact I cannot
  get from the tree.
