# GitHub Copilot Instructions

## Core Context

**All development guidelines are in [`CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md) at the repository root.** Read that file first.

This file provides a quick reference for GitHub Copilot users.

---

## Quick Reference

### Essential Documentation
- **Core Guidelines**: [`../CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md) - Start here for all coding standards
- **Architecture**: [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) - System design and data flows
- **Testing**: [`../docs/TESTING.md`](../docs/TESTING.md) - Testing patterns and requirements
- **ADRs**: [`../docs/adr/`](../docs/adr/) - Architectural decisions

### Component-Specific
- **Agents**: [`docs/copilot-workspace-instructions/agents.instructions.md`](docs/copilot-workspace-instructions/agents.instructions.md)
- **Testing**: [`docs/copilot-workspace-instructions/tests.instructions.md`](docs/copilot-workspace-instructions/tests.instructions.md)
- **Dashboard**: [`docs/copilot-workspace-instructions/dashboard.instructions.md`](docs/copilot-workspace-instructions/dashboard.instructions.md)
- **orpheus-common**: [`docs/copilot-workspace-instructions/orpheus-common.instructions.md`](docs/copilot-workspace-instructions/orpheus-common.instructions.md)

---

## Pre-Commit Checklist

Before any commit or PR:

- [ ] **Run local tests** (`pytest` for Python, `npm test` for TypeScript)
- [ ] **Run linting** (`ruff check` for Python, `npm run lint` for TypeScript)
- [ ] **Check coverage** (minimum 70% required)
- [ ] **Review relevant ADRs** if touching architecture
- [ ] **Update documentation** if changing interfaces or behavior

**Why local first?** Cloud CI is expensive. Catch issues locally in seconds, not minutes.

---

## Python Constraints

**CRITICAL**: Python 3.9.5 compatibility required (Jetson constraint). No `match` statements, no `X | None`, no `list[str]` — use `typing` module equivalents.

See [`../CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md) for full constraints and examples.

---

## Common Patterns

See [`../CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md) for Configuration, Logging, MQTT, and Storage patterns.

---

## Testing Requirements

See [`../docs/TESTING.md`](../docs/TESTING.md) for testing framework, fixtures, and coverage requirements (70% minimum).

---

## Architectural Decision Records (ADRs)

### When to Check ADRs
- Before architectural changes
- When wondering "why is it designed this way?"
- When considering alternatives to existing patterns

### When to Create an ADR
- System architecture changes
- Technology/framework decisions
- Cross-cutting pattern changes
- Breaking changes affecting multiple components

**See [`../CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md#architectural-decision-records-adrs) for detailed ADR guidance.**

---

## File Organization

```
orpheus/
├── CODING_AGENT_CONTEXT.md     # Core guidelines (START HERE)
├── CLAUDE.md                   # Claude-specific workflow
├── docs/                       # All documentation
│   ├── ARCHITECTURE.md         # System architecture
│   ├── TESTING.md              # Testing strategy
│   ├── DASHBOARD.md            # Dashboard patterns
│   ├── adr/                    # Architectural decisions
│   └── README.md               # Documentation index
├── docs/copilot-workspace-instructions/               # Component-specific details
│   ├── agents.instructions.md
│   ├── tests.instructions.md
│   └── ...
├── platform/orpheus-common/    # Shared library
├── agents/                     # Detection agents
└── services/                   # Infrastructure services
```

---

## Make Commands

All components use standardized Makefile targets: `install`, `test`, `coverage`, `lint`, `format`, `clean`. Root-level `make *-all` targets run across all components.

See [`../CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md) for the full target reference.

---

## Known Environment Limitations

### GitHub Actions / CI Environment

**Python Version Mismatch**: The CI environment may not have Python 3.9 installed (only 3.10+). This is expected and not a blocker for documentation-only changes.

- **For code changes**: Tests will run in CI with appropriate Python version
- **For documentation changes**: Local test failures due to missing Python 3.9 can be ignored if only markdown files changed
- **Verify**: Check which files changed with `git diff --name-only` before committing

**When it's safe to skip local tests:**
- Only `.md` files changed (documentation)
- Only `docs/` directory changed
- No code changes in `platform/`, `agents/`, or `services/`

**When you MUST run local tests:**
- Any `.py` file changed
- Any `requirements.txt` or `pyproject.toml` changed
- Any configuration files changed

---

## Anti-Patterns

**DO NOT:**
- ❌ Use Python 3.10+ features (match, X | None, list[X])
- ❌ Duplicate code from orpheus-common
- ❌ Hardcode paths (use storage helpers)
- ❌ Skip type hints on public functions
- ❌ Use print() for logging (use get_logger)
- ❌ Commit without local tests and linting
- ❌ Let coverage drop below 70%
- ❌ Duplicate information across documentation files

---

## Reference Implementation

Use **`agents/orpheus-agent-audio-motion/`** as the template for:
- Agent structure and organization
- Makefile patterns
- Testing with conftest.py
- MQTT lifecycle management

---

**Remember: This is a quick reference. For complete guidelines, always consult [`../CODING_AGENT_CONTEXT.md`](../CODING_AGENT_CONTEXT.md). Do not duplicate content from that file here.**
