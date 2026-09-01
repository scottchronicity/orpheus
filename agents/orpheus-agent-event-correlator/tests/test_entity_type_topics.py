"""Entity_type-routed topic publishing ([ARCH], off by default)."""

from unittest.mock import Mock, patch

from orpheus_common.config import OrpheusConfig

from orpheus_agent_event_correlator.main import EventCorrelatorAgent


def _config(publish_flag: bool) -> OrpheusConfig:
    return OrpheusConfig.from_dict(
        {
            "mqtt": {"broker_host": "localhost"},
            "correlation": {"publish_entity_type_topics": publish_flag},
        },
        source="<test>",
    )


def _entity(entity_type) -> dict:
    return {
        "entity_id": "e1",
        "species_code": "amecro",
        "common_name": "American Crow",
        "confidence": 0.9,
        "evidence": [],
        "entity_type": entity_type,
    }


def _topics(agent: EventCorrelatorAgent) -> list:
    return [c[0][0] for c in agent.bus.publish.call_args_list]


class TestEntityTypeTopics:
    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_legacy_topic_only_when_flag_off(self, mock_cfg: Mock) -> None:
        mock_cfg.get_instance.return_value = _config(False)
        agent = EventCorrelatorAgent()
        agent.bus = Mock()
        agent._publish_entity(_entity("Animal.Bird.Crow"))
        assert _topics(agent) == ["orpheus/entities/animal"]

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_dual_publish_when_flag_on(self, mock_cfg: Mock) -> None:
        mock_cfg.get_instance.return_value = _config(True)
        agent = EventCorrelatorAgent()
        agent.bus = Mock()
        agent._publish_entity(_entity("Animal.Bird.Crow"))
        topics = _topics(agent)
        assert "orpheus/entities/animal" in topics  # legacy always fires
        assert "orpheus/entities/animal/bird/crow" in topics  # additive route

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_no_route_without_entity_type(self, mock_cfg: Mock) -> None:
        # Flag on, but the entity has no resolved entity_type → legacy only.
        mock_cfg.get_instance.return_value = _config(True)
        agent = EventCorrelatorAgent()
        agent.bus = Mock()
        agent._publish_entity(_entity(None))
        assert _topics(agent) == ["orpheus/entities/animal"]
