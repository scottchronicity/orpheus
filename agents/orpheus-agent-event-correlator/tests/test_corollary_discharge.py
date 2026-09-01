"""Tests for corollary discharge (the "echo problem"): the filter + the agent
wiring that tags self-generated detections overlapping our own playback."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from orpheus_common.config import OrpheusConfig
from orpheus_common.detection import DetectionDB

from orpheus_agent_event_correlator.corollary_discharge import (
    PLAYBACK_TOPIC,
    CorollaryDischargeFilter,
)
from orpheus_agent_event_correlator.main import EventCorrelatorAgent

T0 = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)


def _real_config(*, corollary_enabled: bool = True) -> OrpheusConfig:
    """A real config with corollary discharge ON (the wiring under test).
    ``corollary_discharge.enabled`` defaults OFF per the Reversibility
    Contract — flag-off behavior is pinned separately below."""
    return OrpheusConfig.from_dict(
        {
            "mqtt": {"broker_host": "localhost"},
            "corollary_discharge": {"enabled": corollary_enabled},
        },
        source="<test>",
    )


def _entity(start: datetime, end: datetime) -> dict:
    return {
        "event_signature": {
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        }
    }


class TestCorollaryDischargeFilter:
    def test_no_windows_not_self_generated(self) -> None:
        f = CorollaryDischargeFilter()
        assert f.is_self_generated(_entity(T0, T0 + timedelta(seconds=1)), now=T0) is False

    def test_overlapping_window_is_tagged(self) -> None:
        f = CorollaryDischargeFilter(buffer_seconds=2.0)
        f.register_playback(T0, 5.0, "speaker", now=T0)  # window [T0, T0+7]
        e = _entity(T0 + timedelta(seconds=2), T0 + timedelta(seconds=3))
        assert f.is_self_generated(e, now=T0 + timedelta(seconds=3)) is True

    def test_nonoverlapping_window_not_tagged(self) -> None:
        f = CorollaryDischargeFilter(buffer_seconds=2.0)
        f.register_playback(T0, 5.0, "speaker", now=T0)  # [T0, T0+7]
        e = _entity(T0 + timedelta(seconds=20), T0 + timedelta(seconds=21))
        assert f.is_self_generated(e, now=T0 + timedelta(seconds=21)) is False

    def test_buffer_extends_window_tail(self) -> None:
        f = CorollaryDischargeFilter(buffer_seconds=3.0)
        f.register_playback(T0, 5.0, now=T0)  # [T0, T0+8] (5s + 3s buffer)
        e = _entity(T0 + timedelta(seconds=7.5), T0 + timedelta(seconds=7.6))
        assert f.is_self_generated(e, now=T0 + timedelta(seconds=8)) is True

    def test_register_from_event_parses_payload(self) -> None:
        f = CorollaryDischargeFilter(buffer_seconds=0.0)
        ok = f.register_from_event(
            {"start_time": T0.isoformat(), "duration_seconds": 4.0, "source": "x"}, now=T0
        )
        assert ok is True
        e = _entity(T0 + timedelta(seconds=2), T0 + timedelta(seconds=3))
        assert f.is_self_generated(e, now=T0 + timedelta(seconds=3)) is True

    def test_register_from_event_rejects_malformed(self) -> None:
        f = CorollaryDischargeFilter()
        assert f.register_from_event({"duration_seconds": 4.0}, now=T0) is False  # no start
        assert f.register_from_event("not a dict", now=T0) is False

    def test_missing_span_not_self_generated(self) -> None:
        f = CorollaryDischargeFilter()
        f.register_playback(T0, 5.0, now=T0)
        assert f.is_self_generated({}, now=T0) is False
        assert f.is_self_generated({"event_signature": {}}, now=T0) is False

    def test_windows_evict_after_retention(self) -> None:
        f = CorollaryDischargeFilter(buffer_seconds=0.0, retention_seconds=60.0)
        f.register_playback(T0, 1.0, now=T0)  # window end ~T0+1
        # Far past retention: the window is evicted, so even an entity from the
        # original window time is no longer tagged (memory stays bounded).
        later = T0 + timedelta(seconds=600)
        assert f.is_self_generated(_entity(T0, T0 + timedelta(seconds=1)), now=later) is False


class TestAgentCorollaryDischargeWiring:
    """The agent registers playback windows and tags entities in _on_entity_ready."""

    def _entity_event(self, start: datetime, end: datetime, eid: str) -> dict:
        return {
            "entity_id": eid,
            "timestamp": end.isoformat(),
            "species_code": "amecro",
            "common_name": "American Crow",
            "confidence": 0.9,
            "evidence": [],
            "event_signature": {
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
            "is_self_generated": False,
        }

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_entity_overlapping_playback_is_tagged(self, mock_cfg_cls: Mock) -> None:
        mock_cfg_cls.get_instance.return_value = _real_config()
        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.bus = Mock()  # db stays None → _persist_entity no-ops
        # Use a near-now start so the window stays within the 5-min retention.
        start = datetime.now(timezone.utc)
        agent._on_playback_event(
            PLAYBACK_TOPIC,
            {"start_time": start.isoformat(), "duration_seconds": 5.0, "source": "speaker"},
        )
        entity = self._entity_event(
            start + timedelta(seconds=2), start + timedelta(seconds=3), "e1"
        )
        agent._on_entity_ready(entity)
        assert entity["is_self_generated"] is True
        published = agent.bus.publish.call_args[0][1]
        assert published["is_self_generated"] is True

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_tagged_entity_persists_with_flag(self, mock_cfg_cls: Mock, tmp_path) -> None:
        """End-to-end seam: playback event → overlapping entity → the persisted
        DB row carries is_self_generated=True."""
        mock_cfg_cls.get_instance.return_value = _real_config()
        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.bus = Mock()
        agent.db = DetectionDB(db_path=tmp_path / "entities.db")
        start = datetime.now(timezone.utc)
        agent._on_playback_event(
            PLAYBACK_TOPIC,
            {"start_time": start.isoformat(), "duration_seconds": 5.0, "source": "speaker"},
        )
        agent._on_entity_ready(
            self._entity_event(start + timedelta(seconds=2), start + timedelta(seconds=3), "p1")
        )
        saved = next(e for e in agent.db.get_entities() if e.entity_id == "p1")
        assert saved.is_self_generated is True

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_entity_without_playback_not_tagged(self, mock_cfg_cls: Mock) -> None:
        mock_cfg_cls.get_instance.return_value = _real_config()
        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.bus = Mock()
        start = datetime.now(timezone.utc)
        entity = self._entity_event(start, start + timedelta(seconds=1), "e2")
        agent._on_entity_ready(entity)
        assert entity["is_self_generated"] is False

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_flag_on_subscribes_to_playback_topic(self, mock_cfg_cls: Mock) -> None:
        mock_cfg_cls.get_instance.return_value = _real_config()
        agent = EventCorrelatorAgent(window_seconds=3.0)
        assert agent.corollary_discharge_enabled is True
        subs = dict(agent.subscriptions())
        assert subs.get(PLAYBACK_TOPIC) == agent._on_playback_event

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_flag_off_no_playback_subscription_and_no_tagging(
        self, mock_cfg_cls: Mock
    ) -> None:
        """Default (disabled): no PLAYBACK_TOPIC subscription and the verdict
        is never recomputed — the entity keeps the False that
        _build_one_entity emits, even with a window planted in the filter."""
        mock_cfg_cls.get_instance.return_value = _real_config(corollary_enabled=False)
        agent = EventCorrelatorAgent(window_seconds=3.0)
        agent.bus = Mock()
        assert agent.corollary_discharge_enabled is False
        assert PLAYBACK_TOPIC not in [topic for topic, _ in agent.subscriptions()]

        # Plant an overlapping window directly — disabled still means no tag.
        start = datetime.now(timezone.utc)
        agent.corollary_discharge.register_playback(start, 5.0, "speaker")
        entity = self._entity_event(
            start + timedelta(seconds=2), start + timedelta(seconds=3), "off1"
        )
        agent._on_entity_ready(entity)
        assert entity["is_self_generated"] is False
        published = agent.bus.publish.call_args[0][1]
        assert published["is_self_generated"] is False

    @patch("orpheus_agent_event_correlator.main.OrpheusConfig")
    def test_flag_off_default_config_is_off(self, mock_cfg_cls: Mock) -> None:
        # A config with NO corollary_discharge section: the flag defaults OFF
        # (Reversibility Contract) — rollback is deleting the yaml key.
        mock_cfg_cls.get_instance.return_value = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}}, source="<test>"
        )
        agent = EventCorrelatorAgent(window_seconds=3.0)
        assert agent.corollary_discharge_enabled is False
