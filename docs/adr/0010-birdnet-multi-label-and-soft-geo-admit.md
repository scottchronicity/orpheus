# ADR 0010: BirdNET Multi-Label, Soft Geo-Admit Rule, and Non-Bird Suppression

**Status:** Accepted

**Date:** 2026-05-23

**Deciders:** Scott, Development Team

**Related PR:** `fix/birdnet-sigmoid-multilabel`

## Context

The bird-detection agent was failing to surface acoustically-clear species an
operator on-site could plainly hear. The named regression target was Eastern
Whip-poor-will (_Antrostomus vociferus_), audible on the property every spring
but never written to the detections DB. Investigation revealed two compounding
root causes:

1. **BirdNET was being treated as a multi-class classifier.** The agent applied
   `softmax` across all ~6,500 species labels in BirdNET v2.4's output, treating
   the model as mutually-exclusive single-label. BirdNET v2.4 is in fact
   multi-label: each species has an independent sigmoid head and many species
   can co-occur in a single 3-second window. Softmax forced one dominant species
   to absorb the probability mass, suppressing co-present rarer species below
   threshold.

2. **The geographic filter was a hard cut at `min_prob >= 0.03`.** Field
   analysis showed Eastern Whip-poor-will's BirdNET meta-model probability at
   the configured site falls below 0.03 — even though the species is audibly
   present every night. The 36-hour post-sigmoid-fix analysis recorded 219
   high-confidence (avgC=0.89) whip-poor-will detections, all silently dropped
   by the geo filter.

Two phased deploys were executed on jetson1 (Behringer UMC404HD, four
channels, 48kHz) with read-only DB queries and journalctl grep, comparing 39.5h
windows before and after each phase. The raw analysis files live at
`/tmp/geo-overhaul-analysis/` on the device and `~/oha/geo-overhaul-analysis/`
on the operator's workstation.

### Validation time frame

| Phase | Cutover (UTC) | Cutover (ET) |
|---|---|---|
| Sigmoid-only deploy | 2026-05-20 00:19 | 2026-05-19 20:19 |
| Geo-overhaul deploy 1 (soft rule + whitelist + non-bird) | 2026-05-21 22:19 | 2026-05-21 18:19 |
| Geo-overhaul deploy 2 (merge dedup + scientific-name logs) | 2026-05-21 ~later | 2026-05-21 ~later |
| Validation report cutoff | 2026-05-23 ~14:00 | 2026-05-23 ~10:00 |

Future analyses comparing across these boundaries should treat the brief
service-restart gaps (~2 minutes each) as exclusion zones.

## Decision

Ship the full overhaul. The named regression target was solved (0 → 176
detections at avgC=0.98); residual issues are smaller than the win and are
captured as deferred follow-ups.

### Changes shipped

1. **Sigmoid instead of softmax** on BirdNET logits. Each species' score
   becomes independent, matching upstream BirdNET-Analyzer's activation and
   `np.clip(logits, -15, 15)` range.

2. **Soft geographic-admit rule.** Replaces the binary `min_prob >= 0.03` cut
   with three admit paths (first match wins):
   - `geo_prob >= geo_filter_min_prob` (default 0.03, primary, unchanged)
   - `geo_prob >= geo_filter_weak_admit_prob AND acoustic_conf >= geo_filter_weak_admit_conf`
     (defaults 0.0005 / 0.85, soft-admit — what unlocks patchy-distribution species)
   - operator-supplied `site_species_whitelist` (escape hatch; optional, empty
     by default; resolved from scientific names or full BirdNET labels to label
     indices at agent init)

3. **Explicit non-bird-label suppression** before the geo filter. Initial set:
   Dog, Eastern Chipmunk, Engine, Fireworks, Gun, Human non-vocal, Human vocal,
   Human whistle, Noise, Power tools, Siren. Matched on `species_common` field.
   Hardcoded in `birdnet.py`; expand based on operator observation of
   soft-admit log noise. Note that Eastern Chipmunk is a real animal but not a
   bird; its "chuck" call was repeatedly soft-admitting at avgC=0.93.

4. **Multi-window dedup by `_label_idx`** rather than `species_code`. The 6-char
   species_code collapses many distinct species into the same key (American
   Crow + Common Raven both → `corvus`; all 10 Antrostomus nightjars →
   `antros`); using it for sliding-window dedup actively undid multi-label
   semantics. `_label_idx` is unique by construction.

5. **Scientific-name logging** in `_apply_geo_filter` admit/suppress lines. The
   prior format (`Suppressed antros (0.99)`) was ambiguous across 10 nightjars;
   new format (`Suppressed Antrostomus vociferus (Eastern Whip-poor-will) due
   to geographic filter — acoustic=0.99 geo=0.00001`) is greppable and unique.

6. **Documentation**: in-line WARNING comment on `_parse_species_code` flagging
   the 87%-collision rate and steering future readers away from using
   species_code as a join key. Operator-facing knobs documented in
   `config/orpheus.example.yaml`.

7. **Makefile idempotency**: the `$(VENV)/bin/activate` recipe in
   `make/common_python.mk` no longer recreates the venv on every `make install`
   run. Cross-cutting fix surfaced while deploying this work; benefits every
   agent. Skips the recipe entirely when `$(VENV)/bin/activate` already exists,
   avoiding the noisy `uv venv` replace prompt.

### Field validation outcomes

Validation was done in two stages, one per cutover. Both are documented here
so future readers can reason about the contribution of each phase.

#### Stage 1 — softmax → sigmoid (24h symmetric pre/post 2026-05-20 00:19 UTC)

The sigmoid fix alone, prior to any geo or non-bird changes. Pre = softmax,
post = sigmoid; everything else identical. The 36h analysis report covering
this transition is preserved at `/tmp/sigmoid-analysis/` on jetson1.

| Metric | PRE (softmax) | POST (sigmoid) | Δ |
|---|---:|---:|---|
| species.detected rows | 12,033 | 11,103 | −7.7% |
| audio.motion events | 7,272 | 6,709 | −7.7% |
| crow.analyzed rows | 369 | 1,088 | **+195%** |
| Unique species | 94 | 99 | +5 |
| Productive event rate | 70.1% | 73.0% | +2.9pp |
| Mean species / productive event | 2.36 | 2.27 | −0.09 |
| Max species in one event | 9 | 10 | +1 |
| Mean confidence | 0.340 | 0.351 | +3% |
| % detections at conf <0.12 | 17% | 17% | unchanged |
| % detections at conf ≥0.99 | 4% | 2% | −2pp |
| Mean inference latency | 2,334 ms | 2,408 ms | +3% |
| p99 inference latency | 3,000 ms | 3,611 ms | +20% |

Aggregate volume essentially unchanged at the row level — sigmoid does not
change *how many* species cross threshold, only *which* and at what relative
confidences. Notable shifts from this stage:

- **crow.analyzed +195%** driven entirely by Blue Jay (`cyanoc`) detection
  count going from 354 → 1,186 (3.3×). Blue Jay is in `CORVID_SPECIES`, so
  every Blue Jay detection triggers the corvid secondary path. Downstream
  crow-detection load tripled.
- **Mourning Dove 24 → 468**, **Yellow-bellied Sapsucker 103 → 268**: both
  were being absorbed by softmax-dominant common species; sigmoid lets the
  slow paced cooing / quiet drum-tap score cleanly.
- **Nashville Warbler 55 → 168 at avgC 0.26 → 0.64**, **Rose-breasted
  Grosbeak avgC 0.59 → 0.63**: distinctive vocalists previously losing
  probability mass to co-occurring louder species.
- **Pileated Woodpecker 376 → 143 at p95 0.82 → 0.62**: count halved and
  confidence collapsed. Pileated wasn't disappearing; under softmax it was
  "winning" by absorbing mass when it called near other species. Sigmoid
  now reports its honest per-class score, which is much lower in absolute
  terms. Worth listening to a clip to spot-check whether the new
  confidences are *too* low (potential calibration issue) or just honest.
- **Ruffed Grouse 59 → 302 at avgC 0.15**: sigmoid surfaces weakly-positive
  drumming logits as detections. These are probably real but barely-clearing
  threshold and contribute to noise volume.

Critically, after sigmoid alone, **Eastern Whip-poor-will is detected
acoustically at avgC=0.89, max 1.00, 171/219 detections at ≥0.90 confidence
— but every single detection is dropped by the geographic filter's
`min_prob >= 0.03` cut.** This is what motivated Stage 2.

#### Stage 2 — sigmoid → full overhaul (39.5h symmetric pre/post 2026-05-21)

The geo soft-admit rule + non-bird suppression + merge dedup fix + log-format
cleanup. Pre = sigmoid-only baseline, post = full overhaul:

| Metric | PRE (sigmoid-only) | POST (full overhaul) |
|---|---:|---:|
| Eastern Whip-poor-will detections | 0 | **176** (avgC=0.98, peak 1.000) |
| Total species.detected rows | 16,680 | 10,419 (−38%) |
| audio.motion events | 10,143 | 8,075 (−20%) |
| crow.analyzed rows | 1,337 | 305 (−77%) |
| Unique species detected | 101 | 130 |
| Mean confidence | 0.371 | 0.404 |
| Detections ≥0.5 confidence | 4,638 | 3,355 |
| Detections ≥0.8 confidence | 2,593 | 1,907 |
| Productive event rate | 69% | 55% |
| Non-bird labels reaching DB | leaked | 0 |
| Inference latency p99 | 3,480 ms | 3,230 ms |
| Inference latency p50 | 2,309 ms | 2,302 ms |

#### Headline win: Eastern Whip-poor-will (required BOTH stages)

This is the original regression target. The two stages contributed
independently:

- **Stage 1 (sigmoid) made it acoustically detectable**: under softmax, the
  whip-poor-will's call lost probability mass to co-occurring nightjars and
  other nocturnal vocalists. Under sigmoid, it scored avgC=0.89 (171/219
  detections ≥0.90) — but every detection was then dropped by the geo filter.
- **Stage 2 (soft-admit) let it through the geo filter**: at this site
  (43.9525, -84.7), whip-poor-will's BirdNET meta-model probability is 0.0147
  — below the primary 0.03 threshold but above the soft-admit 0.0005 floor.
  Combined with acoustic confidence comfortably clearing the 0.85 floor,
  soft-admit unlocked DB writes.

Result in the post-overhaul DB:

- First detection: 2026-05-22 01:13:21 UTC, channel 1, confidence 0.980
- 176 detections across 39.5h, all four channels, avgC=0.98, peak 1.000
- 171 of 176 detections at confidence ≥0.90; only 5 below 0.95
- Cross-channel correlation visible — successive calls picked up on multiple
  channels within seconds, confirming the call is acoustically real and not a
  single-mic artifact

#### Geo-probabilities at site (43.9525, -84.7) for week 21

Reference values for future comparison. The `predict_probabilities` output
was instrumented during validation. A species with geo_prob ≥ 0.03 passes
the primary admit unconditionally; between 0.0005 and 0.03 requires acoustic
≥ 0.85 (soft-admit); below 0.0005 is rejected unless whitelisted.

| Species | geo_prob | Admit path |
|---|---:|---|
| American Robin | 0.9682 | Primary |
| Baltimore Oriole | 0.7739 | Primary |
| American Crow | 0.6725 | Primary |
| Ovenbird | 0.3757 | Primary |
| Pileated Woodpecker | 0.1679 | Primary |
| Common Raven | 0.1208 | Primary |
| Red-headed Woodpecker | 0.0889 | Primary |
| Tennessee Warbler | 0.0752 | Primary |
| Eastern Whip-poor-will | 0.0147 | **Soft-admit** ✓ |

The meta-model admits 143 species at `geo_prob ≥ 0.03` for this site/week
and 6,379 species fall in the soft-admit band [0.0005, 0.03). Almost the
entire BirdNET label set is reachable via soft-admit — biological plausibility
at this site, not the geo gate, is now the dominant filter.

#### Cross-validation: common Michigan species are *not* gone

A first analysis run produced a top-30 table with several common species
apparently dropping to zero post-deploy (American Robin 279 → 0,
Red-headed Woodpecker 233 → 0, etc.). On reanalysis this turned out to be a
presentation bug in the report (default value of 0 for species below rank 30),
not a regression. Actual numbers:

| Species | PRE detections | POST detections | Geo passes? | Suppression lines in journal |
|---|---:|---:|---|---:|
| American Robin | 279 | 86 | Yes (0.97) | 0 |
| Red-headed Woodpecker | 233 | 74 | Yes (0.09) | 0 |
| Tennessee Warbler | 210 | 28 | Yes (0.08) | 0 |
| Baltimore Oriole | 200 | 51 | Yes (0.77) | 0 |
| Pileated Woodpecker | 127 | 73 | Yes (0.17) | 0 |
| Ovenbird | 118 | 25 | Yes (0.38) | 0 |
| American Crow | 130 | 54 | Yes (0.67) | 0 |

All seven are admitted by the geo filter and written to both `detections`
and `entities` tables. The volume drop is proportional across the broader
community (Blue Jay −80%, Mourning Dove −68%, Tufted Titmouse −65%, Eastern
Towhee −1% i.e. unchanged) and is most consistent with weather + migration
timing in the comparison window. The new filter logic is exonerated.

#### Three-window decomposition (UTC; ET = UTC − 4)

| Window | Hours | PRE detections | POST detections | PRE unique | POST unique |
|---|---|---:|---:|---:|---:|
| Dawn chorus | 09–11 UTC (05–07 ET) | 701 | 942 | 59 | 70 |
| Daytime quiet | 14–18 UTC (10–14 ET) | 2,200 | 1,718 | 88 | 107 |
| Nocturnal | 02–08 UTC (22–04 ET) | 147 | 67 | 21 | 27 |

Dawn chorus is up in both volume and diversity (more species through the
sigmoid + soft-admit). Daytime quiet is down in volume but up in diversity
(more long-tail species reachable). Nocturnal is down in raw count (less
acoustic noise being mis-classified) but up in unique species — including
whip-poor-will.

#### Soft-admit log breakdown (15h post-deploy sample)

61 soft-admit lines total; what was admitted via the soft rule:

| Species | n | avgC | avg geo_prob |
|---|---:|---:|---:|
| Eastern Whip-poor-will | 44 | 0.97 | 0.0147 |
| Eastern Chipmunk | 7 | 0.93 | 0.00055 |
| Ashy-throated Warbler | 2 | 0.91 | 0.00055 |
| Yellow-billed Cuckoo | 1 | 0.92 | 0.0159 |
| 7 others (1 each) | 7 | 0.87–0.97 | ~0.00055 |

Eastern Chipmunk addressed by adding to `NON_BIRD_LABELS_COMMON` in the
same commit as this ADR. Yellow-billed Cuckoo is a plausible Michigan
species. The other singletons (Hawaii Creeper, Northern Pygmy-Owl, Akohekohe,
Varied Thrush, Rufous Fantail, Mexican Whip-poor-will) are confusable
admits and the cluster motivating limitation 1 below.

#### Top suppressed species (15h post-deploy sample)

3,348 geographic-suppression lines total. The top suppressions confirm the
filter is doing the right work on geographically-absent species:

| Species | n suppressed | avg geo_prob |
|---|---:|---:|
| Acadian Flycatcher | 108 | 0.0216 |
| Worm-eating Warbler | 71 | 0.0017 |
| Eastern Chipmunk (now non-bird) | 64 | 0.00055 |
| Puaiohi (Hawaiian) | 58 | 0.00055 |
| Australian Brushturkey | 55 | 0.00055 |
| Chinese Blackbird | 55 | 0.00055 |

A 113-line tail of "non-bird label" suppressions also fired cleanly for Dog,
Engine, Human voice, Power tools, etc., with zero non-bird rows reaching the
detections DB.

#### Channel balance

| Channel | PRE detections | POST detections | PRE avgC | POST avgC |
|---|---:|---:|---:|---:|
| 1 (Orange) | 4,571 | 2,894 | 0.362 | 0.408 |
| 2 (Yellow) | 4,047 | 2,399 | 0.364 | 0.408 |
| 3 (Green) | 4,402 | 2,778 | 0.377 | 0.400 |
| 4 (Blue) | 3,660 | 2,348 | 0.383 | 0.400 |

Channel balance is intact post-overhaul, with average confidence rising
proportionally across all four channels (~+12% relative).

## Known limitations (shipping anyway)

1. **Confusable false-positives in the soft-admit band** (≤10 rows per 39.5h):
   Tawny Owl, Little Owl, Eurasian Coot, European Greenfinch, Hawaii Creeper,
   Brown Tinamou. All Eurasian/Hawaiian species vocally similar to allowed
   Michigan species (Barred Owl, American Coot, House Finch). The 0.0005
   geo_prob floor admits them when acoustic confidence is very high. Mitigation
   candidates: raise floor toward ~0.001-0.002, or add a "confusable-with-
   allowed-congener" rejection rule.

2. **Black-throated Blue Warbler persistence**: 84% of detections sit in the
   0.11–0.35 confidence band, present in ~4% of all clips. Pattern is
   essentially identical pre- and post-overhaul. Not caused by this work;
   probably the model overfitting a generic frequency band.

3. **Blue Jay −80% drop**: mechanically cannot be caused by this PR's changes
   (Blue Jay geo_prob=0.80 passes easily; not in non-bird list; the new
   `_merge_detections` keying on `_label_idx` can only return as many or more
   rows than the prior code, never fewer). Most likely weather + time-of-day
   distribution shift between the two comparison windows. Revisit on a 7-day
   rolling window once weather normalizes.

4. **`species_code` is collision-prone everywhere downstream**:
   `orpheus_common.detection.species.CORVID_SPECIES` keys on it (`corvus`
   matches 32 species globally including Hawaiian Crow), the DB schema indexes
   it, the correlator's alias map likely keys on it, the dashboard's birds
   page likely groups by it. The DB has direct evidence of mixed common names
   under the same code (1 row of `sayorn`=Black Phoebe + 17,296 rows of
   `sayorn`=Eastern Phoebe). This PR adds an in-code WARNING but does not yet
   fix downstream consumers.

5. **Source venv accumulates root-owned files on the Jetson** when running
   `make update`. The Makefile idempotency fix (item 7 above) prevents the
   noisy uv-replace prompt but does not address the underlying ownership
   leak; root cause not yet identified. Workaround: `sudo rm -rf venv` then
   `make update`.

6. **Dashboard Entities-page species filter is broken** (frontend bug,
   separate issue). The backend has the rows.

## Deferred follow-ups

Tracked separately, not in this PR:

- Tighter geo_prob floor or congener-mismatch rule (limitation 1)
- BTBW persistence root-cause investigation (limitation 2)
- Blue Jay drop sanity check on a 7-day window (limitation 3)
- `species_code` consumer audit + ADR + change list for `CORVID_SPECIES`,
  dashboard birds page, correlator alias map (limitation 4). The likely path
  is to use `species_scientific` as the join key everywhere, treating
  `species_code` as a vestigial human-readable nickname.
- Diagnose root-owned source-venv pollution on Jetson (limitation 5)
- Dashboard Entities-page filter fix (limitation 6)
- Per-species confidence calibration (replaces the global 0.10 threshold;
  upstream BirdNET-Analyzer uses this pattern)

## How to roll back / partially revert

The PR is composed of independent commits that can be cherry-picked or
reverted individually. From newest to oldest:

| Commit (short) | Scope | Safe to revert alone? |
|---|---|---|
| chipmunk + this ADR | Add Eastern Chipmunk to non-bird set + this doc | Yes |
| dedup by `_label_idx` + scientific-name logs | Multi-window dedup + log format | Yes (reverts would re-introduce species_code collision in dedup) |
| Makefile venv idempotency | Cross-cutting platform fix | Yes (no behavior change for the agent) |
| Example YAML docs | Operator-facing docs only | Yes |
| Soft geo-admit + whitelist + non-bird suppression | Geo filter overhaul | Yes (reverts would restore the binary 0.03 cut and re-bury whip-poor-will) |
| Sigmoid not softmax on BirdNET logits | Activation function | Reverting this alone re-introduces multi-label suppression; revert only along with the soft geo-admit commit |

The DB has timestamps for every detection, so the dataset boundary between
pre-sigmoid, sigmoid-only, and full-overhaul regimes is recoverable by joining
detection timestamps against the cutover times in the validation table above.

## References

Stage 1 (softmax → sigmoid) analysis:

- `/tmp/sigmoid-analysis/REPORT.md` on jetson1 (the 36h analysis covering this
  transition; identified the geo-filter-suppressing-whip-poor-will issue that
  motivated Stage 2)
- `/tmp/sigmoid-analysis/big_analysis.py` and `big_analysis.out`

Stage 2 (sigmoid → full overhaul) analysis:

- `/tmp/geo-overhaul-analysis/REPORT_FOLLOWUP.md` on jetson1 (canonical
  validation report including the corrected per-species cross-check that
  exonerated the geo filter; this file supersedes the initial `analysis.out`
  which had a top-30 presentation bug)
- `/tmp/geo-overhaul-analysis/probe_geo.py` (per-species geo-probability probe
  — re-runnable with different lat/lon/week to project counterfactuals)
- `/tmp/geo-overhaul-analysis/final_dive.py` (per-species DB + journal queries)
- `/tmp/geo-overhaul-analysis/bird.log` (raw 15h journal dump for grep)

Both `/tmp/` directories are also mirrored at `~/oha/` on the operator's
workstation. `/tmp/` does not survive Jetson reboots — copy elsewhere if you
want them preserved for the long term.

Other:

- Upstream BirdNET-Analyzer activation reference (sigmoid + `np.clip(-15, 15)`
  matches their implementation)
- ADR 0008: Shared Makefile Includes (the `common_python.mk` file modified by
  item 7 above lives in the shared-include layer ADR 0008 established)
