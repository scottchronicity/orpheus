"""OpenTelemetry tracing foundation ([REFACTOR] OTel Migration #95 — foundation).

Mirrors ``get_logger``: ``get_tracer(name)`` returns a tracer, and
``setup_tracing(service_name, config)`` wires a real console/OTLP exporter when
telemetry is enabled AND the optional ``[telemetry]`` extra (opentelemetry-sdk)
is installed.

Off by default with ZERO new hard dependency: when opentelemetry isn't installed
(the default), both degrade to a local no-op, so every component keeps working
unchanged and the import footprint is untouched. Turn it on with
``pip install orpheus-common[telemetry]`` + ``telemetry.enabled: true``.

DEFERRED (non-additive / external — tracked in the backlog): W3C trace-context
propagation across MQTT, the Jaeger/Tempo Jetson deploy, and the actual MIGRATION
of health/metrics OFF the MQTT bus. That last one REMOVES data existing UI
consumers read, so it is deliberately not part of this additive foundation.
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator, Optional

from orpheus_common.logging import get_logger

logger = get_logger(__name__)

# console prints spans; otlp/jaeger/tempo all export OTLP/HTTP to `endpoint`
# (modern Jaeger + Tempo ingest OTLP natively — they're not distinct exporters).
_KNOWN_BACKENDS = frozenset({"console", "otlp", "jaeger", "tempo"})


class _NoOpSpan:
    """Span stand-in used when OpenTelemetry isn't installed/enabled."""

    def set_attribute(self, *_a: Any, **_k: Any) -> None: ...
    def add_event(self, *_a: Any, **_k: Any) -> None: ...
    def record_exception(self, *_a: Any, **_k: Any) -> None: ...
    def set_status(self, *_a: Any, **_k: Any) -> None: ...
    def end(self, *_a: Any, **_k: Any) -> None: ...


class _NoOpTracer:
    """Tracer stand-in: spans are context managers that do nothing, so callers
    can ``with get_tracer(__name__).start_as_current_span(...)`` unconditionally."""

    @contextlib.contextmanager
    def start_as_current_span(self, name: str, **_k: Any) -> Iterator[_NoOpSpan]:
        yield _NoOpSpan()

    def start_span(self, name: str, **_k: Any) -> _NoOpSpan:
        return _NoOpSpan()


def get_tracer(name: str) -> Any:
    """Tracer for ``name``, mirroring ``get_logger(name)``. Returns OpenTelemetry's
    tracer when installed (a no-op until ``setup_tracing`` runs), otherwise a
    local no-op tracer so instrumentation is always safe to write."""
    try:
        from opentelemetry import trace
    except ImportError:
        return _NoOpTracer()
    return trace.get_tracer(name)


def setup_tracing(service_name: str, config: Any) -> Optional[Any]:
    """Install a real ``TracerProvider`` when ``telemetry.enabled`` and the SDK is
    present; otherwise leave the no-op in place and return ``None``. Sets the
    global provider (OTel logs if called twice)."""
    tcfg = getattr(config, "telemetry", None)
    if tcfg is None or not getattr(tcfg, "enabled", False):
        return None
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except ImportError:
        logger.warning(
            "telemetry.enabled is true but opentelemetry-sdk is not installed; "
            "tracing stays a no-op. Install orpheus-common[telemetry] to enable.",
            service=service_name,
        )
        return None

    # Idempotent: if a real SDK provider is already installed (double call / config
    # reload), reuse it rather than orphaning a second BatchSpanProcessor thread.
    existing = trace.get_tracer_provider()
    if isinstance(existing, TracerProvider):
        logger.debug("Tracing already initialised; reusing provider", service=service_name)
        return existing

    exporter = _build_exporter(tcfg)
    if exporter is None:
        return None
    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name}),
        sampler=TraceIdRatioBased(float(getattr(tcfg, "sample_rate", 0.1))),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info(
        "OpenTelemetry tracing enabled",
        service=service_name,
        backend=getattr(tcfg, "backend", "console"),
    )
    return provider


def _build_exporter(tcfg: Any) -> Optional[Any]:
    """Pick a span exporter from the backend. ``console`` needs no endpoint;
    jaeger/tempo/otlp all ingest OTLP/HTTP at an operator-provided endpoint."""
    backend = (getattr(tcfg, "backend", "console") or "console").lower()
    if backend not in _KNOWN_BACKENDS:
        logger.warning(
            "unknown telemetry.backend; tracing stays a no-op", backend=backend
        )
        return None
    if backend == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    endpoint = getattr(tcfg, "endpoint", "") or ""
    if not endpoint:
        logger.warning(
            "telemetry backend needs telemetry.endpoint (OTLP/HTTP URL); "
            "tracing stays a no-op.",
            backend=backend,
        )
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except ImportError:
        logger.warning(
            "OTLP exporter not installed; install orpheus-common[telemetry]. "
            "Tracing stays a no-op.",
            backend=backend,
        )
        return None
    return OTLPSpanExporter(endpoint=endpoint)
