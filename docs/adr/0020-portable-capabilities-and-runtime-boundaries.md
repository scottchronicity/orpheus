# ADR 0020: Portable capabilities and independent runtime boundaries

**Status:** Accepted governing contract; implementation milestone awaits independent review.

**Date:** 2026-11-14

**Decider:** Scott

**Supersedes in part:** [ADR 0009](0009-uv-python-version-management.md)'s
system-wide Python constraint. Its uv tooling decision remains in force.
Clarifies the boundaries and policy of
[ADR 0019](0019-agent-owned-inference-workers.md), without replacing its
validated PANNs implementation or hardware evidence.

## Context

The Jetson PANNs worker proved that domain agents and hardware inference can use
different runtimes. Older contributor instructions nevertheless described
Python 3.9.5, one Jetson and four sensors as platform constraints. That would
make future ports, modern supported agent runtimes and additional models
unnecessarily dependent on the validated Python 3.8 NVIDIA stack.

An earlier GPU revision also treated the correlator's three-second inactivity
window as a clip classification deadline. Removing that cutoff restored the
separation between domain correlation and execution capacity. This distinction
must survive future backend, queue and resource changes.

## Decision

**Configure the capability, not the machine.** The normative contract lives in
[Architecture](../ARCHITECTURE.md#architecture-contract), reached through the
existing AGENTS entry point, contributor guide and generated MkDocs site.

1. Agents own domain behavior and detection streams. Models own model semantics;
   hardware backends implement supported execution. Explicit unsupported choices
   fail visibly; `auto` does not override an explicit model or device choice.
2. Each component owns its runtime/dependencies. Keep the current validated
   PANNs Python 3.8 NVIDIA environment separate from agent Python 3.9 and from
   CPU installation. No Python modernization occurs in this milestone. Shared
   packages remain compatible with their actual consumers.
3. Retain `orpheus-inference` as a small process/IPC library. PANNs remains in
   its agent and worker packages. No renaming, multi-model daemon, BirdNET/video
   GPU implementation or centralized scheduler is justified by this milestone.
4. Deployment policy resolves through existing Orpheus configuration. The agent
   owns admission/queue/lifecycle/resource settings, passes limits to its child
   and exposes their effects in operational health. One installation's measured
   memory budgets inform defaults, not universal validation floors. Validate
   intrinsic constraints (positive finite values, consistent budgets and actual
   transport capacity), rather than invented deployment limits.
5. Backend changes preserve publication, persistence, lineage, taxonomy and
   interval semantics for the same scores/settings. The correlator's inactivity
   window never becomes a classification TTL. Optional loss/degradation policy
   needs an explicit owner, justification, configuration, counters and tests;
   IPC failure/recovery supplies no such domain policy by itself.
6. Sensor, model, accelerator and host counts are deployment dimensions. A
   serial worker is not a platform limit. Add host coordination only after
   measurements show aggregate contention that agent-owned workers cannot meet
   through suitable configuration or placement. Coordination does not imply
   sharing one runtime or putting all models in one process.
7. Use a shared feature branch and one draft PR as the implementation record.
   Reconcile remote history, preserve local work and append commits. Hardware
   validation checks an exact revision and returns evidence/fixes to that branch.
   Tested milestones are pushed only with user authorization. Each review
   checkpoint records an exact commit range, decisions, checks and limitations.
   Independent acceptance is separate from the implementation agent's tests and
   self-review. Review fixes append commits and require a new checkpoint. Merge
   and production deployment remain separately authorized actions.

## Consequences

Ports and future runtime upgrades can preserve domain contracts while replacing
execution details. Each backend must honestly document its actual support; this
decision does not implement MPS, multiple CUDA devices or additional GPU models.
Separate runtimes add packaging and supervision costs, but avoid a platform-wide
dependency lock. Cross-host processing still needs recording access and the
security/deployment prerequisites in ADR 0018.

The current opt-in PANNs queue rejects on overload/unavailability and has no
automatic replay. Its default pending capacity is an explicitly documented
coverage tradeoff, not a guarantee for a particular microphone count. Durable
admission/retry would need the event-sourcing acknowledgement/idempotency work;
the shadow stream does not supply it today. SQLite authority and the existing
replay gates remain unchanged.

## Enforcement and evidence

- Audio-events tests compare in-process and real pipe-worker domain output,
  persist to SQLite, classify old clips, exercise configured bursts beyond four
  sources, and verify IPC failures emit no fabricated detections or age policy.
- Configuration tests exercise YAML, optional KV and environment precedence
  through parent limits and child command arguments, and refuse unsupported
  PANNs devices and invalid concurrency/capacity.
- Infrastructure tests import without site-packages/frameworks, parse shared
  and worker sources as Python 3.8, and test real subprocess recovery/reaping.
- Configuration/manifest tests retain more than four audio and video inputs.
- `make guardrails` and `make docs-build` keep decisions and instructions
  discoverable in the same navigation used by people and agents.

These checks do not repeat or replace CUDA hardware validation. Peak overload,
maximum configured clip lengths and memory-pressure recovery still need
representative hardware evidence for production acceptance. The PR records
which evidence exists at the reviewed revision.
