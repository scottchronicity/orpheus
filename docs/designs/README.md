# Design docs

Working documents: the shape of a change and its trade-offs, written before or
alongside the code. They are not reference — a design doc can describe something
that shipped differently, or has not shipped at all, so check its status line
before trusting a detail. Decisions that were *made* live in
[decision records](../adr/); how to run what shipped is the
[Operator's Manual](../operator-manual/index.md).

| Design | What it covers |
|---|---|
| [Actor model and control plane](actor-model-and-control-plane.md) | Why Orpheus hand-rolls actors on NATS rather than adopting an actor framework, with the survey of eleven that were rejected |
| [Audio-events agent](audio-events-agent.md) | The PANNs/AudioSet classifier: model choice, the curated class whitelist, and interval post-processing |
| [Cross-classifier identity](cross-classifier-identity.md) | Making three classifiers agree that two labels mean one animal — namespaces, the equivalence table, and the layered identity stack |
| [Distributed and config service](distributed-and-config-service.md) | Sequencing for splitting Orpheus across hosts, and the backplane as the config source |
| [Distributed deployment](distributed-deployment.md) | The ops layer for multi-host installs: per-host component sets, the backbone URL, and what a sensor-only host needs |
| [Entity source identity](entity-source-identity.md) | Grouping observations by source rather than by clock time, so one clip does not collapse into one entity |
| [Event-sourcing determinism contract](event-sourcing-determinism-contract.md) | What a future rebuild from the event log may and may not reconstruct |
| [Observability and event sourcing](observability-and-event-sourcing.md) | Keeping telemetry out of the detection stream, and what a durable shadow stream would cost |
| [Read-only portal](read-only-portal.md) | A public-facing read path: the projection chokepoint, and the replica that keeps browsing off the recording database |
| [Sim test matrix](sim-test-matrix.md) | Testing failure modes against topologies without a field station |
| [Storage retention](storage-retention.md) | One component owning every deletion: ceilings, floors, the free-space reserve, and why floors win |
