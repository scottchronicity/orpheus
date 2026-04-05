# Orpheus Open Source Roadmap & Philosophy
**Last Updated:** March 22, 2026
**Status:** Pre-Conference (Merge 2026) Plan of Record

---

## Welcome

Project Orpheus started as one person's obsession: an AI-powered wildlife observation station bolted to a floating platform in the Michigan woods. It listens, watches, and gently interacts with the animals that visit — crows, coyotes, songbirds, the occasional curious human.

Now we're opening the doors. This document is the roadmap, the philosophy, and the invitation. If you've ever wanted to build something that sits at the intersection of ecology, active inference, and edge computing — pull up a chair.

---

## How We Work Together

### The Prime Directive

**Protect the live field station.**

Driving into the freezing woods to reboot a locked-up Jetson sucks. We welcome wild experimentation, but the core runtime must remain bulletproof. In exchange for respecting the hardware, maintainers get deep autonomy over their domains.

Here's the deal:

- **Earn your domain.** If you step up to reliably maintain a module — it's yours. You set the direction, you own the decisions. We believe in proportional trust.
- **Don't break the tank.** The "Floating Tank" is a real, physical thing sitting in a Michigan wetland. If a change destabilizes the production edge deployment, we'll revert first and discuss second. Nothing personal — the animals don't wait for hotfixes.
- **Strong opinions, loosely held.** Every architectural choice in this repo has a reason, but none of them are sacred. Bring a better idea and we'll listen. That's what the ADRs are for.

### Preemptive ADRs

Controversial decisions (RDF-star? MCP? Why not ROS?) are documented as Architectural Decision Records in `docs/adr/`. These exist so you can understand *why* something was chosen — and so you have a clear baseline to argue against if you've got something better. We'd rather have a good debate than a quiet codebase.

### The Tenets

These are non-negotiable:

1. **First, Do No Harm.** Interactions must not habituate, stress, or endanger wildlife. Period.
2. **Production Stability is Paramount.** The edge deployment stays alive. Everything else is secondary.
3. **Hardware Isolation.** Cognitive agents must never know about GPIO pins or ALSA drivers. That's what the MCP layer is for.
4. **Embrace the Messy Reality.** Optimize for thermodynamics, bandwidth, and edge constraints over theoretical purity.
5. **Graceful Degradation.** If an agent dies, the system limps along. It does not crash.
6. **Humans are Just Another Species.** Model human interactions exactly as we model wildlife. Same taxonomy, same event bus, same respect.

---

## Recent Pre-Conference Wins (Completed)

We shipped a massive pre-conference PR ([#193](https://github.com/scottchronicity/orpheus/pull/193)) that knocked out the majority of our "do now" list. Here's what landed:

- **Standardized Makefiles** — DRY, cross-platform build targets across all agents and services. `make test` and `make lint` just work everywhere now.
- **UI Diagnostics & Health Parity** (#123) — Service health panels and log viewers ported to the new React dashboard. No more SSH-ing into the Jetson to check if BirdNET is running.
- **Pre-Roll Buffers** (#81) — Rolling memory buffers for both audio and OpenCV video pipelines. Motion-triggered clips now capture the animal walking *into* frame.
- **Video Snapshot Cleanup** (#141) — `StorageCleanup` with configurable retention so the snapshotter stops filling the disk.
- **CV Runtime Efficiency** (#169) — Optimized the heavy computer vision CI pipeline and Jetson build.
- **Media Pagination & Timelapse Fix** (#171) — Fixed the `media.py` alphabetization bug and added client-side pagination.
- **UI Codecov** (#101) — Coverage instrumentation fixed; we have real numbers now.
- **GitHub Tooling** — Issue templates, PR templates, and `CODEOWNERS` are in place.

That clears the decks for the real fun: the Epics below.

---

## The Epics

### Epic 1: The Cognitive Holarchy & Semantic State Space

This is the brain of Orpheus. Right now the system can tell "bird" from "not bird." We need it to understand a rich, queryable taxonomy — crows, coyotes, known humans, unknown humans, plants, weather patterns — all modeled as entities in a semantic state space that agents can reason over.

**1.1 — The Grand Entity Detector Hierarchy**
Expand the taxonomy beyond Birds. We need `Animals → (Birds, Critters)`, `Humans → (Known 2FA, Unknown)`, and `Plants`. Every entity type gets first-class representation in the `EntityEvent` models, with a clean migration path from the current flat structure.

**1.2 — State Space Likelihood & Memory**
Agents should be able to query the state space: "What's the probability of a coyote visit at 2am in March?" Implement latent memory states so the system *remembers* patterns — not just reacts to the current moment.

**1.3 — Corollary Discharge (The "Echo" Problem)**
When Orpheus plays a crow call, its own microphone hears it and triggers a detection. The correlator needs a temporal blanking window that tags self-generated detections as `is_self_generated: true` instead of treating them as real events.

**1.4 — Full BDD End-to-End Testing Pipeline**
Build a Cucumber BDD suite that simulates complete detection sequences — audio trigger → classification → correlation → actuation — using generated signals. This is how we prove the cognitive loop actually works.

**1.5 — Isolate Individual Bird Calls (Stretch)**
In a dawn chorus, BirdNET gets a chunk with 15 overlapping species. Can we extract individual bird songs from heavily overlapped audio? This is a research problem. Bring your DSP skills.

---

### Epic 2: Universal Actuation & Physical Control

Orpheus can observe the world. Now it needs to *touch* it — safely. This epic wraps all physical actuators (speakers, feeders, relays) behind the Model Context Protocol so that higher-level cognitive agents never talk directly to hardware.

**2.1 — MCP Servers for Audio & Relays**
Wrap the existing audio playback script and relay controller in formal MCP servers. Expose `play_audio(uri, volume)` and `toggle_relay(id, state)` as standardized tools that any agent can call through the protocol.

**2.2 — [SAFETY] Hardware Circuit Breakers via MCP Middleware**
If the Director agent gets stuck in a positive feedback loop, it could play crow calls all night or burn out a relay. Implement hard rate-limiting (max 3 playbacks/hour, max 1 feeder drop/day) at the MCP middleware layer. The limits must persist across restarts.

**2.3 — Agentic Audio Auto-Tuning**
Let agents use MCP to play frequency sweeps and dynamically calibrate volume constraints based on ambient noise levels. The system should tune itself to the environment rather than relying on hardcoded volume settings.

---

### Epic 3: Interspecies Interfaces & Human "Pavloving"

Orpheus treats humans as just another species in the taxonomy. This epic builds the interfaces that let humans interact with the station — voice commands, mobile alerts, privacy-respecting filtering, and a weatherproof field display.

**3.1 — Human Wake-Word Integration**
Add edge-compatible voice control so a human standing near the station can say "Orpheus, what birds are here?" and get an answer. Must work offline on the Jetson — no cloud speech APIs.

**3.2 — Privacy & Human Anomaly Filtering**
When the microphone picks up human conversation, we need to detect it and strip it from saved recordings. Nobody wants their private chat stored on a wildlife station's SD card. This is an ethical and legal requirement.

**3.3 — Personal Observer Apps**
Build a lightweight mobile wrapper (PWA or native shell) that sends push alerts when interesting events happen. "A coyote was just detected at your station." The goal: Pavlov-condition the humans to check on their local wildlife.

**3.4 — Weatherproof Field Display**
Support an external, ruggedized screen mounted on the Floating Tank that shows real-time status, recent detections, and environmental data. Think: a kiosk for the forest.

---

### Epic 4: Event Bus Evolution (From MQTT to Streams)

MQTT is great for lightweight pub/sub on the edge. But as Orpheus gets smarter, we need durable, replayable event streams that support consumer groups and historical replay. This epic abstracts the transport layer so agents don't care what's underneath.

**4.1 — Abstract `paho-mqtt` Behind a Generic EventBus Interface**
No agent should import `paho-mqtt` directly. Refactor `orpheus_common.mqtt` into an abstract `EventBus` base class with dependency-injected backends. Zero changes to agent logic — only `orpheus-common` internals.

**4.2 — Redis Streams / Kafka Evaluation & Backend**
Evaluate durable stream backends (Redis Streams, NATS, Kafka) for edge viability. Implement the winner as a second `EventBus` adapter alongside the existing MQTT adapter. Bonus points if it runs on a Jetson without melting.

**4.3 — Historical Replay Tooling**
Build tools to inject historical `EntityEvents` back into the bus. This unlocks offline analysis, regression testing against real-world data, and "what would the system have done?" counterfactual queries.

---

### Epic 5: Observability, Telemetry & Environment

You can't improve what you can't measure. This epic brings proper observability to the edge — weather data, OpenTelemetry traces, and a clean separation between the MQTT control plane and the observability plane.

**5.1 — Ecowitt Weather Integration (#153)**
Ingest data from the local Ecowitt weather station into `SpatiotemporalContext`. Temperature, humidity, barometric pressure, wind — all correlated with wildlife activity. "Do crows visit more before a storm?" Now we can answer that.

**5.2 — OpenTelemetry (OTel) Migration (#95)**
Right now, debug logging and event data share the same MQTT bus. Separate the observability plane (traces, metrics, health checks) onto OpenTelemetry with a Jaeger backend. Keep the control plane clean for actual system events.

---

### Epic 6: Infrastructure & Extensibility (Makefiles & BATS)

The build system is the first thing a new contributor touches. If `make test` doesn't work in 30 seconds, we've already lost them. This epic makes the developer experience seamless across macOS, Linux x86, and Linux ARM (Jetson).

**6.1 — DRY Makefile Architecture**
Consolidate the duplicated Makefile logic into a centralized inclusion pattern with OS/Arch detection (`uname -m`). One `Makefile.include`, many thin component Makefiles. No more copy-paste drift.

**6.2 — BATS (Bash Automated Testing System)**
Our shell scripts (startup sequences, health checks, deployment scripts) have zero test coverage. Implement BATS tests for the critical bash infrastructure. If a script runs in production, it gets a test.

**6.3 — Package Management Evaluation**
Evaluate swapping `pip`/`poetry` for `uv`. The dependency resolution is faster, the lockfiles are cleaner, and it handles virtual environments more predictably. Run a proof-of-concept migration on one agent and report back.

---

### Epic 7: Containerization & Cloud-Native Simulation

Not everyone has a Jetson. Not everyone wants to deploy to the woods. This epic builds a complete simulation environment so contributors can develop, test, and experiment with the full Orpheus stack on any machine.

**7.1 — Docker Compose "Simulacrum" Environment (#152)**
Create a `docker-compose.dev.yml` that spins up Mosquitto, the database, the UI, and mock agents that replay pre-recorded audio/video events. A new contributor should go from `git clone` to a working system in under 5 minutes.

**7.2 — Auto-Generate Deployment Manifests**
Parse `orpheus.yaml` to auto-generate Docker Compose or K8s/K3s manifests. When a new agent is added to the config, it should automatically appear in the deployment topology. No manual manifest wrangling.

---

### Epic 8: Configuration Management Evolution

Orpheus currently lives in a single `orpheus.yaml`. That works for one station, but it doesn't scale to versioned configs, per-environment overrides, or database-backed tuning.

**8.1 — Nuanced Database Configuration System**
Implement a configuration layer that can store and version settings in the database while remaining backward-compatible with `orpheus.yaml`. Think: "base config in YAML, overrides in the DB, environment variables win everything."

---

### Epic 9: Edge Hardware Realities

The Floating Tank is a sealed enclosure in a Michigan wetland. It gets hot. It gets cold. The network drops. The power flickers. This epic is about surviving all of that gracefully.

**9.1 — Dynamic Thermal Throttling & Shedding**
Monitor `jtop` thermal stats. If the enclosure temperature crosses thresholds, autonomously shed load — kill video processing first, drop to audio-only, and log the thermal event. The system should manage its own thermals without human intervention.

**9.2 — Automated Acoustic Regression Testing**
Build a CI pipeline that tests new BirdNET/AVES models against a "Golden Dataset" of known-good recordings. If a model update causes accuracy to drop, the pipeline blocks the merge. No regressions in production.

---

## Want to Contribute?

Start with the [Epics below](#the-epics) — those tasks are bounded, well-defined, and immediately useful. Look for issues tagged `good first issue` or `help wanted` in the GitHub tracker.

If you're interested in a specific Epic, open a discussion. We'd love to hear your perspective before you start writing code — especially if you disagree with our approach. That's what the ADRs are for.

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) for setup instructions and coding standards.

Welcome to the woods.
