"""Safety contracts for the opt-in live-broker test harness."""

import pytest

from orpheus_common.testing import bus_harness


def test_broker_probe_does_not_touch_network_without_explicit_test_url(monkeypatch):
    def unexpected_import(*args, **kwargs):
        raise AssertionError("broker probe must not create a live connection")

    monkeypatch.setattr(bus_harness, "DEFAULT_NATS_URL", None)
    monkeypatch.setattr(bus_harness, "create_event_bus", unexpected_import)
    assert bus_harness.broker_reachable(None) is False


def test_nats_config_requires_explicit_isolated_url():
    with pytest.raises(ValueError, match="ORPHEUS_TEST_NATS_URL"):
        bus_harness.nats_config(None)


def test_require_broker_skips_without_explicit_url(monkeypatch):
    monkeypatch.setattr(bus_harness, "DEFAULT_NATS_URL", None)
    with pytest.raises(pytest.skip.Exception, match="ORPHEUS_TEST_NATS_URL"):
        bus_harness.require_broker(None)
