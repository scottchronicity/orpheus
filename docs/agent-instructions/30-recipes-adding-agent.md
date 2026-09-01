# 30 — Recipe: adding a new agent

When you create `orpheus-agent-<name>`, you MUST update all of these
files. Past agents have shipped new agents with one or more of these
missing, resulting in: CI silently not testing the agent, Dashboard
not showing its status, systemd not knowing how to start it. Use this
as a checklist.

## 1. Create the agent scaffolding

```
agents/orpheus-agent-<name>/
├── src/orpheus_agent_<name>/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py              # event-bus lifecycle, sub/pub
│   └── ...
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # reuse the OrpheusConfig singleton reset
│   └── test_*.py
├── systemd/
│   ├── install-service.sh
│   └── orpheus-agent-<name>.service
├── Makefile                  # copy from a sibling, change SERVICE_NAME
├── pyproject.toml            # copy from a sibling, change project name
└── requirements.txt          # `-e ../../platform/orpheus-common` + `-e .[dev]`
```

The fastest way: copy a similar agent's directory and `sed` the names.
For ML-model-running agents, copy from `orpheus-agent-bird-detection`
or `orpheus-agent-audio-events`. For sensory-input agents, copy from
`orpheus-agent-audio-motion`.

## 2. Top-level Makefile

Update **every** make target list:

- The single `.PHONY:` block at the top of the Makefile — add `install-<name>`,
  `test-<name>`, `coverage-<name>`, `lint-<name>`, `format-<name>` and
  `clean-<name>` each to the continuation line that already holds its siblings
- `PYTHON_PROJECTS` variable
- `install:` aggregate
- `install-<name>:` target (new)
- `test-<name>:` target (new)
- `coverage-all:` aggregate
- `coverage-<name>:` target (new)
- `lint:` aggregate
- `lint-<name>:` target (new)
- `format:` aggregate
- `format-<name>:` target (new)
- `clean:` aggregate
- `clean-<name>:` target (new)
- `services-install:` (add the `$(MAKE) -C agents/<name> install-service` line)
- `COMPONENT_DIRS` — add `<name>:agents/orpheus-agent-<name> \`.
  `make check-installable` fails if this and `services-install` disagree, and it
  runs in CI. Adding to `services-install` alone is the exact drift that check
  was written to catch.
- `services-start:` (add the `$(MAKE) -C agents/<name> service-start` line)
- `services-stop:` (add the `$(MAKE) -C agents/<name> service-stop` line, REVERSE ORDER)
- `help:` (add the new install-<name> line)

This is a lot of edits. **Take the time. Each missing entry breaks
something.**

## 3. CI workflow file `.github/workflows/pr-tests.yml`

The pr-tests workflow won't auto-discover your new agent. You must add:

- `env:` block: `COVERAGE_THRESHOLD_<NAME_UPPERCASE>: '70'`
- `changes` job's `outputs:` block: `<name>: ${{ steps.filter.outputs.<name> }}`
- `changes` job's `filters:` block: a `<name>:` filter matching
  `'agents/orpheus-agent-<name>/**'`
- `check-dependencies` job's `if:` condition: add
  `needs.changes.outputs.<name> == 'true' ||`
- A new `test-orpheus-agent-<name>:` job (copy from a sibling, update
  the if-condition, the install/lint/coverage commands, the artifact
  name)
- The `ci-complete:` aggregator at the bottom: add
  `- test-orpheus-agent-<name>` to its `needs:` list

If you skip any of these, CI silently doesn't run your tests on PRs.
There is no warning. We caught this once because a human noticed; it
otherwise would have shipped untested.

## 4. Dashboard service grid

`platform/orpheus-common/src/orpheus_common/config.py`:

```python
DEFAULT_DASHBOARD_SERVICES = [
    ...,
    "orpheus-agent-<name>",
    ...,
]
```

Without this, the UI's "is the system healthy?" service grid doesn't
show your agent's status.

## 5. Agent inventory in the architecture doc

Update [`docs/agent-instructions/20-architecture.md`](20-architecture.md)'s
"Components" section to list your new agent with a one-line summary.
(There's a legacy duplicate inventory in `docs/AGENTS.md`; the
deep-dive file is canonical now, but updating the legacy one too is
welcome until it gets deleted.)

## 5.5. codecov.yml: flag + project gate

`codecov.yml` has TWO blocks per component:

1. Top-level `flags:` block — defines the flag name + paths + target
2. `coverage.status.project:` block — sets the per-component coverage
   gate (CI fails if coverage drops below this)

Both need a new entry for your agent. Copy from a sibling:

```yaml
flags:
  orpheus-agent-<name>:
    paths:
      - agents/orpheus-agent-<name>/
    target: 70%

# ...further down...
coverage:
  status:
    project:
      orpheus-agent-<name>:
        flags:
          - orpheus-agent-<name>
        target: 70%
```

The pr-tests.yml workflow uploads with `flags: orpheus-agent-<name>`
matching the flag block; missing this means Codecov sees the uploads
but has no per-component gate to compare against.

## 5.6. tools/llm/ condense scripts

`tools/llm/condense_for_llm.monorepo.sh` orchestrates per-component
condense scripts that flatten a component's Python source into a
single file for LLM ingestion (used by code-review skills and
analysis tooling).

Create a new script for your agent (copy a sibling like
`tools/llm/condense_for_llm.agents.orpheus-agent-bird-detection.sh`,
substitute the component name):

```bash
cp tools/llm/condense_for_llm.agents.orpheus-agent-bird-detection.sh \
   tools/llm/condense_for_llm.agents.orpheus-agent-<name>.sh
# edit the new file: replace "orpheus-agent-bird-detection" with
# "orpheus-agent-<name>" (two spots: cd path and OUTPUT_FILE name)
chmod +x tools/llm/condense_for_llm.agents.orpheus-agent-<name>.sh
```

Then add a line to `condense_for_llm.monorepo.sh`:

```bash
"$SCRIPT_DIR/condense_for_llm.agents.orpheus-agent-<name>.sh"
```

Missing this means LLM-condense runs (used by reviews + analysis)
will silently skip your new agent.

## 5.7. scripts/dev-stack.sh — macOS dev orchestrator

The dev-stack script starts every service as a background process for
laptop smoke testing (`make dev-stack`). It has a hardcoded `SERVICES`
array — your new agent needs an entry. Insert in start-order (after
its upstream dependency, before its downstream consumers):

```bash
"<name>|agents/orpheus-agent-<name>|make run"
```

Missing this means `make dev-stack` won't start your agent —
laptop smoke tests will look like the rest of the pipeline ran fine
but your agent's path was never exercised. (This is exactly how the
audio-events agent's first smoke test missed it entirely.)

## 5.8. manifest catalog

Add `Component("<name>", "agent", _<flag>)` to `CATALOG` in
`platform/orpheus-common/src/orpheus_common/manifest_gen.py`, or the generated
`orpheus.target` never starts your agent. `make guardrails` enforces this.

## 6. config/orpheus.example.yaml (if your agent has user-facing config)

`config/orpheus.example.yaml` is the documented example config that
users copy to `/opt/orpheus/config/orpheus.yaml` on a station (or
`/etc/orpheus/orpheus.yaml`). Add a top-level `<name>:` block — there is no `# AGENTS` header in that file. Place it beside the existing per-agent sections (`bird_detection:`, `correlation:`) and match their comment style. If all your agent needs is a heartbeat cadence, extend the commented `agents:` example instead of adding a section. Give it
with your agent's defaults and concise comments explaining each knob.

Also: if your agent should appear on the Dashboard's service-grid by
default, add it under `dashboard.services` in the same file.

## 6.5. .gitignore: verify bundled data files aren't silently dropped

The repo's `.gitignore` has a Python-build-artifacts `data/` rule that
silently swallows new files in any `data/` directory. There IS a
wildcard exception for the standard agent layout:

```
!agents/*/src/*/data/
!agents/*/src/*/data/**
```

So if your agent ships bundled data files at the standard path
`agents/orpheus-agent-<name>/src/orpheus_agent_<name>/data/`, those
WILL be tracked. But verify before pushing:

```bash
git check-ignore -v agents/orpheus-agent-<name>/src/orpheus_agent_<name>/data/<file>
```

If `check-ignore` reports a hit, the wildcard exception isn't matching
your path — either you used a non-standard layout (fix the layout or
add a specific exception), or there's a more-specific rule winning
above the exception. Don't push until `git status` shows the data
files staged.

This bit us when adding the audio-events agent — the bundled 527-class
AudioSet labels CSV initially missed the wildcard exception because
of an unrelated `lib/` rule interference.

## 7. systemd unit file

`agents/orpheus-agent-<name>/systemd/orpheus-agent-<name>.service`:

```ini
[Unit]
Description=Orpheus <Name> Agent
After=network.target time-sync.target orpheus-backplane.service
Wants=orpheus-backplane.service

[Service]
Type=simple
User=orpheus
Group=orpheus
WorkingDirectory=/opt/orpheus/agents/orpheus-agent-<name>
Environment="PYTHONUNBUFFERED=1"
Environment="ORPHEUS_DATA_ROOT=/data/orpheus"
Environment="PYTHONPATH=/opt/orpheus/agents/orpheus-agent-<name>/src"
ExecStart=/opt/orpheus/agents/orpheus-agent-<name>/venv/bin/python -m orpheus_agent_<name>.main
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=orpheus-<name>

[Install]
WantedBy=multi-user.target
```

Adjust `User=orpheus` only if the agent needs different perms
(`audio` group for ALSA, `video` group for video devices, etc).

## 8. Verify locally before pushing

```bash
make install-<name>      # venv created
make test-<name>         # tests pass
make lint-<name>         # lint clean
make check-installable   # confirms COMPONENT_DIRS and services-install agree
make guardrails          # the same checks CI runs
# Do NOT run `make services-install` to verify wiring — it sudo-installs and
# enables fourteen systemd units on this machine.

# Sanity: spawn the agent and observe its health pulse
cd agents/orpheus-agent-<name>
ORPHEUS_DATA_ROOT=~/data/orpheus venv/bin/python -m orpheus_agent_<name>.main
# (Ctrl-C after you see the startup health publish on the event bus.)
```

## 9. Agent rules common to all Orpheus agents

The new agent must respect:

- **Error tracking.** Every catch block that handles an event should
  increment `self.errors_count` and set
  `self.last_error = f"{type(e).__name__}: {str(e)[:200]}"`. The
  UI's cross-agent error feed reads these from the health publishes.
- **Health heartbeat.** Spawn a 30s heartbeat task that publishes to
  `orpheus/system/<name>/health` with at minimum: status,
  events_processed, errors_count, last_error, started_at.
- **Clean shutdown.** Cancel the heartbeat task in `shutdown()` with
  `contextlib.suppress(asyncio.CancelledError)`. Publish a final
  `status: "offline"` health event.
- **Topic shape.** If you publish detections, use
  `orpheus/detection/<classifier>/events`. If you publish
  domain-specific events, use `orpheus/<domain>/<type>/events`.
- **Cross-classifier identity (Layer 1.5).** If your agent emits a
  Detection downstream of another, set `root_event_id` via
  `Detection.derive_root_event_id(parent)`. If your agent is a sensory
  source (no parent), set `root_event_id = self.event_id` AFTER
  construction.
- **Own (persist) your stream.** Your agent persists its OWN detections
  to `DetectionDB` (`db.save()` on the same `Detection` it publishes,
  preserving `event_id`/`source_event_id`/`root_event_id`). Never rely
  on another service — especially not the UI backend — to record your
  stream, and never mint a fresh `event_id` on save: those ids are the
  cross-classifier chain. Construct `DetectionDB()` at start time, not in
  `__init__` (it touches the filesystem; `__init__` must stay
  side-effect-free so the agent is constructible in tests). For a sensory
  root, persist best-effort AFTER publishing and swallow DB errors so
  storage never stalls the pipeline head. See
  [ADR 0012](../adr/0012-agents-own-their-detection-stream.md).
- **Canonical taxonomy refs.** If your agent emits species claims,
  use `TaxonomyRef(namespace="...", id="...")` with a namespace from
  `orpheus_common.detection.namespaces.KNOWN_NAMESPACES`. Don't invent
  namespaces.

See [`21-event-bus-and-data-flow.md`](21-event-bus-and-data-flow.md) and
[`22-schema-and-migrations.md`](22-schema-and-migrations.md).

## 10. Smoke test it end to end

After deploying to your dev machine:

```bash
# Watch the agent's health pulse
nats sub 'orpheus.system.<name>.health'

# Trigger whatever your agent listens to
# (audio.motion event, bird detection event, etc.)
# Verify your agent publishes the right output
nats sub 'orpheus.detection.<name>.events'
```

If you're adding an ML-model agent, also write an integration test
under `tests/integration/` that runs the real model against a bundled
audio sample and asserts the expected output. Pattern-match
`agents/orpheus-agent-audio-events/tests/integration/test_pipeline_e2e.py`
which auto-skips when the checkpoint is missing (CI-safe).

## 11. Document it (non-negotiable #12)

A new agent is operator-facing: add it to the
[Operator's Manual](../operator-manual/index.md) — what it does, its config knobs
(default state), how to run/monitor it, and any health/topics it adds. If the agent
surfaces anything new in the dashboard, also update the
[User Guide](../user-guide/index.md). Rebuild the site to check nav + links:

```bash
make docs-build
```

The agent isn't done until these land in the same change.

## When you're done

Final check:

```bash
make lint && make test-all   # everything still green
make docs-build              # docs site builds (Operator's Manual updated)
git status                   # nothing untracked
```

Then commit with a single coherent commit message that lists each
file you touched.
