# Gemini Instructions for Orpheus Repository

## 🚨 CRITICAL: SOURCE OF TRUTH

**STOP.** Before generating any code or explanations, you MUST acknowledge that **`CODING_AGENT_CONTEXT.md`** is the single source of truth for this repository.

* **Do not** rely on general Python best practices if they conflict with that file.
* **Do not** suggest Python 3.10+ features (e.g., `match/case`, `list[str]`). We are strictly locked to **Python 3.9.5** for Jetson hardware compatibility.

## 🧠 Context Loading Strategy

To answer user queries accurately, you must retrieve and prioritize the following documentation based on the user's intent. Do not guess; fetch these files:

### 1. The Core (Always Active)
* `CODING_AGENT_CONTEXT.md`: Core development guidelines, constraints, and workflow.
* `docs/ARCHITECTURE.md`: System design and data flow diagrams.

### 2. Task-Specific Context (Fetch as needed)
Use the `File Fetcher` (or available context tool) to read the specific instruction file for the task at hand. These files contain the exact patterns you need:

| If user intent is... | Then fetch and read... |
| :--- | :--- |
| **Creating/Editing Agents** | `docs/copilot-workspace-instructions/agents.instructions.md` |
| **Writing Tests** | `docs/copilot-workspace-instructions/tests.instructions.md` |
| **Dashboard/Frontend** | `docs/copilot-workspace-instructions/dashboard.instructions.md` |
| **Shared Library/Config** | `docs/copilot-workspace-instructions/orpheus-common.instructions.md` |
| **CI/Workflows** | `docs/copilot-workspace-instructions/ci-workflows.instructions.md` |

## 🛠️ Code Generation Standards

When asked to generate code, strictly adhere to these constraints (defined fully in `CODING_AGENT_CONTEXT.md`):

1.  **Imports**: Always check `platform/orpheus-common` first. Do not re-implement Config, MQTT, or Logging.
    * *Use:* `from orpheus_common.config import OrpheusConfig`
    * *Use:* `from orpheus_common.logging import get_logger`
2.  **Type Hinting**: Use `typing` module (`List`, `Dict`, `Optional`) strictly. Do not use built-in collection types as generics.
3.  **Testing**: All new code must be testable.
    * Mock all hardware/MQTT interfaces.
    * Use `pytest-asyncio` for async tests.

## 🚫 Common Pitfalls (Do Not Do)
* **Do not** delete the `if __name__ == "__main__":` block in agents; it is required for direct execution.
* **Do not** use `black` for formatting; we use `ruff`.
* **Do not** hallucinate new MQTT topics; verify against `docs/ARCHITECTURE.md`.
