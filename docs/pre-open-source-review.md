# Pre-Open-Source Review: Orpheus Repository

**Reviewed by:** Senior Engineer (first-time visitor perspective)
**Date:** April 2026
**Status:** Pre-public — most findings addressed (see PR history)

This report covers the five areas requested. Each finding includes the file, the issue, and a suggested fix. Items are ordered roughly by impact on a new visitor.

---

## 1. First Impression (README.md)

### 1.1 `docs/backlog.json` link in README is confusing context

**File:** `README.md`, line 63

**Issue:** The README states that `docs/backlog.json` "generates our GitHub Epics, labels, and sub-issues," but there is no script or tooling visible in the repo that actually does this generation. A new visitor will open the file, see raw JSON, and wonder what runs it. The README implies an automated system without showing how to invoke it.

**Suggested fix:** Either add a brief note about what tool consumes `backlog.json` (e.g., a link to a script in `tools/` or a GitHub Action), or reframe the sentence to say it is the *source of truth that was used to seed* the GitHub issues rather than implying live synchronization.

---

### 1.2 README's "Documentation" table links to `docs/adr/` directory but no specific ADR

**File:** `README.md`, line 299

**Issue:** The table entry `[docs/adr/](docs/adr/)` points to a directory. On GitHub, directory links open the file browser, which is fine — but the table entry says "Architectural Decision Records" with no example ADR linked. A visitor who has never heard of ADRs gets no entry point into *reading* one.

**Suggested fix:** Link to the most foundational ADR as the entry point (e.g., `[docs/adr/0001-documentation-and-instruction-consolidation.md](docs/adr/0001-documentation-and-instruction-consolidation.md)`) or at minimum add a parenthetical: "(9 decisions, listed in [docs/adr/](docs/adr/))".

---

### 1.3 README mentions `artifacts/audio-samples/README.md` but the file has no attribution for the Blue Jay clip author

**File:** `README.md`, line 289 / `artifacts/audio-samples/README.md`

**Issue:** The README's Acknowledgements section states "Third-party audio samples used for testing and calibration are credited in [artifacts/audio-samples/README.md](artifacts/audio-samples/README.md)." The file does exist and is reasonably complete — but the Blue Jay entry uses `Author: Jonathon Jongsma`. The contributor's canonical spelling on Xeno-canto / Wikimedia should be confirmed before going public, as public name misspellings are an easy win to fix and a visible sign of care.

**Suggested fix:** Verify the author's name spelling against the original Xeno-canto entry (XC109601) and the Wikimedia file page before the public launch.

---

### 1.4 Coverage threshold stated inconsistently between README and ARCHITECTURE.md / CI_WORKFLOWS.md

**File:** `README.md` line 228, `docs/ARCHITECTURE.md` line 577, `docs/CI_WORKFLOWS.md` line 111

**Issue:** `README.md` and `CONTRIBUTING.md` both state the coverage requirement is **≥70%**. `docs/ARCHITECTURE.md` states **"80% minimum"** and `docs/CI_WORKFLOWS.md` states **"Coverage threshold: 80%"** for the dashboard job. A new contributor who reads the architecture doc will set the wrong mental model.

**Suggested fix:** Update `docs/ARCHITECTURE.md` line 577 to read "70% minimum (CI enforced)" to match the actual CI configuration. Update `docs/CI_WORKFLOWS.md` to reflect accurate per-job thresholds or note that thresholds vary per component.

---

## 2. Contributor Experience (CONTRIBUTING.md, MACOS_QUICKSTART.md)

### 2.1 `CONTRIBUTING.md` Quick Setup omits `git lfs install` before `make install`

**File:** `CONTRIBUTING.md`, lines 111–118

**Issue:** The "Quick Setup" block runs `make install` but does not first run `git lfs install && git lfs pull`. The ML models (BirdNET ONNX, etc.) live in LFS and are needed by tests. A contributor who clones the repo without LFS installed and jumps straight to `make install` and `make test` will get confusing failures. The README's separate "Git LFS" section at the bottom (line 262) covers this, but the Quick Setup block does not.

**Suggested fix:** Add `git lfs install && git lfs pull` before `make install` in the Quick Setup code block, or add a prerequisite callout box consistent with the style used elsewhere in CONTRIBUTING.md.

---

### 2.2 `MACOS_QUICKSTART.md` "Configure for macOS" section is silent about `ORPHEUS_CONFIG_PATH`

**File:** `docs/MACOS_QUICKSTART.md`, lines 88–127

**Issue:** The guide tells users to copy `config/.env.orpheus.example` and edit it, but `make dev-stack` is documented later as loading "the Jetson config automatically." There is no explanation of when or whether to set `ORPHEUS_CONFIG_PATH`. The separate "Running individual agents" callout sets this env var, but the main flow says `make dev-stack` handles it. A first-time user will not know which mechanism takes precedence or whether they need both the `.env.orpheus` file *and* the env var.

**Suggested fix:** Add one sentence explicitly stating that `make dev-stack` reads `config/.env.orpheus` automatically and that `ORPHEUS_CONFIG_PATH` is only needed when running individual agents manually outside the dev-stack script.

---

### 2.3 CONTRIBUTING.md `make install` does not document what Python version it expects

**File:** `CONTRIBUTING.md`, lines 111–118

**Issue:** The Quick Setup block runs `make install` without specifying that Python 3.9.5 must already be installed (via `uv`) *before* running this. The Python 3.9 constraint is prominently documented, but the mechanical prerequisite of installing that Python version before `make install` is not mentioned in the Quick Setup section — it appears only later in the Prerequisites list. A reader who skips ahead will get an unhelpful error.

**Suggested fix:** Add a prerequisite step: `uv python install 3.9.5` (or `pyenv install 3.9.5`) before the `git clone` block, with a note pointing to the macOS Quick Start for the full walkthrough.

---

### 2.4 `MACOS_QUICKSTART.md` "See It Work" step references a YouTube URL as a quickstart demo

**File:** `docs/MACOS_QUICKSTART.md`, line 172

**Issue:** The guide embeds `https://www.youtube.com/watch?v=K3OdL-lAjeM` as the suggested test video. YouTube URLs go stale, get taken down, or change. This will break silently in the future and leave new visitors with a dead link in their first-run experience.

**Suggested fix:** Remove the specific URL and instead say: *"Play any YouTube video of bird calls near your laptop (search 'bird calls identification')."* This is how the sentence already begins — the embedded URL is redundant and fragile.

---

## 3. Documentation Consistency (docs/ directory)

### 3.1 Filename typo: `OPENS_SOURCE_ROADMAP_v1.md` (should be `OPEN_SOURCE_ROADMAP_v1.md`)

**File:** `docs/OPENS_SOURCE_ROADMAP_v1.md`, referenced in `README.md` line 61 and `CONTRIBUTING.md` line 56

**Issue:** The file is named `OPENS_SOURCE_ROADMAP_v1.md`. The word "OPENS" is a typo — it should be "OPEN". Both README.md and CONTRIBUTING.md link to the misspelled filename, and since the file exists with the wrong name, the links technically work — but the filename looks unprofessional to any first-time visitor navigating the repo directly.

**Suggested fix:** Rename the file to `OPEN_SOURCE_ROADMAP_v1.md` and update the two references in README.md and CONTRIBUTING.md.

---

### 3.2 `docs/AGENTS.md` structure tree uses wrong service name `orpheus-bluetooth`

**File:** `docs/AGENTS.md`, line 27

**Issue:** The repository structure tree inside `docs/AGENTS.md` shows `orpheus-bluetooth/` but the actual directory is `services/orpheus-bluetooth-autoconnect/`. This will confuse any contributor who tries to navigate to it.

**Suggested fix:** Update the tree entry to `orpheus-bluetooth-autoconnect/   # Bluetooth speaker autoconnect`.

---

### 3.3 `docs/ARCHITECTURE.md` "Future Architecture" section lists BirdNET as "Planned" — it is already built

**File:** `docs/ARCHITECTURE.md`, lines 583–607

**Issue:** The "Future Architecture" Mermaid diagram lists `BirdNET Integration (Species ID)` and `YOLOv8 Video Object Detection` under `🔮 Planned`. BirdNET is already fully operational (mentioned as complete in the README's Project Status table). This diagram is stale.

**Suggested fix:** Update the "Future Architecture" diagram to move BirdNET to the "Current" box, or remove the section entirely if it no longer reflects the actual roadmap. At minimum add a `> Note: This diagram is outdated` callout.

---

### 3.4 `docs/CI_WORKFLOWS.md` coverage threshold of 80% does not match actual CI config

**File:** `docs/CI_WORKFLOWS.md`, line 111

**Issue:** The document says the coverage threshold for the dashboard is 80%, which contradicts the 70% stated in README, CONTRIBUTING, and TESTING. Even if the actual CI YAML has different per-component thresholds, the documentation is not consistent with what contributors are told to target. See also finding 1.4.

**Suggested fix:** Audit actual per-component thresholds in `.github/workflows/pr-tests.yml` and update this doc to reflect what CI actually enforces.

---

### 3.5 `docs/crow-tools-reference.txt` is a development snapshot, not documentation

**File:** `docs/crow-tools-reference.txt`

**Issue:** This file is a snapshot of an external repository (`CROW-TOOLS REPOSITORY SNAPSHOT, Generated: 2025-12-05`) dumped into the Orpheus docs directory. It references file paths, model checkpoints, and scripts from a separate private repo. A new visitor browsing `docs/` will be confused about what this is and whether they need it. It has no `README`, no context, and no indication of what to do with it.

**Suggested fix:** Remove this file from the repository (it appears to be a development reference, not project documentation). If it serves a purpose, move it to `tools/` with a comment in the file header explaining its origin and use.

---

### 3.6 `agents/orpheus-agent-audio-motion/README.md` contains stale formatter reference and TODO items visible to public

**File:** `agents/orpheus-agent-audio-motion/README.md`, lines 79, 81, 392–395

**Issue:** Line 79 says `make format # black` — the project uses Ruff, not Black. This is incorrect and will confuse contributors. Lines 392–395 contain four `TODO` items that are visible on GitHub to any new visitor:

```
3. **TODO**: Complete pytest test suite (remove skip markers once fully tested)
4. **TODO**: Add integration tests with real MQTT broker
5. **TODO**: Implement health check endpoints for monitoring
6. **TODO**: Add metrics collection (detection rate, false positive rate, etc.)
```

Additionally, line 81 says `pytest (currently skipped pending implementation)` — but this agent does have tests and CI runs them. This is outdated.

**Suggested fix:** Change `# black` to `# ruff`. Remove or convert the TODO items to GitHub Issues before going public. Update line 81 to remove the "currently skipped" note.

---

## 4. Code Hygiene

### 4.1 DEBUG `print()` statements left in production source: `audio-motion/config.py`

**File:** `agents/orpheus-agent-audio-motion/src/orpheus_agent_audio_motion/config.py`, lines 86–108

**Issue:** Seven `print(f"DEBUG: ...")` statements remain in the `load_app_config()` function. These will fire every time the agent starts, producing raw stdout output that bypasses the structured logging system (structlog). On Jetson, this output goes to the systemd journal without context metadata.

**Suggested fix:** Replace all `print(f"DEBUG: ...")` calls with `logger.debug(...)` using the project's structlog logger, or remove them entirely if they were only used during development.

---

### 4.2 DEBUG `print()` statements in `audio-motion/audio_source.py`

**File:** `agents/orpheus-agent-audio-motion/src/orpheus_agent_audio_motion/audio_source.py`, lines 425–428 and 546–549

**Issue:** Two `print(f"DEBUG: ...")` blocks remain — one in `ALSAAudioSource.__init__()` (prints channel map on every initialization) and one in the audio callback (`if self._callback_count == 1: print(...)`). The callback is invoked at 48kHz and this guard limits the print to once, but it still writes to stdout on every agent start.

**Suggested fix:** Convert to `logger.debug()` calls or remove entirely.

---

### 4.3 `print()` statements in `orpheus-agent-bird-detection/config.py` expose internals

**File:** `agents/orpheus-agent-bird-detection/src/orpheus_agent_bird_detection/config.py`, lines 41–46

**Issue:** Two `print()` calls log the resolved model path using `print()` rather than the structlog logger. They produce output like `[BirdDetectionConfig] Using model_path from YAML: /data/orpheus/models/birdnet.onnx` — useful for debugging, but using the wrong output mechanism for a production agent.

**Suggested fix:** Replace with `logger.debug("model_path_resolved", source="yaml", model_path=model_path)` or similar structlog call.

---

### 4.4 `inspect_checkpoint.py` is a scratch/dev script committed to the agents directory

**File:** `agents/orpheus-agent-crow-detection/inspect_checkpoint.py`

**Issue:** This is a 22-line script that loads a `.pt` checkpoint and prints layer shapes. It has a hardcoded path (`/path/to/data/orpheus/models/mt_70.pt`), no docstring, and no tests. It is clearly a one-off developer utility that was never cleaned up. A new contributor who sees it will not know if it is part of the agent or vestigial.

**Suggested fix:** Either move it to `tools/` with a brief comment explaining its purpose (inspecting a PyTorch model checkpoint), or delete it. It should not live in the agent `src/` or package root.

---

### 4.5 LLM-condensing shell scripts committed to the repository root and all agent directories

**Files:**
- `condense_all.sh`
- `condense_for_llm.monorepo.sh`
- `condense_for_llm.monorepo.Makefile.sh`
- `condense_for_llm.monorepo.markdown.sh`
- `agents/orpheus-agent-audio-motion/condense_for_llm.agents.orpheus-agent-audio-motion.sh` (and one per agent)

**Issue:** These scripts generate consolidated views of the codebase for ingestion by LLMs (language models). They are a development workflow tool. Having `condense_for_llm.*` scripts at the repo root and inside each agent directory is confusing to a new visitor — they look like build artifacts, are unrelated to the project's mission, and produce output files (`.out` files) that are gitignored but whose sources are tracked. The `.gitignore` already excludes the generated output files (`*-condensed-for-llm.out`, `orpheus-condensed-for-llm-markdown.md`, etc.) but the scripts themselves are tracked.

**Suggested fix:** Move all `condense_for_llm.*.sh` scripts to a `tools/llm/` or `tools/dev/` directory and update `condense_all.sh` to reference them from there. Alternatively, document them briefly in a `tools/README.md` so their purpose is clear to visitors.

---

## 5. .gitignore and Tracked File Check

### 5.1 `.vscode/settings.json` is tracked and contains project-specific editor config

**File:** `.vscode/settings.json` (tracked by git, confirmed by `git ls-files`)

**Issue:** The file configures VS Code's Python interpreter path (`${workspaceFolder}/venv/bin/python`), which is a local development path that varies per environment. It also disables all built-in test discovery, which would silently prevent contributors using VS Code from seeing tests in the Test Explorer without understanding why. Committing IDE config is generally considered an antipattern unless the project explicitly requires it; it constrains contributors to VS Code.

**Suggested fix:** Add `.vscode/` to `.gitignore`. The `orpheus-monorepo.code-workspace` file (also tracked) can remain if the team wants to share workspace settings, but individual `settings.json` should not be committed.

---

### 5.2 `orpheus-monorepo.code-workspace` is tracked

**File:** `orpheus-monorepo.code-workspace` (tracked by git)

**Issue:** This is a VS Code workspace file. While less controversial than `settings.json`, it implies a VS Code-first workflow to contributors and will generate "Open in workspace?" prompts they may not expect. It is also stale if the directory structure changes.

**Suggested fix:** If keeping it, add a comment to the file header: `// VS Code workspace configuration for the Orpheus monorepo. Contributors using other editors can ignore this file.` If the team does not actively maintain it, add it to `.gitignore`.

---

### 5.3 `.gitignore` does not exclude `*.code-workspace` files

**File:** `.gitignore`

**Issue:** VS Code workspace files (`*.code-workspace`) are not covered by the current `.gitignore`. If additional workspace files are created, they will be tracked by default.

**Suggested fix:** Add `*.code-workspace` to `.gitignore` (unless this workspace file is intentionally shared — see 5.2).

---

### 5.4 `.gitignore` has duplicate `venv/` and `env/` entries

**File:** `.gitignore`, lines 8–9 and 90–93

**Issue:** `venv/`, `env/`, and `ENV/` appear twice in the file. This is harmless but untidy for a repository about to go public.

**Suggested fix:** Remove the duplicate entries.

---

### 5.5 `docs/crow-tools-reference.txt` is tracked (see also 3.5)

**File:** `docs/crow-tools-reference.txt`

**Issue:** This is a 2,000+ line dump of an external repository's source tree and file contents. It is tracked in git, will be cloned by every contributor, and has no apparent connection to the Orpheus documentation structure. It bloats the repository and will confuse first-time visitors to the `docs/` directory.

**Suggested fix:** Remove from git tracking (`git rm docs/crow-tools-reference.txt`) and add to `.gitignore` if there is any risk of it being regenerated.

---

## Summary Table

| # | Area | File | Severity | Type |
|---|------|------|----------|------|
| 1.1 | README | `README.md` | Medium | Unclear/missing context |
| 1.2 | README | `README.md` | Low | Missing entry point for ADRs |
| 1.3 | README | `artifacts/audio-samples/README.md` | Low | Possible attribution typo |
| 1.4 | README | `README.md`, `docs/ARCHITECTURE.md`, `docs/CI_WORKFLOWS.md` | Medium | Inconsistent coverage threshold |
| 2.1 | Contributor | `CONTRIBUTING.md` | High | Missing LFS step in quickstart |
| 2.2 | Contributor | `docs/MACOS_QUICKSTART.md` | Medium | Ambiguous config mechanism |
| 2.3 | Contributor | `CONTRIBUTING.md` | Medium | Python prerequisite missing from Quick Setup |
| 2.4 | Contributor | `docs/MACOS_QUICKSTART.md` | Low | Fragile YouTube URL in quickstart |
| 3.1 | Doc Consistency | `docs/OPENS_SOURCE_ROADMAP_v1.md` | Medium | Filename typo (OPENS vs OPEN) |
| 3.2 | Doc Consistency | `docs/AGENTS.md` | Low | Wrong service directory name |
| 3.3 | Doc Consistency | `docs/ARCHITECTURE.md` | Medium | BirdNET listed as "Planned" — already built |
| 3.4 | Doc Consistency | `docs/CI_WORKFLOWS.md` | Low | Coverage threshold mismatch |
| 3.5 | Doc Consistency | `docs/crow-tools-reference.txt` | Medium | External repo snapshot committed to docs |
| 3.6 | Doc Consistency | `agents/orpheus-agent-audio-motion/README.md` | Medium | Stale formatter ref, public TODO items, stale test note |
| 4.1 | Code Hygiene | `agents/orpheus-agent-audio-motion/src/.../config.py` | High | DEBUG print() in production code |
| 4.2 | Code Hygiene | `agents/orpheus-agent-audio-motion/src/.../audio_source.py` | High | DEBUG print() in production code |
| 4.3 | Code Hygiene | `agents/orpheus-agent-bird-detection/src/.../config.py` | Medium | print() bypassing structlog |
| 4.4 | Code Hygiene | `agents/orpheus-agent-crow-detection/inspect_checkpoint.py` | Medium | Scratch script committed to agent directory |
| 4.5 | Code Hygiene | Root + per-agent `condense_for_llm.*.sh` | Medium | Dev utility scripts scattered at root + agent level |
| 5.1 | .gitignore | `.vscode/settings.json` | Medium | IDE config tracked (path varies per environment) |
| 5.2 | .gitignore | `orpheus-monorepo.code-workspace` | Low | VS Code workspace file tracked |
| 5.3 | .gitignore | `.gitignore` | Low | `*.code-workspace` not excluded |
| 5.4 | .gitignore | `.gitignore` | Low | Duplicate venv/env/ entries |
| 5.5 | .gitignore | `docs/crow-tools-reference.txt` | Medium | External repo dump committed to docs |

---

*This review is a point-in-time snapshot intended to help prioritize cleanup before the public launch. All findings are advisory — the maintainer decides what to act on.*
