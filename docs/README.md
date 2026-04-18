# Orpheus Documentation

Central documentation hub for the Orpheus wildlife monitoring platform.

---

## For Code Agents (AI Assistants)

**Start here:** [`../CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md) - Single source of truth for all coding guidelines, workflows, and development practices.

---

## Core Documentation

### Architecture & Design

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - System architecture, component diagrams, data flows, MQTT topics
- **[AGENTS.md](./AGENTS.md)** - Agent system design, layered architecture (Layer 1/2/3), agent communication patterns
- **[TESTING.md](./TESTING.md)** - Testing strategy, patterns, fixtures, coverage requirements
- **[DASHBOARD.md](./DASHBOARD.md)** - Legacy web dashboard architecture and patterns
- **[ORPHEUS_UI.md](./ORPHEUS_UI.md)** - New React/FastAPI web UI (replacing legacy dashboard)

### Deployment & Operations

- **[DEPLOYMENT.md](./DEPLOYMENT.md)** - Quick reference for deploying to Jetson, service management, updates
- **[INSTALLATION.md](./INSTALLATION.md)** - Detailed installation guide, prerequisites, step-by-step setup
- **[CI_WORKFLOWS.md](./CI_WORKFLOWS.md)** - GitHub Actions workflows, path filtering system, adding new component tests

### Platform Quickstarts

- **[MACOS_QUICKSTART.md](./MACOS_QUICKSTART.md)** - Development/demo setup on macOS (tested)
- **[JETSON_QUICKSTART.md](./JETSON_QUICKSTART.md)** - Dev and production setup on NVIDIA Jetson Orin NX (tested)
- **[WINDOWS_QUICKSTART.md](./WINDOWS_QUICKSTART.md)** - Development via WSL2 on Windows (⚠️ untested — contributions welcome)
- **[LINUX_QUICKSTART.md](./LINUX_QUICKSTART.md)** - Development/demo on desktop Linux (⚠️ untested — contributions welcome)

### Standards & Conventions

- **[LOGGING.md](./LOGGING.md)** - Structured logging with structlog: keyword patterns, log levels, best practices
- **[Orpheus_Standard_Data_Models.md](./Orpheus_Standard_Data_Models.md)** - Canonical data structures for MQTT messages

---

## Architectural Decision Records (ADRs)

ADRs document significant architectural decisions with context, rationale, and consequences.

- **[adr/0001-documentation-and-instruction-consolidation.md](./adr/0001-documentation-and-instruction-consolidation.md)** - Documentation structure and single source of truth
- **[adr/0002-video-snapshot-architecture.md](./adr/0002-video-snapshot-architecture.md)** - Periodic camera snapshot capture design
- **[adr/0003-timelapse-generation-architecture.md](./adr/0003-timelapse-generation-architecture.md)** - Tiered timelapse system and filename format
- **[adr/0004-jetson-video-codec-strategy.md](./adr/0004-jetson-video-codec-strategy.md)** - mp4v + ffmpeg transcode for H.264 browser playback

**See [`CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md#architectural-decision-records-adrs) for guidance on when to read/write ADRs.**

---

## GitHub Copilot Workspace Instructions

**What is this?** File-scoped instructions that GitHub Copilot auto-loads based on which file you're editing.

- **[copilot-workspace-instructions/README.md](./copilot-workspace-instructions/README.md)** - Explains how these work
- **[copilot-workspace-instructions/agents.instructions.md](./copilot-workspace-instructions/agents.instructions.md)** - Quick reference when editing agent code
- **[copilot-workspace-instructions/tests.instructions.md](./copilot-workspace-instructions/tests.instructions.md)** - Quick reference when writing tests
- **[copilot-workspace-instructions/orpheus-common.instructions.md](./copilot-workspace-instructions/orpheus-common.instructions.md)** - Quick reference for shared library
- **[copilot-workspace-instructions/dashboard.instructions.md](./copilot-workspace-instructions/dashboard.instructions.md)** - Quick reference for legacy dashboard
- **[copilot-workspace-instructions/orpheus-ui.instructions.md](./copilot-workspace-instructions/orpheus-ui.instructions.md)** - Quick reference for new React/FastAPI UI
- **[copilot-workspace-instructions/ci-workflows.instructions.md](./copilot-workspace-instructions/ci-workflows.instructions.md)** - Quick reference for CI workflow modifications

These are **quick reference cards**, not comprehensive docs. They link to the main documentation.

---

## Component Documentation

### Platform

- **[../platform/orpheus-common/README.md](../platform/orpheus-common/README.md)** - Shared library overview
- **[../platform/orpheus-common/docs/](../platform/orpheus-common/docs/)** - Platform-specific docs (e.g., storage cleanup)

### Agents

- **[../agents/orpheus-agent-audio-motion/README.md](../agents/orpheus-agent-audio-motion/README.md)** - Audio motion detection (reference implementation)
- **[../agents/orpheus-agent-video-motion/README.md](../agents/orpheus-agent-video-motion/README.md)** - Video motion detection
- **[../agents/orpheus-agent-video-snapshotter/README.md](../agents/orpheus-agent-video-snapshotter/README.md)** - Periodic camera snapshots
- **[../agents/orpheus-agent-video-timelapser/README.md](../agents/orpheus-agent-video-timelapser/README.md)** - Timelapse video generation
- **[../agents/orpheus-agent-bird-detection/README.md](../agents/orpheus-agent-bird-detection/README.md)** - BirdNET species identification
- **[../agents/orpheus-agent-crow-detection/README.md](../agents/orpheus-agent-crow-detection/README.md)** - Crow vocalization analysis
- **[../agents/orpheus-agent-audio-playback/README.md](../agents/orpheus-agent-audio-playback/README.md)** - Audio output

### Services

- **[../services/orpheus-mqtt/README.md](../services/orpheus-mqtt/README.md)** - MQTT broker setup
- **[../services/orpheus-dashboard/README.md](../services/orpheus-dashboard/README.md)** - Legacy web dashboard
- **[../services/orpheus_ui/README.md](../services/orpheus_ui/README.md)** - New React/FastAPI web UI
- **[../services/orpheus-bluetooth-autoconnect/README.md](../services/orpheus-bluetooth-autoconnect/README.md)** - Bluetooth speaker connection

---

## Data Schemas

- **[schemas/](./schemas/)** - JSON schemas for MQTT message validation

---

## Documentation Principles

This is a **monorepo** - documentation follows these principles:

### Single Source of Truth

- Core guidelines live in [`CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md)
- Architecture details live in [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md)
- Component READMEs **link to** root docs, they don't duplicate them

### DRY (Don't Repeat Yourself)

- Component docs reference common docs rather than duplicating
- If something applies to multiple components → root `docs/`
- If something is component-specific → component `README.md` or `docs/`

### Consistency

- All component READMEs follow a standard structure
- No contradictions between component and root documentation
- Links point upward to root docs for shared guidance

**See [`CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md#component-level-documentation) for component documentation guidelines.**

---

## Contributing to Documentation

When updating documentation:

1. **Check existing docs first** - Don't duplicate content
2. **Update the source of truth** - Not copies of it
3. **Link, don't duplicate** - Reference other docs where appropriate
4. **Consider an ADR** - For architectural decisions
5. **Update this index** - When adding new docs

See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for contribution guidelines.
