"""Tests for EventCorrelationConfig + AutoDiscoveryConfig.

Layer 3 added a bunch of new tunable knobs for the auto-discovery
worker. These tests verify the defaults match what's documented and
that orpheus.yaml-driven overrides work."""

from __future__ import annotations

import pytest

from orpheus_common.config import AutoDiscoveryConfig, EventCorrelationConfig


class TestAutoDiscoveryConfigDefaults:
    def test_defaults_match_documented_values(self) -> None:
        c = AutoDiscoveryConfig.from_dict({})
        assert c.enabled is True
        assert c.interval_seconds == 6 * 60 * 60  # 6h
        assert c.lookback_days == 7
        assert c.accept_threshold == 0.9
        assert c.propose_threshold == 0.6
        assert c.min_cooccurrences == 5
        # Off by default — preserves the historical auto-accept behaviour.
        assert c.cross_namespace_accept_only is False

    def test_full_override(self) -> None:
        c = AutoDiscoveryConfig.from_dict(
            {
                "enabled": False,
                "interval_seconds": 3600,
                "lookback_days": 30,
                "accept_threshold": 0.95,
                "propose_threshold": 0.5,
                "min_cooccurrences": 10,
                "cross_namespace_accept_only": True,
            }
        )
        assert c.enabled is False
        assert c.interval_seconds == 3600
        assert c.lookback_days == 30
        assert c.accept_threshold == 0.95
        assert c.propose_threshold == 0.5
        assert c.min_cooccurrences == 10
        assert c.cross_namespace_accept_only is True

    def test_partial_override_uses_defaults_for_rest(self) -> None:
        c = AutoDiscoveryConfig.from_dict({"enabled": False, "lookback_days": 14})
        assert c.enabled is False
        assert c.lookback_days == 14
        assert c.interval_seconds == 6 * 60 * 60  # default
        assert c.accept_threshold == 0.9  # default


class TestEventCorrelationConfigDefaults:
    def test_default_window_seconds(self) -> None:
        c = EventCorrelationConfig.from_dict({})
        assert c.window_seconds == 3.0

    def test_default_includes_audio_events_topic(self) -> None:
        """Layer 2 added audio.classified to the standard input topics."""
        c = EventCorrelationConfig.from_dict({})
        assert "orpheus/detection/audio/events" in c.input_topics
        assert "orpheus/detection/bird/events" in c.input_topics
        assert "orpheus/detection/crow/events" in c.input_topics

    def test_explicit_input_topics_override_defaults(self) -> None:
        c = EventCorrelationConfig.from_dict(
            {"input_topics": ["custom/topic/a", "custom/topic/b"]}
        )
        assert c.input_topics == ["custom/topic/a", "custom/topic/b"]

    def test_window_seconds_override(self) -> None:
        c = EventCorrelationConfig.from_dict({"window_seconds": 5.0})
        assert c.window_seconds == 5.0

    def test_default_max_cluster_duration_seconds(self) -> None:
        c = EventCorrelationConfig.from_dict({})
        assert c.max_cluster_duration_seconds == 30.0

    def test_max_cluster_duration_seconds_override(self) -> None:
        c = EventCorrelationConfig.from_dict({"max_cluster_duration_seconds": 60.0})
        assert c.max_cluster_duration_seconds == 60.0

    def test_publish_entity_type_topics_defaults_false(self) -> None:
        assert EventCorrelationConfig.from_dict({}).publish_entity_type_topics is False

    def test_publish_entity_type_topics_override(self) -> None:
        c = EventCorrelationConfig.from_dict({"publish_entity_type_topics": True})
        assert c.publish_entity_type_topics is True

    def test_state_space_memory_defaults_false(self) -> None:
        assert EventCorrelationConfig.from_dict({}).state_space_memory_enabled is False

    def test_state_space_memory_override(self) -> None:
        c = EventCorrelationConfig.from_dict({"state_space_memory_enabled": True})
        assert c.state_space_memory_enabled is True

    def test_auto_discovery_subsection_parsed(self) -> None:
        c = EventCorrelationConfig.from_dict(
            {
                "auto_discovery": {
                    "enabled": False,
                    "accept_threshold": 0.85,
                }
            }
        )
        assert c.auto_discovery.enabled is False
        assert c.auto_discovery.accept_threshold == 0.85

    def test_invalid_input_topics_raises(self) -> None:
        from orpheus_common.config import ConfigError

        with pytest.raises(ConfigError, match="input_topics"):
            EventCorrelationConfig.from_dict({"input_topics": "not a list"})


class TestEmptySectionGuards:
    """An empty yaml section (`correlation:` / `auto_discovery:`) parses as None
    — from_dict must yield defaults, not AttributeError."""

    def test_empty_correlation_section_yields_defaults(self) -> None:
        c = EventCorrelationConfig.from_dict(None)  # type: ignore[arg-type]
        assert c.window_seconds == 3.0
        assert len(c.input_topics) == 3

    def test_empty_auto_discovery_section_yields_defaults(self) -> None:
        assert AutoDiscoveryConfig.from_dict(None).enabled is True  # type: ignore[arg-type]
        c = EventCorrelationConfig.from_dict({"auto_discovery": None})
        assert c.auto_discovery.enabled is True

    def test_empty_correlation_key_loads_through_orpheus_config(self) -> None:
        from orpheus_common.config import OrpheusConfig

        cfg = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}, "correlation": None},
            source="<test>",
        )
        assert cfg.correlation.window_seconds == 3.0


class TestCorollaryDischargeConfig:
    def test_default_buffer_seconds(self) -> None:
        from orpheus_common.config import CorollaryDischargeConfig

        assert CorollaryDischargeConfig.from_dict({}).buffer_seconds == 2.0

    def test_override(self) -> None:
        from orpheus_common.config import CorollaryDischargeConfig

        assert CorollaryDischargeConfig.from_dict({"buffer_seconds": 5.0}).buffer_seconds == 5.0

    def test_orpheus_config_section_round_trips(self) -> None:
        from orpheus_common.config import OrpheusConfig

        cfg = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "x"}, "corollary_discharge": {"buffer_seconds": 3.5}},
            source="<test>",
        )
        assert cfg.corollary_discharge.buffer_seconds == 3.5
        # `enabled` (off by default) joined the section in 461d35d.
        assert cfg.to_dict()["corollary_discharge"] == {
            "buffer_seconds": 3.5,
            "enabled": False,
        }
