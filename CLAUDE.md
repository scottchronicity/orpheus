# Claude Instructions for Orpheus Repository

## Primary Context

**Read [`CODING_AGENT_CONTEXT.md`](./CODING_AGENT_CONTEXT.md) first** - it contains all core development guidelines, architecture, and workflows for this repository.

This file contains only Claude-specific tool usage and workflow notes.

---

## Claude-Specific Workflow

### Before Making Any Code Changes

1. **Read the source of truth**: Use `view` tool to read [`CODING_AGENT_CONTEXT.md`](./CODING_AGENT_CONTEXT.md)
2. **Check ADRs for context**: Review [`docs/adr/`](./docs/adr/) for architectural decisions related to your task
3. **Load context-specific quick reference**: Based on what you're editing, read the relevant workspace instruction:
   - Editing agents? → `view("docs/copilot-workspace-instructions/agents.instructions.md")`
   - Writing tests? → `view("docs/copilot-workspace-instructions/tests.instructions.md")`
   - Working on dashboard? → `view("docs/copilot-workspace-instructions/dashboard.instructions.md")`
   - Editing orpheus-common? → `view("docs/copilot-workspace-instructions/orpheus-common.instructions.md")`
4. **Check component READMEs**: Read relevant component README.md files for component-specific information

**Note**: The files in `docs/copilot-workspace-instructions/` are designed for GitHub Copilot's auto-loading feature, but Claude can benefit from them too by explicitly reading the relevant file for the task at hand.

### Critical Pre-Commit Steps

**ALWAYS run tests and linting locally before committing:**

```bash
# Python components
cd platform/orpheus-common  # or agents/*, services/*
make test                   # Must pass
make lint                   # Must pass with no errors
make coverage              # Must be ≥70%

# TypeScript components (if applicable)
npm test                   # Must pass
npm run lint              # Must pass
```

**Rationale**: Cloud CI resources are expensive. Catch issues locally first.

---

## Tool Usage Patterns

### Reading Documentation

Use `view` tool to examine referenced documentation:

```python
# Read core guidelines
view("CODING_AGENT_CONTEXT.md")

# Check architecture
view("docs/ARCHITECTURE.md")

# Review ADRs
view("docs/adr/0001-documentation-and-instruction-consolidation.md")

# Component-specific
view("docs/copilot-workspace-instructions/agents.instructions.md")
view("docs/copilot-workspace-instructions/tests.instructions.md")
```

### Running Tests and Linting

Use `bash` tool to run validation locally:

```bash
# Navigate to component
cd platform/orpheus-common

# Run tests
make test

# Check coverage
make coverage

# Lint code
make lint

# Format code
make format
```

### Making Code Changes

1. **Read first**: Understand the codebase and relevant docs
2. **Make minimal changes**: Surgical edits, not rewrites
3. **Test locally**: Run `make test` and `make lint`
4. **Verify coverage**: Run `make coverage` (≥70% required)
5. **Commit**: Only after local validation passes

---

## GitHub Copilot Workspace Instructions (for Claude)

The `docs/copilot-workspace-instructions/` directory contains **quick reference cards** designed for GitHub Copilot's file-pattern matching feature. While they auto-load for Copilot users, Claude should explicitly read them based on the task:

### When to Read Which File

| Task | File to Read |
| ------ | ------------- |
| Building/modifying an agent | `docs/copilot-workspace-instructions/agents.instructions.md` |
| Writing/fixing tests | `docs/copilot-workspace-instructions/tests.instructions.md` |
| Working on dashboard | `docs/copilot-workspace-instructions/dashboard.instructions.md` |
| Modifying orpheus-common | `docs/copilot-workspace-instructions/orpheus-common.instructions.md` |

### What These Provide

- ✅ Quick lookup patterns (e.g., common test fixtures, agent entry point patterns)
- ✅ Links to comprehensive documentation
- ✅ Component-specific anti-patterns
- ❌ NOT comprehensive guides (use main docs for that)

**Example workflow:**

```bash
# Task: Add a new test to orpheus-agent-audio-motion
view("CODING_AGENT_CONTEXT.md")                                    # Core guidelines
view("docs/TESTING.md")                                            # Comprehensive testing
view("docs/copilot-workspace-instructions/tests.instructions.md")  # Quick patterns
view("agents/orpheus-agent-audio-motion/tests/conftest.py")       # Existing fixtures
```

---

## Architecture Decision Records (ADRs)

Check `docs/adr/` before making architectural changes. See [`CODING_AGENT_CONTEXT.md`](./CODING_AGENT_CONTEXT.md#architectural-decision-records-adrs) for when to read/write ADRs.

---

## Quick Reference Links

- **Core Guidelines**: [`CODING_AGENT_CONTEXT.md`](./CODING_AGENT_CONTEXT.md)
- **Architecture**: [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)
- **Testing**: [`docs/TESTING.md`](./docs/TESTING.md)
- **ADRs**: [`docs/adr/`](./docs/adr/)
- **Component Instructions**: [`docs/copilot-workspace-instructions/`](./docs/copilot-workspace-instructions/)

---

## Anti-Patterns

Claude should **NOT**:

- ❌ Duplicate information from `CODING_AGENT_CONTEXT.md` in this file
- ❌ Override guidelines from `CODING_AGENT_CONTEXT.md`
- ❌ Skip reading `CODING_AGENT_CONTEXT.md` before making changes
- ❌ Commit code without running local tests and linting
- ❌ Use Python 3.10+ syntax (match, X | None, etc.)

---

**Remember: This file supplements [`CODING_AGENT_CONTEXT.md`](./CODING_AGENT_CONTEXT.md), it does not replace it. Always read the core guidelines first.**
