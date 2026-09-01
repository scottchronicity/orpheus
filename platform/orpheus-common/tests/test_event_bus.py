"""Tests for the EventBus abstraction (Epic 4).

Covers the ABC contract, the MQTT implementation wiring, the factory's
backend selection (incl. the defensive default that keeps old configs
working), and the additive EventBusConfig.
"""

from types import SimpleNamespace

import pytest

from orpheus_common import EventBus, create_event_bus
from orpheus_common.config import ConfigError, EventBusConfig
from orpheus_common.mqtt import MQTTBus, MQTTClient


def _fake_config(backend=None):
    """Minimal stand-in for OrpheusConfig: just the bits the factory reads."""
    cfg = SimpleNamespace(
        mqtt=SimpleNamespace(broker_host="localhost", broker_port=1883, keepalive=60)
    )
    if backend is not None:
        cfg.event_bus = SimpleNamespace(backend=backend)
    return cfg


class TestEventBusABC:
    def test_cannot_instantiate_abstract_base(self):
        with pytest.raises(TypeError):
            EventBus()  # type: ignore[abstract]

    def test_mqtt_client_is_an_event_bus(self):
        assert issubclass(MQTTClient, EventBus)
        assert MQTTBus is MQTTClient  # alias, same class
        bus = MQTTClient(broker_host="localhost", client_id="t")
        assert isinstance(bus, EventBus)
        # The full contract is present.
        for name in ("publish", "subscribe", "unsubscribe", "connect", "disconnect"):
            assert callable(getattr(bus, name))
        # is_connected is a PROPERTY (accessed without parens), not a method.
        assert bus.is_connected is False


class TestUnsubscribe:
    def test_unsubscribe_removes_callbacks_and_is_idempotent(self):
        bus = MQTTClient(broker_host="localhost", client_id="t")
        bus.subscribe("orpheus/test/#", lambda topic, payload: None)
        assert "orpheus/test/#" in bus._callbacks
        bus.unsubscribe("orpheus/test/#")
        assert "orpheus/test/#" not in bus._callbacks
        # Idempotent: unsubscribing a pattern with no callbacks is a no-op.
        bus.unsubscribe("orpheus/test/#")
        bus.unsubscribe("never/subscribed")


class TestCreateEventBus:
    def test_defaults_to_nats_when_no_event_bus_section(self):
        # The default backend is now nats (the backplane). A config with no
        # event_bus section builds a NatsBus (constructed, not connected).
        from orpheus_common.event_bus_nats import NatsBus

        bus = create_event_bus(_fake_config(), client_id="t")
        assert isinstance(bus, EventBus)
        assert isinstance(bus, NatsBus)

    def test_explicit_mqtt_backend(self):
        bus = create_event_bus(_fake_config(backend="mqtt"), client_id="t")
        assert isinstance(bus, MQTTClient)

    def test_passes_broker_settings_through(self):
        # MQTT-specific wiring → select mqtt explicitly.
        bus = create_event_bus(_fake_config(backend="mqtt"), client_id="corr")
        assert bus.broker_host == "localhost"
        assert bus.broker_port == 1883
        assert bus.client_id == "corr"

    def test_qos_passthrough(self):
        # MQTT-specific (NATS has no qos). Default qos is the client's (1); a
        # caller-supplied qos (e.g. video/audio-motion preserving config.mqtt.qos)
        # is honoured.
        cfg = _fake_config(backend="mqtt")
        assert create_event_bus(cfg, client_id="t").qos == 1
        assert create_event_bus(cfg, client_id="t", qos=2).qos == 2

    def test_honours_configured_keepalive(self):
        # MQTT-specific: the factory threads config.mqtt.keepalive through. See ADR 0015.
        cfg = SimpleNamespace(
            mqtt=SimpleNamespace(broker_host="localhost", broker_port=1883, keepalive=45),
            event_bus=SimpleNamespace(backend="mqtt"),
        )
        bus = create_event_bus(cfg, client_id="t")
        assert bus.keepalive == 45

    def test_unknown_backend_raises_valueerror(self):
        with pytest.raises(ValueError, match="Unknown event_bus.backend"):
            create_event_bus(_fake_config(backend="redis"), client_id="t")


class TestNatsConnectRequired:
    """A cold broker is NON-fatal by default (come up disconnected + retry in the
    background) regardless of loopback vs remote — so an agent restarted before
    its broker is up self-heals instead of crash-looping. Only an explicit
    ``connect_required: true`` makes a missing broker fatal."""

    def _nats_bus(self, nats_url, connect_required=None):
        eb = SimpleNamespace(backend="nats", nats_url=nats_url)
        if connect_required is not None:
            eb.connect_required = connect_required
        cfg = SimpleNamespace(
            event_bus=eb,
            mqtt=SimpleNamespace(broker_host="localhost", broker_port=1883, keepalive=60),
        )
        return create_event_bus(cfg, client_id="t")

    def test_loopback_does_not_require_broker_by_default(self):
        # The single-host case: a cold broker must NOT be fatal (no crash-loop).
        assert self._nats_bus("nats://127.0.0.1:4222")._connect_required is False
        assert self._nats_bus("nats://localhost:4222")._connect_required is False

    def test_default_no_url_does_not_require_broker(self):
        # No event_bus section at all -> graceful degrade default.
        from orpheus_common.event_bus_nats import NatsBus

        bus = create_event_bus(_fake_config(), client_id="t")
        assert isinstance(bus, NatsBus)
        assert bus._connect_required is False

    def test_remote_does_not_require_broker(self):
        assert self._nats_bus("nats://nuc.local:4222")._connect_required is False
        assert self._nats_bus("nats://user@nuc.local:4222")._connect_required is False

    def test_explicit_true_makes_it_fatal(self):
        # Opt in to hard-fail (systemd surfaces a missing broker loudly).
        loop = self._nats_bus("nats://127.0.0.1:4222", connect_required=True)
        remote = self._nats_bus("nats://nuc:4222", connect_required=True)
        assert loop._connect_required is True
        assert remote._connect_required is True

    def test_explicit_false_is_same_as_unset(self):
        assert (
            self._nats_bus("nats://127.0.0.1:4222", connect_required=False)._connect_required
            is False
        )

    def test_config_from_dict_parses_connect_required(self):
        assert EventBusConfig.from_dict({}).connect_required is None
        assert EventBusConfig.from_dict({"backend": "nats"}).connect_required is None
        assert EventBusConfig.from_dict({"connect_required": False}).connect_required is False
        assert EventBusConfig.from_dict({"connect_required": True}).connect_required is True

    def test_config_from_dict_parses_presence_enabled(self):
        assert EventBusConfig.from_dict({}).presence_enabled is False  # default off
        assert EventBusConfig.from_dict({"presence_enabled": True}).presence_enabled is True
        assert EventBusConfig.from_dict({"presence_enabled": False}).presence_enabled is False

    def test_config_from_dict_parses_health_migration_flags(self):
        # Defaults preserve today's behavior: no KV dual-write, health still on the bus.
        d = EventBusConfig.from_dict({})
        assert d.health_kv_enabled is False
        assert d.health_on_bus is True
        cfg = EventBusConfig.from_dict({"health_kv_enabled": True, "health_on_bus": False})
        assert cfg.health_kv_enabled is True
        assert cfg.health_on_bus is False


class TestEventBusConfig:
    def test_defaults_to_nats(self):
        assert EventBusConfig.from_dict({}).backend == "nats"

    def test_reads_backend(self):
        assert EventBusConfig.from_dict({"backend": "mqtt"}).backend == "mqtt"

    def test_rejects_non_string_backend(self):
        with pytest.raises(ConfigError):
            EventBusConfig.from_dict({"backend": 123})
