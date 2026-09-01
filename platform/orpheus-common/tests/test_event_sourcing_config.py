"""EventSourcingConfig — the domain event-sourcing shadow knobs (default off)."""

from __future__ import annotations

from orpheus_common.config import EventSourcingConfig, OrpheusConfig


def test_defaults_are_off_and_bounded():
    cfg = EventSourcingConfig.from_dict({})
    assert cfg.shadow_publish_enabled is False  # default off -> byte-identical
    assert cfg.stream_name == "orpheus_domain"
    assert cfg.max_age_seconds == 7 * 24 * 60 * 60.0
    assert cfg.max_bytes == 500_000_000  # well under the 2GB account store


def test_overrides_round_trip():
    cfg = EventSourcingConfig.from_dict(
        {
            "shadow_publish_enabled": True,
            "stream_name": "dom",
            "max_age_seconds": 3600,
            "max_bytes": 1000,
        }
    )
    assert cfg.shadow_publish_enabled is True
    assert cfg.stream_name == "dom"
    assert cfg.max_age_seconds == 3600.0
    assert cfg.max_bytes == 1000


def test_wired_into_orpheus_config_and_to_dict():
    c = OrpheusConfig.from_dict(
        {"mqtt": {"broker_host": "localhost"}, "event_sourcing": {"shadow_publish_enabled": True}},
        source="<test>",
    )
    assert c.event_sourcing.shadow_publish_enabled is True
    assert c.to_dict()["event_sourcing"]["shadow_publish_enabled"] is True

    default = OrpheusConfig.from_dict({"mqtt": {"broker_host": "localhost"}}, source="<test>")
    assert default.event_sourcing.shadow_publish_enabled is False
