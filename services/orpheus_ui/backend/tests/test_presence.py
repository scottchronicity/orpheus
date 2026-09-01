"""Tests for the /api/diagnostics/presence endpoint (Diagnostics presence panel)."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def restore_presence_bus():
    """Keep the module-level bus reference from leaking across tests."""
    from orpheus_ui.api import presence

    original = presence._bus
    yield
    presence._bus = original


class TestPresenceAPI:
    """Tests for the agent-presence consumer.

    Presence is KV-only (JetStream backend): with no bus, on the mqtt backend
    (kv_* raises NotImplementedError), or on a transport error the endpoint
    reports ``supported: false`` — it never 500s the Diagnostics poll.
    """

    def test_presence_no_bus_returns_unsupported(self):
        """No bus wired (MQTT connect failed at startup) → supported:false."""
        from orpheus_ui.api import presence
        from orpheus_ui.auth.models import User

        presence.set_bus(None)

        mock_user = MagicMock(spec=User)
        result = presence.get_presence(user=mock_user)

        assert result == {"supported": False, "agents": {}}

    def test_presence_kv_less_backend_returns_unsupported(self):
        """An mqtt bus (kv_list raises NotImplementedError) → supported:false."""
        from orpheus_ui.api import presence
        from orpheus_ui.auth.models import User

        mock_bus = MagicMock()
        mock_bus.kv_list.side_effect = NotImplementedError("mqtt backend has no KV")
        presence.set_bus(mock_bus)

        mock_user = MagicMock(spec=User)
        result = presence.get_presence(user=mock_user)

        assert result == {"supported": False, "agents": {}}

    def test_presence_happy_path_snapshots_live_agents(self):
        """A KV-capable bus → supported:true with the live agent snapshot."""
        from orpheus_ui.api import presence
        from orpheus_ui.auth.models import User

        mock_bus = MagicMock()
        mock_bus.kv_list.return_value = {
            "orpheus-agent-audio-motion": {"status": "online"},
            "orpheus-agent-event-correlator": {"status": "online"},
        }
        presence.set_bus(mock_bus)

        mock_user = MagicMock(spec=User)
        result = presence.get_presence(user=mock_user)

        assert result["supported"] is True
        assert result["agents"] == {
            "orpheus-agent-audio-motion": {"status": "online"},
            "orpheus-agent-event-correlator": {"status": "online"},
        }
        # Reads the shared orpheus_presence bucket the producers refresh.
        mock_bus.kv_list.assert_called_with("orpheus_presence")

    def test_presence_empty_bucket_is_supported_with_no_agents(self):
        """KV works but nothing is online (all keys aged out) → empty snapshot."""
        from orpheus_ui.api import presence
        from orpheus_ui.auth.models import User

        mock_bus = MagicMock()
        mock_bus.kv_list.return_value = {}
        presence.set_bus(mock_bus)

        mock_user = MagicMock(spec=User)
        result = presence.get_presence(user=mock_user)

        assert result == {"supported": True, "agents": {}}

    def test_presence_single_kv_round_trip_per_poll(self):
        """One kv_list per poll: the endpoint snapshots directly instead of
        probing supported() (itself a kv_list) first — Diagnostics polls this
        every HEALTH tick, so the probe doubled broker traffic."""
        from orpheus_ui.api import presence
        from orpheus_ui.auth.models import User

        mock_bus = MagicMock()
        mock_bus.kv_list.return_value = {"a": {"status": "online"}}
        presence.set_bus(mock_bus)

        result = presence.get_presence(user=MagicMock(spec=User))

        assert result["supported"] is True
        assert mock_bus.kv_list.call_count == 1

    def test_presence_transport_error_returns_unsupported(self):
        """A broker/transport error (KV surface exists but fails) → supported:false,
        not a 500. supported() treats a transport error as "surface exists", so the
        failure surfaces from snapshot() and must be swallowed."""
        from orpheus_ui.api import presence
        from orpheus_ui.auth.models import User

        mock_bus = MagicMock()
        mock_bus.kv_list.side_effect = RuntimeError("broker connection lost")
        presence.set_bus(mock_bus)

        mock_user = MagicMock(spec=User)
        result = presence.get_presence(user=mock_user)

        assert result == {"supported": False, "agents": {}}
