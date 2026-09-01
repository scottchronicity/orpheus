"""Tests for the OpenTelemetry tracing foundation ([REFACTOR] OTel Migration)."""

import sys

import pytest

from orpheus_common.config import OrpheusConfig, TelemetryConfig
from orpheus_common.telemetry import _NoOpTracer, get_tracer, setup_tracing


class TestGetTracer:
    def test_tracer_is_always_usable(self) -> None:
        # Whether or not opentelemetry is installed, a tracer's span is a usable
        # context manager — instrumentation is safe to write unconditionally.
        tracer = get_tracer(__name__)
        with tracer.start_as_current_span("unit-test-span") as span:
            span.set_attribute("k", "v")  # no-op or real; must not raise

    def test_noop_when_opentelemetry_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Force the ImportError branch deterministically (regardless of whether
        # the [telemetry] extra is installed) so the no-op default path is guarded.
        monkeypatch.setitem(sys.modules, "opentelemetry", None)
        tracer = get_tracer("x")
        assert isinstance(tracer, _NoOpTracer)
        with tracer.start_as_current_span("s") as span:
            span.set_attribute("k", "v")

    def test_noop_span_methods_are_safe(self) -> None:
        tracer = _NoOpTracer()
        span = tracer.start_span("x")
        span.set_attribute("a", 1)
        span.add_event("e")
        span.record_exception(ValueError("x"))
        span.set_status("ok")
        span.end()


class TestSetupTracing:
    def test_disabled_returns_none(self) -> None:
        cfg = OrpheusConfig.from_dict({"mqtt": {"broker_host": "localhost"}}, source="<test>")
        assert cfg.telemetry.enabled is False
        assert setup_tracing("svc", cfg) is None

    def test_enabled_without_sdk_degrades_to_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # SDK isn't a hard dep; enabling without it must degrade to a no-op (None),
        # not crash. Force the import failure so this is deterministic regardless
        # of whether the [telemetry] extra is installed in the test env.
        monkeypatch.setitem(sys.modules, "opentelemetry", None)
        cfg = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}, "telemetry": {"enabled": True}},
            source="<test>",
        )
        assert setup_tracing("svc", cfg) is None

    def test_enabled_console_when_sdk_present(self) -> None:
        pytest.importorskip("opentelemetry.sdk")
        from opentelemetry import trace

        # Defend against a global provider leaked by another test in the session
        # (set_tracer_provider is process-global + set-once).
        trace._TRACER_PROVIDER = None
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "telemetry": {"enabled": True, "backend": "console", "sample_rate": 1.0},
            },
            source="<test>",
        )
        provider = setup_tracing("svc-console", cfg)
        assert provider is not None


class TestBuildExporter:
    """The backend→exporter branch is a pure function of config — no globals.
    Unknown/missing-endpoint cases short-circuit BEFORE any OTel import, so they
    are deterministic even without the [telemetry] extra installed."""

    def test_unknown_backend_is_none(self) -> None:
        from orpheus_common.telemetry import _build_exporter

        assert _build_exporter(TelemetryConfig(backend="kafka")) is None

    def test_otlp_without_endpoint_is_none(self) -> None:
        from orpheus_common.telemetry import _build_exporter

        assert _build_exporter(TelemetryConfig(backend="otlp", endpoint="")) is None

    def test_console_returns_exporter_when_sdk_present(self) -> None:
        pytest.importorskip("opentelemetry.sdk")
        from orpheus_common.telemetry import _build_exporter

        assert _build_exporter(TelemetryConfig(backend="console")) is not None


class TestTelemetryConfig:
    def test_defaults_disabled(self) -> None:
        c = TelemetryConfig.from_dict({})
        assert c.enabled is False
        assert c.backend == "console"
        assert c.sample_rate == 0.1
        assert c.endpoint == ""

    def test_from_dict_values(self) -> None:
        c = TelemetryConfig.from_dict(
            {"enabled": True, "backend": "tempo", "sample_rate": 0.25, "endpoint": "http://x"}
        )
        assert c.enabled is True and c.backend == "tempo"
        assert c.sample_rate == 0.25 and c.endpoint == "http://x"

    def test_sample_rate_clamped_to_unit_interval(self) -> None:
        assert TelemetryConfig.from_dict({"sample_rate": 5.0}).sample_rate == 1.0
        assert TelemetryConfig.from_dict({"sample_rate": -1.0}).sample_rate == 0.0

    def test_config_roundtrips_through_to_dict(self) -> None:
        # The recipe's round-trip spot: from_dict(to_dict()) preserves all fields.
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "telemetry": {
                    "enabled": True,
                    "backend": "tempo",
                    "sample_rate": 0.25,
                    "endpoint": "http://x",
                },
            },
            source="<test>",
        )
        rt = OrpheusConfig.from_dict(cfg.to_dict(), source="<test>").telemetry
        assert (rt.enabled, rt.backend, rt.sample_rate, rt.endpoint) == (
            True,
            "tempo",
            0.25,
            "http://x",
        )

    def test_absent_section_yields_disabled(self) -> None:
        cfg = OrpheusConfig.from_dict({"mqtt": {"broker_host": "localhost"}}, source="<test>")
        assert cfg.telemetry.enabled is False

    def test_to_dict_includes_telemetry(self) -> None:
        cfg = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}, "telemetry": {"enabled": True}},
            source="<test>",
        )
        assert cfg.to_dict()["telemetry"]["enabled"] is True
