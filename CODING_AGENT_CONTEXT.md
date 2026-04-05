# Orpheus Coding Agent Context

**This is the single source of truth for all AI coding agents working on Orpheus.**

Read this file first before making any code changes. It contains all core development guidelines, architecture references, and workflows for this repository.

---

## Project Overview

**Orpheus** is a Python monorepo for wildlife monitoring and cross-species communication research, designed for real-time edge deployment on NVIDIA Jetson Orin NX hardware.

### Key Components

- **Platform**: `orpheus-common` shared library (config, MQTT, storage, logging)
- **Agents**: Independent processing agents (audio/video motion, bird detection, crow detection, playback)
- **Services**: Supporting infrastructure (MQTT broker, web dashboard, Bluetooth autoconnect)
- **Hardware**: 4-channel USB audio interface (Behringer UMC404HD), 4 IP cameras, Samsung T7 SSD storage

### Technology Stack

- **Language**: Python 3.9.5 (locked for Jetson JetPack compatibility)
- **Communication**: MQTT (Mosquitto broker)
- **ML Framework**: PyTorch with ONNX inference
- **Testing**: pytest with 70% minimum coverage
- **Linting/Formatting**: ruff only (no Black)
- **Deployment**: systemd services on Ubuntu 20.04 ARM64

---

## Architecture

### High-Level Structure

```bash
orpheus/
├── platform/orpheus-common/     # Shared library (MUST import, never duplicate)
├── services/                    # MQTT broker, dashboard, Bluetooth
├── agents/                      # Independent detection/processing agents
├── docs/                        # All documentation and ADRs
└── docs/copilot-workspace-instructions/                # Component-specific implementation details
```

### Agent Architecture

Orpheus uses a **layered agent architecture**:

- **Layer 1**: Motion detection (audio/video) - triggers on activity
- **Layer 2**: Specialized analysis (bird species ID, crow vocalization) - processes Layer 1 events
- **Layer 3**: Output (audio playback) - produces responses

### Communication Pattern

All agents communicate via **MQTT message broker**:

- Agents publish events to topic hierarchies
- Agents subscribe to relevant topics for processing
- Dashboard subscribes to all topics for monitoring

**See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for detailed architecture diagrams and data flows.**

---

## Architectural Decision Records (ADRs)

### What are ADRs?

ADRs document significant architectural decisions made in the project. They provide:

- **Context**: Why the decision was needed
- **Decision**: What was decided
- **Consequences**: Implications of the decision
- **Historical record**: Immutable documentation of past choices

ADRs are stored in `docs/adr/` and numbered sequentially (e.g., `0001-topic-name.md`).

### When to Read ADRs

**ALWAYS** check `docs/adr/` when:

- Making changes that affect system architecture
- Wondering why something is designed a certain way
- Considering alternatives to existing patterns
- Working on cross-cutting concerns (logging, config, communication)
- Adding new agents, services, or major features

**Example**: Before changing the MQTT topic structure, read ADRs about communication patterns.

### When to Write a New ADR

Create an ADR when making decisions about:

**✅ DO write an ADR for:**

- **System architecture changes**: New agent layers, communication patterns, data flow modifications
- **Technology choices**: Switching frameworks, adding new dependencies, changing deployment approach
- **Cross-cutting patterns**: New logging approach, configuration strategy, testing framework changes
- **Breaking changes**: API modifications affecting multiple components
- **Standards adoption**: Coding conventions, documentation structure (like this consolidation!)
- **Infrastructure decisions**: Storage layout, deployment model, security approach

**❌ DO NOT write an ADR for:**

- **Implementation details**: How a specific function works
- **Bug fixes**: Even significant ones (document in commit message)
- **Minor refactoring**: Code cleanup without architectural impact
- **Component-specific logic**: Algorithm choice within a single agent
- **Temporary workarounds**: Known to be replaced later
- **Obvious choices**: Using standard library features

### ADR Writing Process

1. **Create the file**: `docs/adr/XXXX-brief-title.md` (next sequential number)
2. **Use the template**:

   ```markdown
   # ADR XXXX: Brief Title
   
   **Status:** Proposed | Accepted | Deprecated | Superseded by ADR-YYYY
   **Date:** YYYY-MM-DD
   **Deciders:** [Who was involved]
   
   ## Context
   What is the issue we're facing? What constraints exist?
   
   ## Decision
   What are we doing? Be specific and concrete.
   
   ## Consequences
   ### Positive
   - What benefits does this bring?
   
   ### Negative
   - What drawbacks or costs?
   
   ### Neutral
   - What changes but isn't clearly good or bad?
   
   ## Alternatives Considered
   What other options did we evaluate? Why were they rejected?
   
   ## Related
   - Links to relevant docs, ADRs, issues
   ```

3. **Get review**: Propose the ADR in your PR for team review
4. **Mark as Accepted**: Once merged, status becomes "Accepted"
5. **Immutability**: Never edit an accepted ADR - supersede it with a new one if needed

### ADR Examples

**Good ADR topics** (from Orpheus history):

- ADR 0001: Documentation and Instruction Consolidation
- Hypothetical: "ADR 0002: MQTT Message Format Versioning Strategy"
- Hypothetical: "ADR 0003: Multi-Region Detection Database Architecture"

**NOT ADR material** (use commit messages or comments instead):

- "Changed threshold from -40dB to -35dB" (implementation detail)
- "Fixed off-by-one error in frame processing" (bug fix)
- "Refactored detector into smaller functions" (code quality)

### Quick Decision Guide

Ask yourself:

1. **Will this affect multiple components?** → Likely needs ADR
2. **Will future developers wonder why we did this?** → Likely needs ADR
3. **Is this reversible without major work?** → Probably doesn't need ADR
4. **Does this change how the system fundamentally works?** → Definitely needs ADR

**When in doubt**: Ask in PR review or create a draft ADR for discussion.

---

## Code Standards

### Python Version Constraints

**CRITICAL**: Python 3.9.5 compatibility is non-negotiable due to Jetson JetPack requirements.

**DO:**

```python
from typing import Optional, List, Dict, Union
def process(items: List[str]) -> Optional[str]:
    ...
```

**DO NOT:**

```python
# ❌ Python 3.10+ syntax - FORBIDDEN
def process(items: list[str]) -> str | None:  # NO!
    ...
match value:  # NO!
    case 1: ...
```

### Type Hints

- **Required** for all public functions and methods
- Use `typing` module imports: `Optional[X]`, `List[X]`, `Dict[K, V]`
- Avoid bare `list`, `dict`, `tuple` - import from `typing`

### Code Style

- **Formatter/Linter**: `ruff` only (never Black)
- **Line length**: 100 characters
- **Docstrings**: Google style, required for all public classes/functions
- **Imports**: Use `from orpheus_common import ...` for shared functionality

Example:

```python
from typing import Optional, List
from orpheus_common import OrpheusConfig
from orpheus_common.mqtt import MQTTClient
from orpheus_common.logging import setup_logging, get_logger

def process_audio(samples: List[float], threshold: float) -> Optional[dict]:
    """Process audio samples and detect motion.
    
    Args:
        samples: List of audio sample values.
        threshold: Detection threshold in dB.
    
    Returns:
        Detection event dict or None if no motion detected.
    """
    ...
```

### Common Patterns

#### Configuration Access

```python
from orpheus_common import OrpheusConfig
config = OrpheusConfig.get_instance()  # Singleton pattern
```

#### Logging

```python
from orpheus_common.logging import setup_logging, get_logger
setup_logging("my-agent", level="INFO")
logger = get_logger(__name__)
logger.info("Processing started")
```

#### MQTT Publishing

```python
from orpheus_common.mqtt import MQTTClient
client = MQTTClient(
    broker_host=config.mqtt.broker_host,
    broker_port=config.mqtt.broker_port,
    client_id="my-agent"
)
client.publish("orpheus/events", {"type": "detection", "value": 42})
```

#### Storage Paths

```python
from orpheus_common.storage import get_audio_path, get_video_path
audio_path = get_audio_path(category="audio_motion", channel_id="1")
# Returns: Path("/data/orpheus/audio/audio_motion/1/")
```

### MQTT Topic Conventions

| Pattern | Purpose | Example |
| --------- | --------- | --------- |
| `orpheus/{domain}/{type}/events` | Event notifications | `orpheus/audio/motion/events` |
| `orpheus/{domain}/{type}/status` | Agent status updates | `orpheus/video/motion/status` |
| `orpheus/system/{agent}/health` | Health monitoring | `orpheus/system/dashboard/health` |

---

## Development Workflow

### Pre-Commit Checklist

**ALWAYS** complete these steps locally before committing:

1. **Run tests locally**:

   ```bash
   # For Python components
   cd platform/orpheus-common  # or agents/*, services/*
   make test
   
   # For TypeScript components
   npm test
   ```

2. **Run linting locally**:

   ```bash
   # For Python
   make lint
   
   # For TypeScript
   npm run lint
   ```

3. **Check coverage** (70% minimum):

   ```bash
   make coverage
   ```

4. **Format code**:

   ```bash
   make format
   ```

### Why Local Tests First?

- **Cloud resources are expensive** - don't waste CI minutes on fixable issues
- **Faster feedback** - local tests run in seconds vs. minutes in CI
- **Good practice** - ensures you understand the impact of your changes
- **Coverage gate** - CI will fail below 70% coverage, catch it locally first

### Standard Makefile Targets

Every Python component has these targets:

```bash
make install          # Create venv, install deps including orpheus-common
make test             # Run pytest
make coverage         # pytest --cov with report
make lint             # ruff check
make format           # ruff format
make clean            # Remove venv and caches
make install-service  # Deploy systemd unit (requires sudo)
make deploy           # Sync source code to /opt/orpheus/ production path
make update           # git pull + reinstall + deploy + restart
make service-logs     # journalctl -f
```

### Shared Makefile Includes

Common targets are provided by shared includes in `make/` (see [ADR 0008](docs/adr/0008-shared-makefile-deploy-logic.md)):

| Include | Provides |
|---------|----------|
| `common_python.mk` | Python venv, version checks, tool paths (`PYTHON`, `PIP`, `PYTEST`, `RUFF`) |
| `common_lint.mk` | `lint`, `format`, `check` targets via ruff |
| `common_deploy.mk` | `deploy` target — rsync source to `/opt/orpheus/`, copy metadata, pip install |
| `common_service.mk` | `start`, `stop`, `restart`, `status`, `logs`, `install-service` via systemd |

Component Makefiles set identity variables (`SERVICE_NAME`, `DEPLOY_ROOT`) and include the relevant shared files. See `make/README.md` for details.

### Root-Level Commands

```bash
# From repository root
make install      # Install all components
make test         # Test all components
make lint         # Lint all components
make format       # Format all components
make coverage-all # Coverage for all components
```

---

## File Organization

### Documentation Hierarchy

1. **`CODING_AGENT_CONTEXT.md`** (this file) - Start here, core guidelines
2. **`docs/ARCHITECTURE.md`** - Detailed system architecture, diagrams, data flows
3. **`docs/AGENTS.md`** - Agent system design, layer architecture
4. **`docs/TESTING.md`** - Testing strategy, patterns, fixtures
5. **`docs/DASHBOARD.md`** - Dashboard design, API patterns
6. **`docs/adr/`** - Architectural Decision Records (immutable historical records)
7. **`docs/copilot-workspace-instructions/`** - Component-specific implementation details

### When to Consult Each Document

- **Making any code change?** Read this file first
- **Architectural questions?** Check `docs/ARCHITECTURE.md` and `docs/adr/`
- **Creating a new agent?** Read `docs/AGENTS.md` and `docs/copilot-workspace-instructions/agents.instructions.md`
- **Writing tests?** Consult `docs/TESTING.md` and `docs/copilot-workspace-instructions/tests.instructions.md`
- **Dashboard work?** See `docs/DASHBOARD.md` and `docs/copilot-workspace-instructions/dashboard.instructions.md`
- **Working on orpheus-common?** Check `docs/copilot-workspace-instructions/orpheus-common.instructions.md`

### Agent-Specific Files

- **`CLAUDE.md`** - Claude-specific workflow and tool usage
- **`.github/copilot-instructions.md`** - GitHub Copilot quick reference

These files are thin wrappers that reference this document. They do NOT duplicate core guidelines.

---

## Testing Strategy

### Framework & Requirements

- **Framework**: pytest with pytest-asyncio
- **Async mode**: `asyncio_mode = "auto"` in pytest.ini
- **Coverage**: 70% minimum (enforced by CI)
- **Mocking**: unittest.mock for external dependencies

### What to Test

- All public functions and methods
- Error handling paths (test with invalid inputs)
- Edge cases (empty input, None values, boundary conditions)
- MQTT message handling with various payloads
- Configuration loading with missing/invalid values

### What to Mock

- MQTT connections and publishing
- File system operations (use `tmp_path` fixture)
- External services and hardware
- `OrpheusConfig` (unless testing config itself)
- Time-dependent operations

### Example Test Pattern

```python
import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_config():
    with patch("orpheus_common.config.OrpheusConfig.get_instance") as mock:
        config = MagicMock()
        config.mqtt.broker_host = "localhost"
        config.mqtt.broker_port = 1883
        mock.return_value = config
        yield config

def test_my_function(mock_config):
    """Test normal operation."""
    result = my_function()
    assert result is not None
```

**See [`docs/TESTING.md`](docs/TESTING.md) for comprehensive testing patterns and fixture examples.**

---

## Component-Specific Instructions

The `docs/copilot-workspace-instructions/` directory contains implementation details for specific components:

- **`docs/copilot-workspace-instructions/agents.instructions.md`** - Agent development template, structure, patterns
- **`docs/copilot-workspace-instructions/tests.instructions.md`** - Test development patterns, fixtures, organization
- **`docs/copilot-workspace-instructions/orpheus-common.instructions.md`** - Shared library guidelines, module responsibilities
- **`docs/copilot-workspace-instructions/dashboard.instructions.md`** - Dashboard API patterns, frontend guidelines

**Each instruction file references this document for core guidelines and contains ONLY component-specific details.**

### Component-Level Documentation

**This is a monorepo** - each component has its own README.md but shares common documentation.

#### Component README.md Structure

Each agent/service MUST have a README.md that follows this pattern:

```markdown
# Component Name

Brief description of what this component does.

## For Developers
**See repository root documentation for:**
- [Development Guidelines](../../CODING_AGENT_CONTEXT.md) - Core coding standards
- [Testing Strategy](../../docs/TESTING.md) - How to write tests
- [Architecture](../../docs/ARCHITECTURE.md) - System design

## Component-Specific Information
[Only document what's unique to this component:]
- Installation/deployment instructions
- Component-specific configuration
- Usage examples
- API documentation (if applicable)
```

#### DRY Principles for Component Docs

- ✅ **DO** link to root-level docs for shared guidelines
- ✅ **DO** document component-specific behavior and configuration
- ✅ **DO** include quick-start examples unique to the component
- ❌ **DON'T** duplicate coding standards (link to `CODING_AGENT_CONTEXT.md`)
- ❌ **DON'T** duplicate testing patterns (link to `docs/TESTING.md`)
- ❌ **DON'T** duplicate architecture explanations (link to `docs/ARCHITECTURE.md`)

#### Component-Specific Docs

Beyond READMEs, components may have their own `docs/` directories:

- **`platform/orpheus-common/docs/`** - Platform library specific docs (e.g., storage cleanup integration)
- **Component docs/** - Detailed component-specific documentation

**Rule**: If something applies to multiple components, it belongs in root `docs/`, not component docs.

---

## Key Reference Documents

### Must-Read for All Changes

- **This file** (`CODING_AGENT_CONTEXT.md`) - Core guidelines, start here
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - System architecture and design
- [`docs/adr/`](docs/adr/) - Architectural Decision Records

### Domain-Specific

- [`docs/AGENTS.md`](docs/AGENTS.md) - Agent system, Layer 1/2/3 architecture
- [`docs/TESTING.md`](docs/TESTING.md) - Testing strategy and patterns
- [`docs/DASHBOARD.md`](docs/DASHBOARD.md) - Dashboard architecture and API design

### Component Implementation

- [`docs/copilot-workspace-instructions/agents.instructions.md`](docs/copilot-workspace-instructions/agents.instructions.md) - How to build agents
- [`docs/copilot-workspace-instructions/orpheus-common.instructions.md`](docs/copilot-workspace-instructions/orpheus-common.instructions.md) - Shared library guide
- [`docs/copilot-workspace-instructions/tests.instructions.md`](docs/copilot-workspace-instructions/tests.instructions.md) - How to write tests
- [`docs/copilot-workspace-instructions/dashboard.instructions.md`](docs/copilot-workspace-instructions/dashboard.instructions.md) - Dashboard implementation

### Reference Implementation

Use **`agents/orpheus-agent-audio-motion/`** as the template for new agents:

- Directory structure and file organization
- Makefile targets and patterns
- systemd service setup scripts
- Test organization with conftest.py
- MQTT lifecycle management in main.py

---

## Anti-Patterns (DO NOT DO)

### Code

- ❌ Use Python 3.10+ syntax (`match`, `X | None`, bare `list[X]`)
- ❌ Add Black as a dependency (use ruff only)
- ❌ Hardcode paths (use storage helpers from orpheus_common)
- ❌ Duplicate MQTT/config code (use orpheus_common)
- ❌ Use `print()` for logging (use get_logger)
- ❌ Skip type hints on public functions
- ❌ Create new config files (use OrpheusConfig singleton)

### Testing

- ❌ Skip tests because "it's just a small change"
- ❌ Skip mocking external dependencies
- ❌ Let coverage drop below 70%
- ❌ Only test happy paths (test errors and edge cases!)

### Workflow

- ❌ Commit without running tests locally first
- ❌ Commit without running linting locally first
- ❌ Push code that doesn't meet coverage requirements
- ❌ Duplicate information across documentation files

---

## Critical Workflow Rules

### For Cloud Agents (GitHub Actions, etc.)

Before triggering any expensive cloud operations:

1. **VERIFY** local tests pass (`make test`)
2. **VERIFY** local linting passes (`make lint`)
3. **VERIFY** coverage meets 70% minimum (`make coverage`)
4. **ONLY THEN** push changes to trigger CI/CD

### For All Code Changes

1. Read `CODING_AGENT_CONTEXT.md` (this file) first
2. Consult relevant docs in `docs/` and `docs/copilot-workspace-instructions/`
3. Make minimal, surgical changes
4. Write/update tests for your changes
5. Run tests and linting locally
6. Ensure coverage stays ≥70%
7. Commit and push

### For Documentation Changes

1. Update the canonical source (don't duplicate)
2. If changing conventions, update `CODING_AGENT_CONTEXT.md`
3. If changing architecture, consider an ADR in `docs/adr/`
4. Keep component instructions in `docs/copilot-workspace-instructions/` minimal (link to docs, don't duplicate)

---

## Quick Command Reference

```bash
# Development workflow
cd platform/orpheus-common  # or agents/*, services/*
make install                # Setup environment
make test                   # Run tests
make coverage               # Check coverage
make lint                   # Check code style
make format                 # Auto-format code

# Root-level commands
make install-all            # Install everything
make test-all               # Test everything
make coverage-all           # Coverage for everything
make lint-all               # Lint everything
make format-all             # Format everything

# Production deployment (Jetson)
make services-install       # Install all systemd services
make services-start         # Start all services
make services-stop          # Stop all services
make status-all             # Check service status
make update-all             # Update and restart all
```

---

## Getting Help

- **Architecture questions?** Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **How to build an agent?** Read [`docs/AGENTS.md`](docs/AGENTS.md) and [`docs/copilot-workspace-instructions/agents.instructions.md`](docs/copilot-workspace-instructions/agents.instructions.md)
- **Testing patterns?** Read [`docs/TESTING.md`](docs/TESTING.md)
- **Dashboard work?** Read [`docs/DASHBOARD.md`](docs/DASHBOARD.md)
- **Architectural decisions?** Browse [`docs/adr/`](docs/adr/)
- **Component-specific?** Check [`docs/copilot-workspace-instructions/`](docs/copilot-workspace-instructions/) for the relevant file

---

**Remember: This file is your starting point. Read it before making changes, and always run tests and linting locally before committing.**
