# ADR 0022: BirdNET ONNX provider fail-closed runtime

**Status:** Accepted

**Date:** 2026-11-14

**Decider:** Scott

**Clarifies:** [ADR 0021](0021-birdnet-onnx-execution-providers.md)

## Context

Selecting an ONNX Runtime provider is not proof that ONNX Runtime registered it
for the constructed session. Runtime provider failures can also cause ONNX
Runtime to retry an inference with a different provider set. A deployment that
explicitly asks for acceleration needs to distinguish per-operator CPU
assignment from whole-session fallback.

## Decision

BirdNET's install mechanism selects exactly one ONNX Runtime distribution in
its own environment. `make install` remains the simple CPU default;
`make install-cuda` removes either existing runtime distribution and installs
the CUDA extra. The Python package exposes mutually exclusive `onnx-cpu` and
`onnx-cuda` extras, while requirements files select one for the agent Make
workflow.

After session construction, BirdNET records ONNX Runtime's registered provider
list and uses its first BirdNET-supported registered provider as the actual
primary provider. An explicit CUDA or CoreML request fails startup if that
provider is absent from the constructed session. It disables ONNX Runtime's
whole-session `Run()` retry fallback for explicit accelerator requests. CPU
remains in the provider priority list so individual operators unsupported by
the accelerator can still execute on CPU. Agent health exposes requested,
registered, and primary provider values separately.

Automatic selection can accept ONNX Runtime's session-construction fallback,
but health reports the providers actually registered rather than the requested
candidate. Provider registration is not proof that every operator executed on
that provider; profiling is required to determine node assignment.

## Consequences

- CPU remains a no-extra-steps default, and NVIDIA packages remain outside the
  CPU runtime environment.
- Reinstalling this agent through its Make targets switches the ORT package
  instead of leaving both distributions installed.
- Explicit accelerator deployments fail clearly when session initialization or
  registration falls back to CPU.
- CPU operator fallback remains available; a runtime execution failure does
  not silently rerun the full inference on a CPU-only session.
- The selected CUDA package must still match deployment OS, architecture,
  CUDA, and cuDNN libraries.
