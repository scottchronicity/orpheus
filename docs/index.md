# Orpheus

Orpheus listens to a place and tells you what is there.

It runs a handful of machine-learning models over live audio — a bird
specialist, a corvid specialist, a general sound classifier — and reconciles what
they each heard into a single picture: one entry per real animal, with the evidence
that identified it. It runs on hardware in your own home, and the recordings stay
there.

Orpheus is a closed loop — an agent that observes the place it is in and acts in it.
It is already wired to recognize animals by sound; recognizing them by sight goes in
next. The playback path is built too, but no specific responding agent ships in this
repository yet: the policies that decide what to say, to whom, and when are in active
development, and full feedback loops are held to a high bar before they land here.

**Using it responsibly.** Orpheus listens to a real place, and with playback wired up
it makes sound in one. Anywhere you run it is somebody's habitat. Don't deploy it in
protected or sensitive areas, don't let it become a nuisance to your neighbors —
human or animal — and use playback deliberately: sound directed at wildlife changes
behavior, and it carries further than you expect. Running this software means taking
that judgment on yourself.

![The Entities page from a live station: per-day totals, the species mix, a
confidence scatter, hourly activity, and the filterable entity
table](assets/entities.png)

*Eight days on a real deployment — 47,551 entities.*

**New here?** [What Orpheus is and how it compares](comparison.md) to the other
projects in this space, honestly.

---

## Start where you are

### ![](assets/glyph-bird.svg)"I want to know what's singing in my yard"

You want the result, not the machinery. Someone else can set the box up — or an AI
assistant can, see below.

1. [What Orpheus can tell you](comparison.md) — is this the right tool?
2. [Using the dashboard](user-guide/index.md) — the pages, what they show, how to
   filter and play back what was heard.
3. [Playing back what was heard](user-guide/index.md) — finding a clip and listening to it.

### ![](assets/glyph-wave.svg)"I want to install it, but I'd rather not do it by hand"

1. [Installing with an AI assistant](llm-assisted-install.md) — a prompt to hand
   your assistant, plus the errors that actually come up and their fixes.
2. [Using the dashboard](user-guide/index.md) once it is running.

### ![](assets/glyph-mic.svg)"I'm setting this up on my own hardware"

1. Your platform first: [macOS](MACOS_QUICKSTART.md) · [Jetson](JETSON_QUICKSTART.md)
   — both verified end to end — or [Linux](LINUX_QUICKSTART.md) ·
   [Windows](WINDOWS_QUICKSTART.md), which are published but not yet verified. Each
   is self-contained.
2. [Installation](INSTALLATION.md) — the overall shape, and the production reference
   for a Linux or Jetson box.
3. [Configuration](operator-manual/index.md#2-configuration) — microphones,
   detection sensitivity, retention, and the optional features.
4. [Security](security.md) — what is exposed, what is not hardened, and what to
   change before anyone but you can reach the dashboard.
5. [Running and supervision](operator-manual/index.md#5-running-supervision) —
   keeping it alive, upgrades, health checks.

### ![](assets/glyph-leaf.svg)"I care about the data — where it comes from and where it can go"

1. [Data models](Orpheus_Standard_Data_Models.md) — what a detection and an entity
   actually are.
2. [Equivalences](user-guide/index.md#equivalences-teaching-orpheus-that-two-labels-mean-one-animal)
   — how Orpheus decides two labels mean one animal, and how you correct it.
3. [Retention](operator-manual/index.md#7-data-retention) — what is kept and for how
   long.
4. [Sharing safely](security.md#recommended-deployment) — the read-only mirror, which
   ships as a CLI you schedule yourself, and the privacy-preserving public projection,
   whose dataset exists but whose hosted site does not yet.

### ![](assets/glyph-feather.svg)"I want to change how it works"

1. [Architecture](ARCHITECTURE.md) — the agents, the event bus, the correlator.
2. [Contributing](contributing.md) — the workflow, the gates, the house style.
3. [Voice and audience](contributing/voice-and-audience.md) — who we write for,
   before you write documentation.
4. [Adding an agent](agent-instructions/30-recipes-adding-agent.md) — the recipe,
   including everything you must wire up.
5. [Testing](TESTING.md) — the test suites, what each one covers, and how to run them.
6. [The Simulacrum](operator-manual/index.md#3-deployment-topologies) — running the
   whole collective in containers, with no hardware at all.

### ![](assets/glyph-lyre.svg)"I want to work on responding and vision"

The two edges of the loop that are moving right now: deciding what Orpheus says
back, and teaching it to recognize animals by sight as well as by sound.

1. [Architecture](ARCHITECTURE.md) — where the playback agent sits in the system,
   and what runs alongside it.
2. [The playback agent](https://github.com/scottchronicity/orpheus/tree/main/agents/orpheus-agent-audio-playback)
   — it plays a clip when asked; the policy that asks is what is in development.
3. [Corollary discharge](user-guide/index.md) — why the
   system tags what it played itself, off by default, so you can tell a reply from an
   animal.
4. [Entity taxonomy](adr/0016-entity-type-taxonomy.md) and
   [source identity](adr/0013-source-identity-entities.md) — knowing *who* is
   present is the prerequisite for addressing them.
5. [Adding an agent](agent-instructions/30-recipes-adding-agent.md) — the recipe, if
   you are writing a classifier for video or an agent that responds.
6. Open work is tracked in
   [GitHub Issues](https://github.com/scottchronicity/orpheus/issues) — including
   consuming the latent state-space memory, which is off by default
   (`correlation.state_space_memory_enabled`) and read by nothing.

---

## How this site is organized

- **Operator's Manual** — installing, configuring, deploying, running, and fixing.
- **User Guide** — using the dashboard.
- **Architecture & Design** — how it works and why, including the decision records.
- **Coding & Contributing** — the rules, recipes, and gates for changing Orpheus.
  Written for humans and coding agents alike; there is one documentation tree, not a
  separate one for machines.
- **Project** — the repository README, the changelog, the code of conduct, and how to
  report a vulnerability.

The larger sections open with an overview page that says what is under them. Use the
search box at the top for anything specific — it indexes every page.
