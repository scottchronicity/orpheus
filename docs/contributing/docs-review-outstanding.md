# Documentation review — what is still outstanding

A nine-agent adversarial review covered all 82 published pages on 2026-08-27.
Most findings were applied (see `git log --grep=docs` around that date). This
file is what was deliberately **not** applied, so the next pass does not have to
re-derive it.

## Scope fence — read before editing

**The project's thesis, name, positioning and taglines are not editorial
territory.** Orpheus is a cross-species communication research platform; that is
what was built, and the playback path exists. The absence of a shipped
responding policy in this repo is **not** grounds to call the framing
overclaimed or aspirational. The same goes for "closed loop" and every other
identity statement. Reviewers who flag these are wasting the owner's time.

`docs/contributing/voice-and-audience.md` is the house style guide: the standard
to measure pages against, not a document to critique.

"Hyperbole" means **mechanisms dressed up** — a dry-run flag given a bolded
slogan, glob patterns called "intelligent". "Unsupported" means **checkable
factual specifics** — numbers, benchmarks, costs, competitor claims. Neither
means the premise.

## Calibration — do not re-derive

Generic LLM slop is **absent** from this site. Tree-wide greps for "seamless",
"robust", "delve", "testament to", "at its core", "That said," return nothing.
An agent hunting the standard slop list will report a clean site and be wrong.
The tells here are house-specific:

- **Em-dash density.** `index.md` ran 40.5 per 1,000 words; several sentences
  carry two. `whats-new-testing-tour.md` 27, `user-guide/index.md` 19.
- **Honesty-performing adverbs.** "exactly" ×48, "actually" ×38,
  "honest/honestly" ×27, "deliberately" ×18, "genuinely" ×17 across `docs/`.
  The site performs its own candour often enough to become a tic.
- **Heading-restating openers** and "enables:" capability lists — concentrated
  in the two unrevised legacy pages, `ARCHITECTURE.md` and `CI_WORKFLOWS.md`.
- **A triad reused verbatim** across pages: "a bird specialist, a corvid
  specialist, a general sound classifier".
- **Verbosity in the wrong container** — 150–200 word table *cells*, and prose
  narrating a dashboard panel that a reader can see faster than they can read
  about.

## Owner decisions, not editing tasks

1. **Hardware pricing** (`comparison.md`). The old figures ($600–900 Orin NX
   "developer kit", ~$100 BirdNET-Pi build) were stale enough to mislead a
   purchase, and NVIDIA does not sell an Orin NX dev kit — it is a module plus a
   third-party carrier. Specific numbers were removed rather than replaced with
   unverified ones. Someone with current prices should put real figures back.

2. **`adr/0010` publishes the station's GPS coordinates** (43.9525, -84.7),
   plus the operator's home directory path, the Jetson hostname, per-channel mic
   identity, and a 39.5-hour log of what is audible there. ADRs 0002/0003 add
   the camera hostnames. Nothing is wrong; it is a deliberate call to make
   before the repo is public, not a discovery afterwards.

3. **Whether the 11 design docs belong in the public nav.** They are 36% of the
   site's words and are working documents: `## Owner-gates + open questions`,
   `Sequenced epics (flywheel-pickable)`, `[WITHDRAWN by REVISION 1]` blocks
   left in place. Their H1s render in the sidebar, so it reads as a to-do list.
   `scripts/check_guardrails.py` already has a `NAV_EXEMPT` mechanism for this.

## Confirmed findings not yet applied

The full review's 178 findings were worked through on 2026-08-31; what remains
is listed here rather than in the review files.

- **CC-26** — `voice-and-audience.md` names coding agents as an audience in its
  second sentence and then gives them no profile row. The fix is a sixth row
  and one rule ("an agent-facing page states the command, not the intent"). Not
  applied because that file is deliberately off-limits to automated passes.
- **ST-06** — ten empty table cells that are ambiguous between "none", "not
  applicable" and "nobody filled this in". Cosmetic; an automated attempt at it
  collapsed a table, so it wants a human eye.
- **AR-22** — ADR 0010 is a 414-line field-validation report filed as a decision
  record, with no Consequences section. Splitting the evidence into
  `docs/designs/` is a file move, which this pass did not do.
- **RB-19** — the Ollama page is filed under Runbooks but has no procedure, no
  verification and no rollback. Also a file move.
- **OP-12** — `LOGGING.md` is a contributor style guide in the Operator's
  Manual. It gained the operator content it was missing; moving it to Coding &
  Contributing is still the better answer.
- **OP-01** — the `make update` target in `platform/orpheus-common` cannot run:
  `force-update-config` copies `config/orpheus.yaml` relative to its own
  directory, which does not exist. The docs steer around it; the Makefile bug
  is unfixed because this pass changed no code.

## Where the local preview lives

`make docs-pages` builds the published artifact into `site-pages/`;
`python3 tools/scripts/serve_docs_preview.py --dir site-pages --prefix /orpheus/
--port 8765 --host 0.0.0.0` serves it on the LAN so it can be read on a phone.
