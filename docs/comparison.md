# How Orpheus compares

If you want to know what birds are around you, several good projects already do
that, and some of them will serve you better than Orpheus. The ones worth weighing
against it are **[BirdNET-Pi](https://github.com/Nachtzuster/BirdNET-Pi)** (the
maintained fork; the original `mcguirepr89` repo is archived and its author
marks that install deprecated), **[BirdWeather PUC](https://www.birdweather.com/)**, and
**[Haikubox](https://haikubox.com/)**. This page is here so you can decide quickly
instead of discovering it three evenings in.

## The short version

**Pick something else if** you want a bird-song identifier that works this weekend.
BirdNET-Pi on a Raspberry Pi with a USB microphone gets you there with a friendly
setup guide and thousands of people who have hit your exact problem before. A
BirdWeather PUC or a Haikubox gets you there without any setup at all — you plug it
in. Those are solved, well-served needs, and Orpheus is not a better answer to them.

**Orpheus is interesting if** you want several classifiers running at once and
reconciled into one picture — not three separate lists — on hardware you already
have, with the internals open enough to change.

## What Orpheus does differently

**One row per acoustic moment, not one per model.** Three classifiers hearing the
same crow call produce one entity carrying all three pieces of evidence, instead of
three rows you mentally deduplicate. That makes counts comparable across classifiers
and the evidence behind each one auditable. It is *not* individual identification:
a crow calling all afternoon is still many entities, and Orpheus cannot tell you
whether the same jay came back.

**Several classifiers, one answer.** Orpheus runs a bird specialist, a corvid
specialist, and a general sound-event model at the same time, then correlates their
detections into a single **entity** per real animal.

**It learns that two labels mean one animal.** Different models name things
differently. Orpheus watches which labels keep co-occurring and proposes equivalences
between them, applying the obvious ones and asking you about the rest.

**It hears more than birds.** The general sound model covers AudioSet's 527
classes, so dogs, vehicles, rain, chainsaws, and human speech are first-class
observations, not noise to discard. Useful if your question is about a place, not
just its birds.

**Independent agents, not one program.** Capture, each classifier, correlation, and
the dashboard are separate processes talking over a message bus. Any one can be
restarted, replaced, moved to another machine, or written by you, without touching
the others.

**It can be run and tested without hardware.** The whole collective runs in
containers with a synthetic or replayed audio source, so you can develop or evaluate
it on a laptop before committing hardware.

**Operational tooling built for a box that must keep running.** Health checks,
verified upgrades with a rollback path, a retention sweep that trims each category
oldest-first under disk pressure but will not delete inside a floor of recent
history, and a read-only mirror so browsing a year of data does not contend with
what is being recorded. Two caveats on that list,
both noted in the [Operator's Manual](operator-manual/index.md#7-data-retention):
retention is bounded by size, not by age — each category has a `max_gb` ceiling and a
`floor_days` floor, so a station well under its ceiling keeps clips indefinitely and
row-level retention of the detection database is configurable but *stubbed*; and the
mirror ships as a working CLI you run from cron or a unit you write, not as a service
that keeps itself on a schedule.

## Where the alternatives are stronger

**Turnkey setup.** A Haikubox or a BirdWeather PUC is an appliance: plug it in,
join it to wifi, done. BirdNET-Pi is a one-line installer on top of a stock
Raspberry Pi OS image, and gets you to first detection quickly. Orpheus expects
you to be comfortable with a terminal, and the install is several components.

**Cheaper hardware.** BirdNET-Pi runs happily on a Raspberry Pi 4 with a USB
microphone. Orpheus's reference target is a Jetson Orin NX, because three models run
concurrently — see the hardware numbers below.

**Community and shared data.** BirdWeather aggregates detections from thousands of
stations into a live public map, and BirdNET-Pi has years of accumulated
troubleshooting in its issue tracker. Orpheus is one station's software opened up;
its network effects do not exist yet.

**Polish.** Their mobile experience, notifications, and onboarding are more finished
than ours today.

**Reporting outward.** BirdWeather and Haikubox submit observations upstream for you.
Orpheus keeps everything local by default; sharing data back is
[tracked work](https://github.com/scottchronicity/orpheus/issues), not a shipped
feature.

## What it costs to run

| | Trying it out | A real station |
| --- | --- | --- |
| Hardware | Any laptop with Docker | Jetson Orin NX (the reference target) |
| Memory | 8 GB is enough for the container fleet | 8 GB minimum, 16 GB comfortable |
| Disk, to install | ~1.5 GB of models, plus component environments | Same, plus the OS |
| Disk, ongoing | Nothing — you tear it down | Recordings accumulate. A retention sweep trims each category oldest-first once it passes its `max_gb` ceiling, or sooner if free space drops under `reserve_gb`, and never deletes inside `floor_days`. The shipped ceilings total 1,560 GiB across audio, motion video, snapshots and timelapses. Size is what bounds a category; nothing ages a clip out on a schedule. An external SSD is the assumption. |
| Microphone | None — synthetic or replayed audio | A multi-channel USB interface for real capture |
| Roughly, in money | Nothing you don't already own | The compute module dominates: an Orin NX is sold as a module plus a third-party carrier board, not as a dev kit, and it costs several times a Raspberry Pi. On top of that, a multi-channel USB audio interface, microphones, an external SSD, and a weatherproof enclosure. A BirdNET-Pi build is a Pi, a USB microphone, and a card. Price both before committing — module and memory prices have moved sharply and anything quoted here would be stale. |

Power is modest either way: a station running continuously draws roughly 10–15 W
and a Pi less, which is on the order of $20 a year at average US residential
rates.

The three model agents ship with soft memory guardrails of 1.5 GB (BirdNET),
2.5 GB (the corvid classifier), and 2.5 GB (the general sound model). Those are
throttle ceilings rather than measured usage, but they show the shape: the models
dominate, and the correlator, dashboard, and broker run alongside them.
Fewer classifiers means less memory — they are individually switchable.

The laptop path is the honest way to find out whether this is for you before any
hardware arrives: `make sim-up` and `make sim-fleet-up` run the whole collective in
containers against a synthetic source, or `SIM_MODE=replay` to run real clips
through the real models.

## Honest limitations

- The default deployment targets a Jetson running a pinned older Python, which
  constrains dependency versions. See [Security](security.md).
- It expects a LAN, not the public internet. The sharing path is the read-only
  mirror, not exposing the dashboard.
- Multi-classifier correlation is genuinely more moving parts. If one model answers
  your question, more models are cost, not benefit.
- Video support exists but assumes network cameras; there is no plug-in-a-webcam
  path.

## Using them together

These are not exclusive. Orpheus's classifiers are the same public models other
projects use, so running a small bird box and an Orpheus station side by side is
reasonable, and comparing what they each report is a good way to calibrate trust in
either.

**Keeping this page honest.** Other projects improve. If something here is out of
date or unfair, that is a bug — open an issue or send a pull request.
