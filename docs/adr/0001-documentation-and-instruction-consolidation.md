# ADR 0001: Documentation and Instruction Consolidation

**Status:** Accepted

**Date:** 2025-12-24

**Deciders:** Development Team

## Context

The Orpheus project had documentation and agent instructions scattered across multiple locations:

- Root-level architectural documents (`ARCHITECTURE.md`, `AGENTS.md`)
- Agent-specific instructions in `.github/instructions/`
- Copilot instructions in `.github/copilot-instructions.md`
- Various documentation files in `docs/`

This fragmentation led to:

1. **Duplication**: Same information repeated in multiple files
2. **Inconsistency**: Updates made to one file but not others
3. **Discovery issues**: New contributors and AI agents struggled to find the right information
4. **Maintenance burden**: Changes required updating multiple files

AI coding agents (Claude, Copilot, Cursor, etc.) needed a clear, single entry point for understanding project conventions, architecture, and development workflows.

## Decision

We will consolidate all documentation and agent instructions into a clear, maintainable structure:

### 1. Single Source of Truth for Agents

Create `CODING_AGENT_CONTEXT.md` at the repository root as the **primary reference** for all AI coding agents. This file will contain:

- Project overview and tech stack
- References to architectural documentation
- Code standards and conventions
- Development workflow (testing, linting, pre-commit requirements)
- File organization and naming conventions
- Links to component-specific instructions

### 2. Centralized Documentation in `docs/`

Move all architectural and design documentation to `docs/`:

- `ARCHITECTURE.md` → `docs/ARCHITECTURE.md`
- `AGENTS.md` → `docs/AGENTS.md`
- Consolidate testing guidance → `docs/TESTING.md`
- Consolidate dashboard guidance → `docs/DASHBOARD.md`

### 3. Architectural Decision Records

Use `docs/adr/` for all architectural decisions following the ADR pattern:

- One ADR per decision
- Immutable records (new ADRs supersede old ones, don't edit)
- Standard format: Context, Decision, Consequences

### 4. Component-Specific Instructions

Move component-specific implementation details from `.github/instructions/` to `docs/copilot-workspace-instructions/`:

- Each file references `CODING_AGENT_CONTEXT.md` for core guidelines
- Contains only implementation details specific to that component
- Removes duplication with main documentation

### 5. Agent-Specific Files as Thin Wrappers

Agent-specific files (`CLAUDE.md`, `.github/copilot-instructions.md`) become thin wrappers that:

- Reference `CODING_AGENT_CONTEXT.md` as the primary source
- Contain only agent-specific tool usage or workflow notes
- Do NOT duplicate information from CODING_AGENT_CONTEXT.md

## Rationale

### Single Source of Truth

Having one authoritative document (`CODING_AGENT_CONTEXT.md`) reduces confusion and ensures consistency. AI agents always know where to start.

### Human + Agent Readable

All documentation is written in clear markdown, accessible to both human developers and AI coding assistants.

### Separation of Concerns

- **Core guidelines**: `CODING_AGENT_CONTEXT.md`
- **Architecture/design**: `docs/`
- **Architectural decisions**: `docs/adr/`
- **Component implementation**: `docs/copilot-workspace-instructions/`
- **Agent-specific workflows**: `CLAUDE.md`, `.github/copilot-instructions.md`

### Maintainability

When conventions change, update one place (`CODING_AGENT_CONTEXT.md` or the relevant doc in `docs/`), not five different files.

### Discoverability

New contributors and AI agents can quickly find what they need by following a clear hierarchy:

1. Start with `CODING_AGENT_CONTEXT.md`
2. Consult `docs/` for architecture/design details
3. Check `docs/adr/` for architectural decisions
4. Review `docs/copilot-workspace-instructions/` for component-specific guidance

## Consequences

### Positive

- **Single entry point** for AI agents reduces confusion
- **Reduced duplication** makes maintenance easier
- **Clear hierarchy** improves discoverability
- **ADRs provide historical context** for architectural decisions
- **Consistent structure** across all documentation

### Negative

- **Migration effort** to move and update existing files
- **References must be updated** when files move
- **Discipline required** to maintain the structure (don't duplicate information)

### Neutral

- All agent-specific files must reference `CODING_AGENT_CONTEXT.md`
- Component-specific instructions must link to core docs, not duplicate them
- New architectural decisions require an ADR in `docs/adr/`

## Implementation Notes

1. Create `CODING_AGENT_CONTEXT.md` with comprehensive agent guidelines
2. Move architectural docs to `docs/` directory
3. Create consolidated `docs/TESTING.md` and `docs/DASHBOARD.md`
4. Create/update agent-specific files to reference SSOT
5. Move and update component instructions to `docs/copilot-workspace-instructions/`
6. Create `docs/README.md` as a documentation index

## Related

- `CODING_AGENT_CONTEXT.md` - The single source of truth for agents
- `docs/README.md` - Documentation index
- `docs/copilot-workspace-instructions/` - Component-specific implementation details
