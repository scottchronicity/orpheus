# ADR 0023: Portable crow Torch device selection

**Status:** Accepted

**Date:** 2026-11-14

**Decider:** Scott

**Clarifies:** [ADR 0020](0020-portable-capabilities-and-runtime-boundaries.md)

## Context

Crow detection runs two Torch model stages, the AVES embedder and the
multi-task classifier, in the crow agent's independently managed runtime. The
existing shared Torch selector supports CUDA and CPU. Crow also has a useful
accelerator on supported Apple hosts: Torch MPS. Selecting the device
independently in both model constructors risks inconsistent execution and
health reporting.

The video-motion, snapshotter, and timelapser agents currently perform capture,
OpenCV motion processing, and media operations. No shipped video DNN loads a
model. `detection.video_model` is presently a parsed placeholder without a
consumer, so choosing an accelerator for it would claim behavior that does not
exist.

## Decision

Crow resolves its configured `device` once during setup and passes that
resolved device to both model stages. Supported values are `auto`, `cpu`,
`cuda`, and `mps`. Crow's `auto` policy prefers CUDA, then MPS, then CPU;
explicit unavailable accelerators fail clearly. Health reports the requested
and resolved values separately. The shared selector only considers MPS for
callers that opt in, so existing audio-events behavior is unchanged.

This choice affects execution placement only. Model outputs, detection
thresholds, event lineage, and published payload semantics remain unchanged.
Crow keeps its own Python and dependency environment; this does not alter the
PANNs CUDA runtime.

Do not add an accelerator selector to video configuration until a video model
implementation defines model artifacts, supported runtime/provider choices,
outputs, source lineage, and resource ownership. The video model configuration
placeholder is documented as inert. This ADR does not introduce a shared
inference process or host-wide accelerator scheduler.

## Consequences

- Crow can use CUDA, Apple MPS, or CPU through deployment configuration.
- CPU-only systems do not acquire a hard accelerator dependency.
- The resolved device is consistent across AVES and classifier inference and
  visible in agent health.
- Video acceleration remains future work because no current video model
  workload exists to accelerate or validate.
- Availability selection does not guarantee model support or performance on a
  particular device; platform integration validation remains necessary.
