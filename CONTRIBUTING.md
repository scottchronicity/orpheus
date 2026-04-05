# Contributing to Orpheus

Thank you for your interest in contributing to Orpheus. This document covers everything you need to know before opening a pull request.

---

> [!CAUTION]
> ## Python 3.9 Is Not Optional
>
> This project targets **Python 3.9.5** exclusively. This is a hard constraint imposed by NVIDIA JetPack, the firmware stack on the Jetson Orin NX hardware where Orpheus is deployed. JetPack ships a specific Python version and we cannot deviate from it.
>
> **Pull requests containing Python 3.10+ syntax will be rejected without review.** This includes, but is not limited to:
>
> - `match`/`case` statements (structural pattern matching)
> - `X | None` union syntax in type hints — use `Optional[X]` from `typing`
> - `X | Y` union types in `isinstance()` calls
> - Parenthesized context managers (`with (A() as a, B() as b):`)
> - `ExceptionGroup` and `except*`
>
> ```python
> # CORRECT — Python 3.9 compatible
> from typing import Optional, Union
>
> def find_species(code: str) -> Optional[str]:
>     ...
>
> def process(value: Union[str, int]) -> None:
>     ...
>
> # WRONG — Python 3.10+ only, PR will be rejected
> def find_species(code: str) -> str | None:
>     ...
>
> def process(value: str | int) -> None:
>     ...
> ```
>
> If you are unsure whether a syntax feature is 3.9-compatible, check [docs.python.org/3.9](https://docs.python.org/3.9/whatsnew/3.9.html) or run `python3.9 -c "import ast; ast.parse(open('yourfile.py').read())"`.

---

## Code of Conduct

This project follows a standard code of conduct. Please be respectful and constructive in all interactions.

---

## Finding Work

We use a **Backlog-as-Code** system. Our roadmap lives in [`docs/backlog.json`](docs/backlog.json), which generates GitHub Epics, labels, and sub-issues automatically. Here's how to navigate it:

### Start Here

1. **Want the big picture?** Go to [GitHub Issues](https://github.com/scottchronicity/orpheus/issues) and filter by `type: epic`. You'll see 9 Epics — from building the Cognitive Holarchy to surviving Michigan winters in a sealed enclosure. Each Epic is a tracking issue that links to its sub-tasks.
2. **Want to dive right in?** Filter by `good first issue`. These are scoped, approachable, and immediately useful. No prior context required.
3. **Want the philosophy?** Read [`docs/OPENS_SOURCE_ROADMAP_v1.md`](docs/OPENS_SOURCE_ROADMAP_v1.md) — it explains *why* we build what we build, and the tenets we won't compromise on.

### Understanding C4 Architecture Labels

Every issue is tagged with a **C4 architecture label** that tells you exactly where in the system your code belongs:

| Label | Scope | Examples |
|-------|-------|---------|
| `C4: System Context` | Ecosystem-level interactions | Wildlife modeling, weather integration, human interfaces |
| `C4: Container` | Deployable services and agents | An MQTT agent, the React dashboard, the database |
| `C4: Component` | Internal libraries and modules | Classifiers, config managers, event bus abstractions |

This isn't just bureaucracy — it's a navigation system. If you see `C4: Container` on a ticket, you're building or modifying a standalone service in `agents/` or `services/`. If you see `C4: Component`, you're working inside `platform/orpheus-common/` or a module's internals. The label tells you your blast radius before you write a line of code.

### The Standard of Quality: Gherkin Acceptance Criteria

Feature tickets in this repo contain **Gherkin acceptance criteria** — structured `Given / When / Then` scenarios that define exactly what "done" looks like:

```gherkin
Given the audio-motion agent detects a sound event
When the event exceeds the energy threshold for 200ms
Then a FLAC clip is saved with 2s pre-roll buffer
And an MQTT message is published to orpheus/audio/motion/events
```

This isn't optional decoration. These scenarios are the behavioral contract for the feature. When you pick up a ticket, your job is to make every `Then` clause true. Think of it as fulfilling a strict behavioral state machine — the Gherkin *is* the spec.

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

- **Python 3.9.5** — must be the version you use locally (use `uv` — recommended — or `pyenv`)
- **Git LFS** — for ML models and audio samples: `git lfs install && git lfs pull`
- **Make** — build automation
- **libportaudio2** and **libsndfile1** — audio I/O for local testing: `sudo apt install libportaudio2 libsndfile1` (macOS: `brew install portaudio libsndfile`)

### Quick Setup

```bash
git clone https://github.com/scottchronicity/orpheus.git
cd orpheus

make install        # Install all components
make test           # Run all tests
make coverage-all   # Check coverage (≥70% required per component)
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
| `hardware/` | No | Hardware abstraction layer (device wrappers used by agents) |

### Hardware Porting Strategy

If you want to run Orpheus on a different single-board computer (e.g., Raspberry Pi, Orange Pi, Radxa Rock), the correct approach is:

1. **Create `platform/raspberry-pi/`** (or the appropriate name) for your hardware-specific configuration
2. **Do not modify any agent or service code** — `agents/` and `services/` are already hardware-agnostic
3. Port only what differs: ALSA device aliases, GPIO mappings, service installation paths, systemd unit files

The existing agents subscribe to MQTT topics and publish to MQTT topics. They have no opinions about what hardware generated the audio or video streams. As long as the upstream agents (audio-motion, video-motion) are producing events on the correct topics, every downstream agent works unchanged.

This pattern means a Raspberry Pi deployment and a Jetson deployment can share 100% of their agent code. Only the `platform/` directory differs.

---

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/issue-description
```

### 2. Make Changes

- Read [`CODING_AGENT_CONTEXT.md`](CODING_AGENT_CONTEXT.md) before making changes — it is the single source of truth for development patterns
- Follow existing code style (Ruff formatter, 100-char line length, Google-style docstrings)
- Add tests for new functionality
- Update documentation as needed

### 3. Run Quality Checks Locally

**This is mandatory before pushing.** Cloud CI is expensive; catch issues locally first.

```bash
cd path/to/your/component   # e.g., agents/orpheus-agent-audio-motion
make lint                    # Must pass with zero errors
make test                    # Must pass
make coverage                # Must be ≥70%
```

### 4. Commit and Push

```bash
git add path/to/changed/files
git commit -m "Brief description of changes"
git push origin your-branch-name
```

### 5. Open a Pull Request

- Use the PR template
- Link related issues
- Request review from maintainers

---

## Coding Standards

### Python Style

- **Formatter**: Ruff (not Black)
- **Linter**: Ruff
- **Line length**: 100 characters
- **Python version**: **3.9 compatible only** — see the warning at the top of this document

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
- Use `@pytest.mark.asyncio` for async tests
- Mock external dependencies (MQTT broker, file I/O)
- Target ≥70% coverage (CI enforces this)

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
| Python 3.9.5 | NVIDIA JetPack system Python — non-negotiable |
| ARM64 compatible dependencies | Target deployment is ARM64 Jetson |
| No `X \| Y` type union syntax | Python 3.10+ only |
| `requirements.txt` for all components | Jetson deployment uses pip, not Poetry/uv |
| Ruff for formatting and linting | Faster than Black/flake8 on Jetson |

---

## Pull Request Checklist

- [ ] Python 3.9 compatible syntax throughout
- [ ] Tests pass (`make test`)
- [ ] Linting passes (`make lint`) with zero errors
- [ ] Coverage maintained or improved (`make coverage`)
- [ ] Documentation updated if behavior changed
- [ ] No hardcoded hardware assumptions in `agents/` or `services/`
- [ ] If porting to new hardware, changes are in a new `platform/` subdirectory

### Review Process

1. Automated CI checks must pass
2. At least one maintainer review required
3. Address all review feedback
4. Squash merge when approved

---

## Getting Help

- **Issues**: Open a GitHub Issue for bugs or concrete feature requests
- **Discussions**: Use [GitHub Discussions](https://github.com/scottchronicity/orpheus/discussions) for questions, ideas, and the Active Inference interaction policy work
- **Documentation**: [`docs/`](docs/) directory, [`CODING_AGENT_CONTEXT.md`](CODING_AGENT_CONTEXT.md)

---

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License.
