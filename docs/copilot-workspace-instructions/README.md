# GitHub Copilot Workspace Instructions

This directory contains **file-scoped instructions for GitHub Copilot** using the `applyTo` frontmatter pattern.

## What Are These Files?

These are NOT general documentation. They are **context-specific instructions** that GitHub Copilot automatically loads when you edit files matching the `applyTo` pattern.

### How It Works

When you edit a file in VS Code with GitHub Copilot:

1. Copilot checks these instruction files for matching `applyTo` patterns
2. If a pattern matches your current file, Copilot loads those instructions
3. This gives Copilot context-specific guidance for that component

### Example

When editing `agents/orpheus-agent-audio-motion/src/orpheus_agent_audio)_motion/main.py`:

- ✅ **Loads**: `agents.instructions.md` (matches `agents/**`)
- ✅ **Loads**: `tests.instructions.md` if it's a test file
- ❌ **Ignores**: `dashboard.instructions.md` (doesn't match pattern)

## File Descriptions

| File | Pattern | Purpose |
| ------ | --------- | --------- |
| `agents.instructions.md` | `agents/**` | Quick reference for agent development patterns |
| `tests.instructions.md` | `**/tests/**` | Quick reference for writing tests |
| `dashboard.instructions.md` | `services/orpheus-dashboard/**` | Quick reference for dashboard development |
| `orpheus-common.instructions.md` | `platform/orpheus-common/**` | Quick reference for shared library work |

## Why Quick References?

These files:

- ✅ **Provide quick lookups** for common patterns when editing code
- ✅ **Link to comprehensive docs** (like `docs/TESTING.md`) for details
- ✅ **Don't duplicate** - they reference the main documentation
- ✅ **Auto-apply** based on file location - no manual selection needed

## Relationship to Main Docs

```bash
CODING_AGENT_CONTEXT.md           ← Single source of truth for ALL agents
        ↓
docs/ARCHITECTURE.md              ← Comprehensive architecture
docs/TESTING.md                   ← Comprehensive testing guide
docs/AGENTS.md                    ← Comprehensive agent guide
        ↓
docs/copilot-workspace-instructions/  ← Quick references that auto-apply per file
```

## When to Edit These Files

**Edit when:**

- Patterns change that are specific to a component type
- Quick reference examples need updating
- Links to main docs need correction

**Don't edit when:**

- Making architectural changes (update ADRs instead)
- Changing core guidelines (update `CODING_AGENT_CONTEXT.md` instead)
- Adding comprehensive content (update main docs instead)

---

**For comprehensive documentation, see:**

- [`../CODING_AGENT_CONTEXT.md`](../../CODING_AGENT_CONTEXT.md) - Core development guidelines
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) - System architecture
- [`../TESTING.md`](../TESTING.md) - Testing strategy
- [`../AGENTS.md`](../AGENTS.md) - Agent design patterns
- [`../DASHBOARD.md`](../DASHBOARD.md) - Dashboard architecture
