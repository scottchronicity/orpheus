# Contributing to Orpheus

Thank you for your interest in contributing to Orpheus. This document covers everything you need to know before opening a pull request.

---

## Architecture and runtime compatibility

Read [AGENTS.md](AGENTS.md), then the [architecture contract](docs/ARCHITECTURE.md#architecture-contract)
and [ADR 0020](docs/adr/0020-portable-capabilities-and-runtime-boundaries.md)
before changing architecture, configuration, runtimes or deployment.
**Configure the capability, not the machine.** Agents own domain behavior;
model/backend implementations and their runtimes remain replaceable.

Python versions belong to components. Most current agents/services declare
Python 3.9; the validated Jetson PANNs CUDA worker declares Python 3.8 with its
pinned NVIDIA stack; shared IPC supports 3.8+. Follow each package's metadata,
constraints, Makefile and Ruff target. This assignment does not modernize those
runtimes, and the worker does not prevent future agent modernization.

For current Python 3.9 components, postponed annotations permit `X | None` and
`list[X]`; expressions evaluated at runtime still need compatible types. Syntax
and dependencies must work on the component's declared interpreters. Do not use
newer language features merely because your development interpreter accepts them.

---

## Code of Conduct

This project follows a standard code of conduct. Please be respectful and constructive in all interactions.

---

## How We Work Together

**Protect the live field station.**

Driving into the freezing woods to reboot a locked-up Jetson is nobody's idea of a good time. Wild experimentation is welcome; the core runtime has to stay bulletproof. In exchange for respecting the hardware, maintainers get deep autonomy over their domains.

- **Earn your domain.** Step up to reliably maintain a module and it's yours — you set the direction and own the decisions. Trust here is proportional to what you carry.
- **Don't break the tank.** The station is a real, physical thing sitting in a Michigan wetland. A change that destabilizes the production deployment gets reverted first and discussed second. Nothing personal; the animals don't wait for hotfixes.
- **Strong opinions, loosely held.** Every architectural choice in this repo has a reason, and none of them are sacred. Bring a better idea and we'll listen — that's what the [ADRs](docs/adr/) are for.

---

## Finding Work

We use a **Backlog-as-Code** system. Our roadmap lives in [`docs/backlog.json`](https://github.com/scottchronicity/orpheus/blob/main/docs/backlog.json), which seeds the labels, milestones, and issues on GitHub automatically. Here's how to navigate it:

### Start Here

1. **Want the big picture?** Work is grouped into eight themes, each a milestone on [GitHub Issues](https://github.com/scottchronicity/orpheus/issues) — from recognising what is out there to surviving Michigan winters in a sealed enclosure. Filter by a milestone to see a theme's open work. There is one stream and no epics: every item is a story someone can pick up.
2. **Want to dive right in?** Filter by `good first issue`. These are deliberately small and self-contained: a shared helper to extract, a caching bug with a known reproduction, a table column, a docs page to keep honest. No prior context required.
3. **Want the reasoning behind a design?** The [ADRs](docs/adr/) record why each architectural choice was made, and the [design docs](docs/designs/) cover the features they describe.

### Understanding C4 Architecture Labels

Every issue is tagged with a **C4 architecture label** that tells you exactly where in the system your code belongs:

| Label | Scope | Examples |
|-------|-------|---------|
| `C4: System Context` | Ecosystem-level interactions | Wildlife modeling, weather integration, human interfaces |
| `C4: Container` | Deployable services and agents | An MQTT agent, the React dashboard, the database |
| `C4: Component` | Internal libraries and modules | Classifiers, config managers, event bus abstractions |

If you see `C4: Container` on a ticket, you're building or modifying a standalone service in `agents/` or `services/`. If you see `C4: Component`, you're working inside `platform/orpheus-common/` or a module's internals. The label tells you your blast radius before you write a line of code.

### The Standard of Quality: a stated Definition of Done

Every ticket says what "done" means before you start. Most use a short **Definition of Done** — a few sentences of observable outcome. The largest and most behavioral ones go further and use **Gherkin acceptance criteria**, structured `Given / When / Then` scenarios:

```gherkin
Given the audio-motion agent detects a sound event
When the event exceeds the energy threshold for 200ms
Then a FLAC clip is saved with 2s pre-roll buffer
And an MQTT message is published to orpheus/audio/motion/events
```

Where a ticket has them, they are the behavioral contract: your job is to make every `Then` clause true, and the Gherkin *is* the spec. Where a ticket has a prose Definition of Done instead, that is the bar. Either way, if the acceptance criteria are vague or you disagree with them, say so on the ticket before writing code — sharpening them is a contribution in itself.

### Spikes & ADRs

Some tickets are labeled `type: spike`. These are different from feature work. A spike is a **time-boxed research task**, and the expected deliverable is an **Architectural Decision Record (ADR)** — not necessarily a massive code PR.

If you pick up a spike:

1. Research the problem within the time box described in the ticket
2. Write an ADR in `docs/adr/` documenting what you found, what you recommend, and why
3. Open a PR with the ADR for review and discussion

Spikes exist because we'd rather have a well-reasoned decision document than a speculative implementation that paints us into a corner. See existing ADRs in [`docs/adr/`](docs/adr/) for the format and tone.

---

## Development Setup

> **On macOS?** See the **[macOS Quick Start](docs/MACOS_QUICKSTART.md)** for a streamlined guide that gets you from zero to a running dashboard in 15 minutes, including `make dev-stack` to start the full Observe stack with one command.

### Prerequisites

- **The component-compatible Python interpreter** — the current default developer toolchain is 3.9.5 (uv recommended); optional CUDA workers use their own pinned runtime
- **Git LFS** — for ML models and audio samples: `git lfs install && git lfs pull`
- **Make** — build automation
- **libportaudio2** and **libsndfile1** — audio I/O for local testing: `sudo apt install libportaudio2 libsndfile1` (macOS: `brew install portaudio libsndfile`)

### Quick Setup

> For the current default agent setup, ensure Python 3.9.5 is active (`python3 --version`). See Prerequisites above or the [macOS Quick Start](docs/MACOS_QUICKSTART.md) for installation via uv or pyenv.

```bash
git clone https://github.com/scottchronicity/orpheus.git
cd orpheus
git lfs install && git lfs pull   # Fetch ML models (~1.5 GB)

make install        # Install all components
make test           # Run all tests
make coverage-all   # Check coverage against each component's floor
```

---

## Repository Structure

The monorepo is organized around a strict separation of concerns:

| Directory | Hardware-specific? | Description |
|---|---|---|
| `platform/jetson-orin-nx-yahboom/` | **Yes** | ALSA config, GPIO, display, network setup for the Yahboom Jetson board |
| `platform/orpheus-common/` | No | Shared Python library: config, MQTT, logging, storage, DetectionDB |
| `agents/` | **No** | Detection and analysis agents — pure Python, no hardware assumptions |
| `services/` | **No** | Infrastructure services — MQTT broker, dashboards, GPS, Bluetooth |
| `hardware/` | No | Hardware interface design notes; implemented capture adapters live with their agents |
| `platform/orpheus-inference/` | No | Dependency-free subprocess IPC and supervision |
| `workers/` | Backend-specific | Optional model implementations with independent runtimes |

### Hardware Porting Strategy

Preserve domain agents when porting to another platform. Hardware setup belongs
in the platform configuration; capture and inference differences belong behind
replaceable backends in their owning components. Existing audio source factories,
camera registry and `SEDModel` interface are the seams to inspect. The `hardware/`
folder describes intended interfaces; it is not a shipped universal driver package.

Do not claim a port works until its dependencies and backend have been validated.
A Raspberry Pi may use CPU inference; a Jetson may select the isolated CUDA worker.
Those choices must preserve event/detection semantics and use Orpheus configuration.
See the [architecture contract](docs/ARCHITECTURE.md#architecture-contract).

---

## Making Changes

### 1. Reconcile or create a branch

For an existing feature, use its shared remote branch. Fetch and compare local
and remote history before edits; preserve all commits and uncommitted work.
Fast-forward when possible, and reconcile divergence without rewriting remote
history. One branch has one PR. Create a branch only for new work:

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/issue-description
```

### 2. Make Changes

- Read [`AGENTS.md`](AGENTS.md) before making changes — it carries the non-negotiable rules and routes to the themed guides in [`docs/agent-instructions/`](docs/agent-instructions/) (tooling, testing, git, CI, architecture, recipes, gotchas)
- Follow existing code style (Ruff formatter, 100-char line length, Google-style docstrings)
- Add tests for new functionality
- Update documentation as needed

### 3. Run Quality Checks Locally

**This is mandatory before pushing.** Cloud CI is expensive; catch issues locally first.

```bash
cd path/to/your/component   # e.g., agents/orpheus-agent-audio-motion
make lint                    # Must pass with zero errors
make test                    # Must pass
make coverage                # Must meet this component's floor

cd -                         # back to the repo root
make guardrails              # Must pass — CI blocks the merge on it
```

`make guardrails` is the one gate people miss. It checks the mechanical rules a
change can break silently: that a new agent is wired into every place it has to be,
that the manifest catalog covers it, that a new design doc or ADR is reachable from
the docs site, and that the non-negotiables stay coherent. It runs on every pull
request and it blocks the merge, so run it before you push.

### 4. Commit and Push

```bash
git status                    # once — check nothing unexpected is staged or ignored
git add -A
git commit -m "feat(<scope>): <imperative summary>"
git push origin your-branch-name
```

### 5. Open a draft PR and hand off independent review

Use the [shared development and independent review workflow](docs/agent-instructions/12-git-and-lfs.md#shared-development-and-independent-review).
Keep one draft PR as the implementation record. Include architecture/ADR decisions,
exact check commands/results, hardware evidence tied to its tested SHA/config,
known limitations, and full base/head SHAs with the exact review range.
Explicitly present the PR/range to the independent reviewer; a push does not notify
a separate review conversation automatically. Tests and self-review are not
independent acceptance. Address findings in new commits and hand off a new range.
Keep draft until architecture, implementation and tests are accepted; merge and
production deployment need separate explicit authorization.

Hardware validators test an agreed revision in a separate checkout and return
evidence/fixes to the shared branch. They do not become a competing development
owner or gain authorization to change production by running a trial.

---

## Coding Standards

### Python Style

- **Formatter**: Ruff (not Black)
- **Linter**: Ruff
- **Line length**: 100 characters
- **Python version**: compatible with the changed component and all consumers of shared code

### Type Hints

All public function signatures must have type hints. Use `typing` module imports:

```python
from typing import Any, Dict, List, Optional

def process_audio(data: bytes, sample_rate: int = 48000) -> List[float]:
    ...

def find_agent(name: str) -> Optional[str]:
    ...
```

### Docstrings

Follow Google-style docstrings:

```python
def process_audio(data: bytes, sample_rate: int = 48000) -> List[float]:
    """Process raw audio data and return normalized samples.

    Args:
        data: Raw audio bytes in int16 format.
        sample_rate: Sample rate in Hz.

    Returns:
        List of normalized float samples in range [-1.0, 1.0].

    Raises:
        ValueError: If data length is not divisible by 2.
    """
```

### Testing

- Write tests using pytest
- Don't mark async tests — components that need it set `asyncio_mode = auto` in their `pytest.ini`
- Mock external dependencies (MQTT broker, file I/O)
- Coverage floors are per-component: 70% for most, 78% for `orpheus-common`,
  72% for `audio-motion`. `codecov.yml` and the `env:` block of
  `.github/workflows/pr-tests.yml` hold the real numbers. Note the local make
  targets are stricter than CI for two components, so a local pass is a safe
  bet but not an identical check.

```python
import pytest

@pytest.mark.asyncio
async def test_audio_source_starts():
    source = MockAudioSource(48000, 100, 50)
    await source.start()
    assert source.is_running()
```

---

## Platform Constraints Summary

| Constraint | Reason |
|---|---|
| Per-component Python versions | Preserve declared runtime and dependency compatibility |
| Backend/platform-compatible dependencies | Validate every claimed supported path |
| Runtime-compatible syntax and evaluated types | Follow package metadata and Ruff targets |
| `requirements.txt` for all components | Jetson deployment uses pip, not Poetry/uv |
| Ruff for formatting and linting | Faster than Black/flake8 on Jetson |

---

## Pull Request Checklist

- [ ] Runtime compatibility preserved for each changed component
- [ ] Tests pass (`make test`)
- [ ] Linting passes (`make lint`) with zero errors
- [ ] Coverage maintained or improved (`make coverage`)
- [ ] Guardrails pass (`make guardrails`)
- [ ] Documentation updated if behavior changed
- [ ] No hardcoded hardware assumptions in `agents/` or `services/`
- [ ] Platform setup and backend implementations preserve agent/domain semantics

### Review Process

1. Automated CI checks must pass
2. At least one maintainer review required
3. Address all review feedback
4. Leave draft only after independent acceptance; merge/deploy only with separate authorization

---

## Getting Help

- **Issues**: Open a GitHub Issue for bugs or concrete feature requests
- **Discussions**: Use [GitHub Discussions](https://github.com/scottchronicity/orpheus/discussions) for questions, ideas, and the Active Inference interaction policy work
- **Documentation**: the [documentation site](https://scottchronicity.github.io/orpheus/docs/) or the [`docs/`](docs/) directory in a checkout; [`AGENTS.md`](AGENTS.md) for the rules a change has to hold

---

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License.
