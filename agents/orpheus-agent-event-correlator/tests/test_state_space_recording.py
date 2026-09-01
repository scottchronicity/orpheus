"""State-space recording on entity-ready ([CORE] State Space Likelihood)."""

from unittest.mock import Mock, patch

from orpheus_common.config import OrpheusConfig
from orpheus_common.state_space import StateSpaceMemory, TimeWindow

from orpheus_agent_event_correlator.main import EventCorrelatorAgent


def _config(enabled: bool, *, corollary: bool = False) -> OrpheusConfig:
    return OrpheusConfig.from_dict(
        {
            "mqtt": {"broker_host": "localhost"},
            "correlation": {"state_space_memory_enabled": enabled},
            # Off by default; the corollary-tagging test opts in explicitly.
            "corollary_discharge": {"enabled": corollary},
        },
        source="<test>",
    )


def _entity(*, entity_type, is_self_generated=False) -> dict:
    return {
        "entity_id": "e1",
        "species_code": "amecro",
        "common_name": "American Crow",
        "confidence": 0.9,
        "evidence": [],
        "entity_type": entity_type,
        "timestamp": "2026-03-01T02:00:00+00:00",
        "is_self_generated": is_self_generated,
    }


def _agent(enabled: bool, tmp_path, *, corollary: bool = False) -> EventCorrelatorAgent:
    with patch("orpheus_agent_event_correlator.main.OrpheusConfig") as mock_cfg:
        mock_cfg.get_instance.return_value = _config(enabled, corollary=corollary)
        agent = EventCorrelatorAgent()
    agent.bus = Mock()
    agent.db = None  # skip persistence; we only exercise the state-space leg
    if enabled:
        agent.state_space = StateSpaceMemory(db_path=tmp_path / "ss.db")
    return agent


class TestStateSpaceRecording:
    def test_disabled_by_default(self, tmp_path) -> None:
        agent = _agent(False, tmp_path)
        assert agent.state_space_memory_enabled is False
        assert agent.state_space is None
        agent._on_entity_ready(_entity(entity_type="Animal.Bird.Crow"))  # no crash

    def test_records_when_enabled(self, tmp_path) -> None:
        agent = _agent(True, tmp_path)
        agent._on_entity_ready(_entity(entity_type="Animal.Bird.Crow"))
        likelihood = agent.state_space.query_likelihood(
            "Animal.Bird.Crow", TimeWindow(hour_of_day=2)
        )
        assert likelihood > 0.0
        assert agent.state_space_recorded == 1

    def test_on_entity_ready_skips_corollary_tagged(self, tmp_path) -> None:
        # End-to-end: corollary discharge (flag ON) tags the entity
        # self-generated, so the full _on_entity_ready path must not record it
        # into temporal memory.
        agent = _agent(True, tmp_path, corollary=True)
        agent.corollary_discharge = Mock()
        agent.corollary_discharge.is_self_generated.return_value = True
        agent._on_entity_ready(_entity(entity_type="Animal.Bird.Crow"))
        assert agent.state_space.query_pattern("Animal.Bird.Crow").total == 0
        assert agent.state_space_recorded == 0

    def test_skips_self_generated(self, tmp_path) -> None:
        # Our own audio playback must not poison the temporal memory. (Driven
        # through _record_state_space directly — _on_entity_ready recomputes
        # the is_self_generated tag from the corollary filter first when
        # corollary_discharge.enabled is on.)
        agent = _agent(True, tmp_path)
        agent._record_state_space(
            _entity(entity_type="Animal.Bird.Crow", is_self_generated=True)
        )
        assert agent.state_space.query_pattern("Animal.Bird.Crow").total == 0

    def test_record_failure_does_not_break_pipeline(self, tmp_path) -> None:
        agent = _agent(True, tmp_path)
        agent.state_space = Mock()
        agent.state_space.record_event.side_effect = RuntimeError("boom")
        # Recording is best-effort enrichment — a failure must not stop publish.
        agent._on_entity_ready(_entity(entity_type="Animal.Bird.Crow"))
        agent.bus.publish.assert_called()
        assert agent.state_space_errors == 1
