# Decision records

Why the system is built the way it is. Each record states the problem, the
decision, and what it cost — the reasoning behind a choice, not instructions for
using it. For how to run Orpheus see the [Operator's Manual](../operator-manual/index.md);
for how to change it, [Coding & Contributing](../contributing.md). Proposals that
are not yet decisions live in [design docs](../designs/).

**Status means:** *live* — this describes the system now. *Superseded* — a later
record replaced part or all of it; the record stays, because the reasoning is
still worth reading. *Partially implemented* — the decision is made and some of
it has shipped.

| # | Title | Status |
|---|---|---|
| [0001](0001-documentation-and-instruction-consolidation.md) | Documentation and instruction consolidation | **Superseded** — `AGENTS.md` replaced `CODING_AGENT_CONTEXT.md`; themed files replaced the single-document model |
| [0002](0002-video-snapshot-architecture.md) | Video snapshot architecture | Live |
| [0003](0003-timelapse-generation-architecture.md) | Timelapse generation architecture | **Superseded in part** by [0007](0007-timelapse-scheduling-race-condition-and-label-requirement.md) — the scheduling section is dead; tiers, filenames and bucket sampling are live |
| [0004](0004-jetson-video-codec-strategy.md) | Jetson video codec strategy | Live |
| [0005](0005-event-driven-architecture-and-context.md) | Event-driven architecture with JSON sidecars | **Superseded in part** by [0006](0006-event-hierarchy-and-taxonomy.md) — the `InferenceEvent` layer is now an alias; sidecars and migration are live |
| [0006](0006-event-hierarchy-and-taxonomy.md) | Event hierarchy and taxonomy | Live |
| [0007](0007-timelapse-scheduling-race-condition-and-label-requirement.md) | Timelapse scheduling and required labels | Live — supersedes part of 0003 |
| [0008](0008-shared-makefile-deploy-logic.md) | Shared Makefile includes | Live |
| [0009](0009-uv-python-version-management.md) | uv for Python version management | Live |
| [0010](0010-birdnet-multi-label-and-soft-geo-admit.md) | BirdNET multi-label and soft geo-admit | Live — structurally a validation report rather than a decision record |
| [0011](0011-temporal-localisation-and-taxonomy-references.md) | Temporal localisation and taxonomy references | Live |
| [0012](0012-agents-own-their-detection-stream.md) | Agents own their detection stream | Live |
| [0013](0013-source-identity-entities.md) | Source-identity entities | Live — what entity merge keys on, and what it deliberately does not |
| [0014](0014-independent-component-versioning.md) | Independent component versioning | Live |
| [0015](0015-event-bus-abstraction.md) | EventBus abstraction over the transport | **Superseded in part** by [0017](0017-actor-model-nats-backplane.md) — the ABC and factory are live; its `"mqtt"` default is not |
| [0016](0016-entity-type-taxonomy.md) | Entity-type state-space taxonomy | Live |
| [0017](0017-actor-model-nats-backplane.md) | Hand-rolled actors on a NATS + JetStream backplane | Live — supersedes 0015's transport posture |
| [0018](0018-distributed-backplane-and-config-service.md) | Distributed backplane and config service | **Partially implemented** — the config backends, KV layer and `orpheus-config-push` shipped; install profiles and cert lifecycle have not |

Records are immutable once accepted: a decision that changes gets a new record
and a `Superseded` line on the old one, rather than an edit.
