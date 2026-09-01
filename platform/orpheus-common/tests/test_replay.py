"""Tests for historical event replay (Epic 4)."""

from datetime import datetime, timedelta, timezone

import pytest

from orpheus_common.detection import Detection, DetectionDB, Entity
from orpheus_common.replay import (
    DETECTION_TYPE_TOPICS,
    ENTITIES_TOPIC,
    REPLAY_FALLBACK_TOPIC,
    ReplayEngine,
)

T0 = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)


class _RecorderBus:
    """Minimal EventBus stand-in that records publishes (no broker)."""

    def __init__(self) -> None:
        self.published: list[tuple] = []

    def publish(self, topic, payload, qos=None, retain=False) -> None:
        self.published.append((topic, payload))

    def subscribe(self, topic_pattern, callback) -> None:  # pragma: no cover
        pass

    def unsubscribe(self, topic_pattern) -> None:  # pragma: no cover
        pass

    def connect(self) -> None:  # pragma: no cover
        pass

    def disconnect(self) -> None:  # pragma: no cover
        pass

    @property
    def is_connected(self) -> bool:  # pragma: no cover
        return True


def _make_db(tmp_path, events):
    """events: list of (detection_type, seconds_offset_from_T0)."""
    db = DetectionDB(db_path=tmp_path / "orpheus.db")
    for i, (dtype, offset) in enumerate(events):
        db.save(
            Detection(
                event_id=f"e{i}",
                timestamp=T0 + timedelta(seconds=offset),
                detection_type=dtype,
                channel=1,
                species_code="amecro",
                species_common="American Crow",
                confidence=0.9,
            )
        )
    return str(tmp_path / "orpheus.db")


class TestReplayEngine:
    def test_load_returns_count(self, tmp_path):
        src = _make_db(
            tmp_path,
            [("species.detected", 20), ("species.detected", 0), ("species.detected", 10)],
        )
        assert ReplayEngine(_RecorderBus()).load(src) == 3

    def test_play_tags_replay_and_routes_by_detection_type(self, tmp_path):
        src = _make_db(tmp_path, [("species.detected", 0)])
        bus = _RecorderBus()
        eng = ReplayEngine(bus, tag="t1", sleep=lambda s: None)
        eng.load(src)
        assert eng.play(speed=0) == 1

        topic, payload = bus.published[0]
        assert topic == DETECTION_TYPE_TOPICS["species.detected"]
        assert payload["_replay"] is True
        assert payload["_replay_tag"] == "t1"
        assert datetime.fromisoformat(payload["_original_timestamp"]) == T0
        assert payload["detection_type"] == "species.detected"  # original payload preserved

    def test_time_dilation_divides_gaps_by_speed(self, tmp_path):
        # Events 10s apart; speed=10 → 1.0s waits between them.
        src = _make_db(
            tmp_path,
            [("species.detected", 0), ("species.detected", 10), ("species.detected", 20)],
        )
        slept: list[float] = []
        eng = ReplayEngine(_RecorderBus(), sleep=slept.append)
        eng.load(src)
        eng.play(speed=10.0)
        assert slept == [1.0, 1.0]

    def test_speed_zero_is_as_fast_as_possible(self, tmp_path):
        src = _make_db(tmp_path, [("species.detected", 0), ("species.detected", 10)])
        slept: list[float] = []
        eng = ReplayEngine(_RecorderBus(), sleep=slept.append)
        eng.load(src)
        eng.play(speed=0)
        assert slept == []

    def test_time_range_filter_on_load(self, tmp_path):
        src = _make_db(
            tmp_path,
            [("species.detected", 0), ("species.detected", 100), ("species.detected", 200)],
        )
        n = ReplayEngine(_RecorderBus()).load(
            src, start=T0 + timedelta(seconds=50), end=T0 + timedelta(seconds=150)
        )
        assert n == 1  # only the middle event

    def test_unknown_detection_type_uses_fallback_topic(self, tmp_path):
        src = _make_db(tmp_path, [("weird.type", 0)])
        bus = _RecorderBus()
        eng = ReplayEngine(bus, sleep=lambda s: None)
        eng.load(src)
        eng.play(speed=0)
        assert bus.published[0][0] == REPLAY_FALLBACK_TOPIC

    def test_invalid_kind_raises(self, tmp_path):
        src = _make_db(tmp_path, [("species.detected", 0)])
        with pytest.raises(ValueError, match="kind must be one of"):
            ReplayEngine(_RecorderBus()).load(src, kind="bogus")


def _add_entities(src, offsets):
    """Save entities into the same DB file (entities + detections share it)."""
    from pathlib import Path

    db = DetectionDB(db_path=Path(src))
    for i, offset in enumerate(offsets):
        db.save_entity(
            Entity(
                entity_id=f"ent{i}",
                timestamp=T0 + timedelta(seconds=offset),
                species="corvus",
                common_name="American Crow",
                confidence=0.9,
            )
        )


class TestEntityAndMixedReplay:
    def test_entities_replay_on_entities_topic(self, tmp_path):
        src = _make_db(tmp_path, [])  # init the DB
        _add_entities(src, [0])
        bus = _RecorderBus()
        eng = ReplayEngine(bus, tag="e1", sleep=lambda s: None)
        assert eng.load(src, kind="entities") == 1
        eng.play(speed=0)

        topic, payload = bus.published[0]
        assert topic == ENTITIES_TOPIC
        assert payload["_replay"] is True
        assert payload["_replay_tag"] == "e1"
        assert datetime.fromisoformat(payload["_original_timestamp"]) == T0
        assert payload["species"] == "corvus"  # original Entity payload preserved

    def test_both_merges_in_chronological_order(self, tmp_path):
        # detection at +5s between two entities at 0s and +10s.
        src = _make_db(tmp_path, [("species.detected", 5)])
        _add_entities(src, [0, 10])
        bus = _RecorderBus()
        eng = ReplayEngine(bus, sleep=lambda s: None)
        assert eng.load(src, kind="both") == 3
        eng.play(speed=0)

        topics = [t for t, _ in bus.published]
        assert topics == [
            ENTITIES_TOPIC,
            DETECTION_TYPE_TOPICS["species.detected"],
            ENTITIES_TOPIC,
        ]

    def test_detections_kind_ignores_entities(self, tmp_path):
        src = _make_db(tmp_path, [("species.detected", 0)])
        _add_entities(src, [5])
        eng = ReplayEngine(_RecorderBus())
        assert eng.load(src, kind="detections") == 1  # entity not loaded


class TestLoadIsStreaming:
    def test_detections_load_streams_via_iter_query_not_query(self, tmp_path, monkeypatch):
        # query(limit=1_000_000) materialises the whole window of Detection
        # models — the OOM anti-pattern iter_query's docstring names replay for.
        # load() must use the streaming path (and gain iter_query's no-cap
        # semantics) instead.
        def _boom(self, *args, **kwargs):
            raise AssertionError("ReplayEngine.load must stream via iter_query")

        monkeypatch.setattr(DetectionDB, "query", _boom)
        src = _make_db(tmp_path, [("species.detected", 0), ("species.detected", 10)])
        assert ReplayEngine(_RecorderBus()).load(src) == 2

    def test_entity_cap_hit_logs_truncation_warning(self, tmp_path, monkeypatch):
        from unittest.mock import Mock

        from orpheus_common import replay as replay_mod

        warn_logger = Mock()
        monkeypatch.setattr(replay_mod, "logger", warn_logger)
        monkeypatch.setattr(replay_mod, "_ENTITY_LOAD_LIMIT", 2)
        src = _make_db(tmp_path, [])
        _add_entities(src, [0, 10, 20])
        assert ReplayEngine(_RecorderBus()).load(src, kind="entities") == 2
        # the silent-truncation cap must be loud when hit
        assert warn_logger.warning.called
