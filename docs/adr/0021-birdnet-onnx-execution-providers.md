# ADR 0021: BirdNET ONNX execution providers

**Status:** Accepted

**Date:** 2026-11-14

**Decider:** Scott

## Context

BirdNET runs an ONNX acoustic model inside its own agent runtime. Implicit
ONNX Runtime session construction left it on CPU even when a supported
accelerator provider was installed. Making the runtime package or CUDA stack a
global Orpheus dependency would couple unrelated agents and deployments.

## Decision

BirdNET configuration owns an `execution_provider` choice: `auto` (default),
`cpu`, `cuda`, or `coreml`. `auto` selects only among providers reported by the
installed ONNX Runtime, preferring CUDA, CoreML, then CPU. An explicit provider
that is not available fails model startup clearly. Accelerated sessions retain
CPU fallback for model operations the selected execution provider cannot run.

The standard agent dependency remains CPU `onnxruntime`. CUDA deployments
replace it with a compatible `onnxruntime-gpu` package in the BirdNET agent's
isolated environment; the CPU and GPU packages must not be installed together.
No host-wide accelerator dependency or pinned CUDA version is introduced.
Health reports the selected provider. The setting changes only ONNX execution;
BirdNET windowing, thresholds, geographic filtering, species events, lineage,
and persistence remain owned by the existing agent/model implementation.

CoreML and CUDA selection are provider availability checks, not hardware
validation or performance guarantees. Deployment-specific package versions and
accelerator behavior require validation on their target runtime. Other model
agents may choose their own suitable providers and runtimes.

## Consequences

- CPU-only installs continue to import and run without NVIDIA packages.
- A host can opt into an installed ONNX accelerator without changing the
  detection stream or coupling BirdNET to a host type.
- Provider registration does not prove that every model operator runs on the
  accelerator; ONNX Runtime may place unsupported operations on CPU.
- Installing and validating compatible accelerator packages remains a
  per-agent deployment responsibility.
