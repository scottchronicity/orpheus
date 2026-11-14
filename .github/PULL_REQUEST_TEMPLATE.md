<!--
Before opening this PR, work the checklist in
[`docs/agent-instructions/10-tooling.md`](../docs/agent-instructions/10-tooling.md)
(the "Pre-PR checklist (the actual sequence)" section).

If you're an AI coding agent, read [`AGENTS.md`](../AGENTS.md) first.
It's short by design.
-->

## Summary

<!-- 1-3 sentences. What does this PR do and why? -->

## Related issue

<!-- Fixes #N — or "None" -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (would alter existing behavior for consumers)
- [ ] Refactor (no functional changes)
- [ ] Documentation only
- [ ] Test improvement
- [ ] CI / infrastructure

## Component(s) changed

<!-- Mark every component your diff touches. -->

- [ ] `platform/orpheus-common`
- [ ] `services/orpheus_ui` (React + FastAPI)
- [ ] `services/orpheus-backplane`
- [ ] `services/orpheus-gps`
- [ ] `services/orpheus-bluetooth-autoconnect`
- [ ] `agents/orpheus-agent-audio-motion`
- [ ] `agents/orpheus-agent-audio-playback`
- [ ] `agents/orpheus-agent-audio-events`
- [ ] `agents/orpheus-agent-bird-detection`
- [ ] `agents/orpheus-agent-crow-detection`
- [ ] `agents/orpheus-agent-event-correlator`
- [ ] `agents/orpheus-agent-video-motion`
- [ ] `agents/orpheus-agent-video-snapshotter`
- [ ] `agents/orpheus-agent-video-timelapser`
- [ ] Root `Makefile` / CI workflows
- [ ] Documentation (`docs/`, `AGENTS.md`, READMEs)
- [ ] LFS-tracked artifacts (`artifacts/models/`, `artifacts/audio-samples/`)

## Pre-PR checklist

**Every box must be ticked before requesting review.** If you can't tick
one, explain why in the additional-notes section.

### Local verification (must match what CI runs)

- [ ] **Verified the working directory is clean**: no stray files,
      no committed-by-accident artifacts. `git status` is honest.
- [ ] Ran **`make lint`** from the repo root (or `make lint-<component>`
      for each component touched). Zero errors. This catches the
      "local ruff vs CI ruff" divergence that has bitten past PRs.
- [ ] Ran **`make test-all`** (or `make test-<component>` per touched
      component). All green.
- [ ] For frontend changes: also ran `npx tsc --noEmit` AND `make build`
      from `services/orpheus_ui/frontend/`. `make test` alone
      does not catch missing-file imports (this has burned us — see
      [`docs/agent-instructions/99-gotchas.md`](../docs/agent-instructions/99-gotchas.md)).

### Schema and data flow

- [ ] If I added a Pydantic field that gets persisted, I followed
      [`docs/agent-instructions/31-recipes-schema-changes.md`](../docs/agent-instructions/31-recipes-schema-changes.md)
      (9-step checklist; missed steps silently lose data).
- [ ] Any new bus subjects follow conventions in
      [`docs/agent-instructions/21-event-bus-and-data-flow.md`](../docs/agent-instructions/21-event-bus-and-data-flow.md).

### Adding a new agent

- [ ] If this PR adds an `orpheus-agent-<X>`, I followed every step in
      [`docs/agent-instructions/30-recipes-adding-agent.md`](../docs/agent-instructions/30-recipes-adding-agent.md)
      (Makefile, `pr-tests.yml`, `DEFAULT_DASHBOARD_SERVICES`,
      systemd unit, `orpheus.example.yaml`, `AGENTS.md`).

### Architecture and platform compatibility

- [ ] Read the architecture contract and affected ADRs; capability/domain,
      model, backend, IPC and host resource ownership remain explicit.
- [ ] Compatible with each changed component's declared Python/dependency range;
      runtime-specific dependencies remain isolated.
- [ ] Unsupported backend/device choices fail clearly; `auto` respects explicit
      choices. Backend changes preserve detection publication/persistence/lineage.
- [ ] Queue/retry/rejection/degradation policies are configured, observable and tested.
- [ ] Works on macOS dev AND Linux/Jetson production paths
      (`$ORPHEUS_DATA_ROOT` for persistent paths; no hardcoded
      `~/...` or `/data/orpheus`).

### Docs

- [ ] Updated relevant README / instruction files.
- [ ] If I hit a "weird library behavior" workaround that future
      agents shouldn't have to rediscover, I added it to
      [`docs/agent-instructions/99-gotchas.md`](../docs/agent-instructions/99-gotchas.md).
- [ ] If I learned something about tooling / process / git, I updated
      the relevant file under `docs/agent-instructions/`. (Explicit
      policy: future agents should not have to relearn the same
      lessons.)

## Test plan

<!--
Bulleted list of how you verified this works. For new features:
include the exact commands or UI flows. For bug fixes: include the
reproduction steps that USED to fail and now don't.
-->

## Additional notes for reviewers

<!-- Anything else worth flagging. Risk areas, trade-offs, etc. -->

## Independent review checkpoint

<!-- Keep draft until architecture, implementation and tests are independently accepted.
Tests and implementation-agent self-review are evidence, not acceptance.
Record full base/head SHAs and an exact base..head range (full PR and incremental
checkpoint where relevant), architecture decisions, commands/results, hardware
evidence with its tested SHA/config, known issues and deferred enhancements.
Explicitly hand off this PR/range; a separate reviewer conversation is not notified
by a push. Fix review findings in new commits and present a new checkpoint.
Merge and production deployment require separate authorization. -->
