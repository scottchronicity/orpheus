"""Tests for state-space latent memory ([CORE] State Space Likelihood)."""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orpheus_common.events import EntityEvent
from orpheus_common.state_space import StateSpaceMemory, TemporalPattern, TimeWindow

T0 = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
COYOTE = "Animal.Critter.Coyote"
CROW = "Animal.Bird.Crow"


def _mem(tmp_path: Path, **kw) -> StateSpaceMemory:
    return StateSpaceMemory(db_path=tmp_path / "ss.db", **kw)


def _record_at(mem: StateSpaceMemory, entity_type: str, hours, days: int = 30) -> None:
    """Record one event per (day, hour) — simulates `days` of history."""
    for d in range(days):
        day = T0 + timedelta(days=d)
        for h in hours:
            mem.record_event(
                {"entity_type": entity_type, "timestamp": day.replace(hour=h).isoformat()}
            )


class TestStateSpaceGherkin:
    """The backlog's acceptance scenarios."""

    def test_high_likelihood_inside_historical_window(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path)
        _record_at(mem, COYOTE, [22, 23, 0, 1, 2, 3])  # 30 days, 22:00-04:00
        assert mem.query_likelihood(COYOTE, TimeWindow(hour_of_day=2)) > 0.7

    def test_low_likelihood_outside_historical_window(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path)
        _record_at(mem, COYOTE, [22, 23, 0, 1, 2, 3])
        assert mem.query_likelihood(COYOTE, TimeWindow(hour_of_day=14)) < 0.1

    def test_memory_persists_across_restart(self, tmp_path: Path) -> None:
        db = tmp_path / "ss.db"
        first = StateSpaceMemory(db_path=db)
        for _ in range(10):
            first.record_event({"entity_type": CROW, "timestamp": T0.replace(hour=8).isoformat()})
        del first
        # A fresh instance on the same file reads the persisted buckets.
        second = StateSpaceMemory(db_path=db)
        assert second.query_likelihood(CROW, TimeWindow(hour_of_day=8)) > 0.0


class TestStateSpaceApi:
    def test_no_history_is_zero(self, tmp_path: Path) -> None:
        assert _mem(tmp_path).query_likelihood(CROW, TimeWindow(hour_of_day=8)) == 0.0

    def test_no_hour_is_zero(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path)
        _record_at(mem, CROW, [8], days=3)
        assert mem.query_likelihood(CROW, TimeWindow()) == 0.0

    def test_records_entityevent_model_and_dict(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path)
        mem.record_event(
            EntityEvent(entity_id="x", timestamp=T0.replace(hour=8).isoformat(), entity_type=CROW)
        )
        mem.record_event({"entity_type": CROW, "timestamp": T0.replace(hour=8).isoformat()})
        assert mem.query_likelihood(CROW, TimeWindow(hour_of_day=8)) > 0.0

    def test_no_entity_type_is_noop(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path)
        mem.record_event({"entity_type": None, "timestamp": T0.isoformat()})
        mem.record_event({"timestamp": T0.isoformat()})
        assert mem.query_pattern(CROW).total == 0

    def test_unparseable_timestamp_is_skipped(self, tmp_path: Path) -> None:
        # A present-but-malformed timestamp must NOT be stamped with wall-clock
        # (that would corrupt the temporal marginal) — it's dropped.
        mem = _mem(tmp_path)
        mem.record_event({"entity_type": CROW, "timestamp": "not-a-timestamp"})
        assert mem.query_pattern(CROW).total == 0

    def test_absent_timestamp_falls_back_to_now(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path)
        pinned = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)
        mem.record_event({"entity_type": CROW}, now=pinned)
        assert mem.query_pattern(CROW).hourly[9] == 1

    def test_query_pattern_marginals(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path)
        _record_at(mem, CROW, [8], days=5)  # 5 events at hour 8
        pattern = mem.query_pattern(CROW)
        assert isinstance(pattern, TemporalPattern)
        assert pattern.total == 5
        assert pattern.hourly[8] == 5
        assert sum(pattern.hourly) == 5
        assert sum(pattern.daily) == 5
        assert sum(pattern.monthly) == 5

    def test_day_of_week_filter(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path)
        # Record only on the weekday of T0 (a Sunday=6) so a Monday(0) filter sees nothing.
        _record_at(mem, CROW, [8], days=1)
        only_t0_dow = T0.weekday()
        assert mem.query_likelihood(
            CROW, TimeWindow(hour_of_day=8, day_of_week=only_t0_dow)
        ) > 0.0
        other_dow = (only_t0_dow + 1) % 7
        assert mem.query_likelihood(CROW, TimeWindow(hour_of_day=8, day_of_week=other_dow)) == 0.0


class TestStateSpaceCache:
    def test_cache_populated_then_cleared_on_record(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path)
        _record_at(mem, CROW, [8], days=3)
        mem.query_likelihood(CROW, TimeWindow(hour_of_day=8))
        assert len(mem._cache) == 1
        mem.record_event({"entity_type": CROW, "timestamp": T0.replace(hour=8).isoformat()})
        assert len(mem._cache) == 0  # history changed → invalidated

    def test_cache_invalidation_is_scoped_per_entity_type(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path)
        _record_at(mem, CROW, [8], days=2)
        _record_at(mem, COYOTE, [2], days=2)
        mem.query_likelihood(CROW, TimeWindow(hour_of_day=8))
        mem.query_likelihood(COYOTE, TimeWindow(hour_of_day=2))
        assert len(mem._cache) == 2
        # Recording a CROW must not evict the COYOTE entry.
        mem.record_event({"entity_type": CROW, "timestamp": T0.replace(hour=8).isoformat()})
        assert [k for k in mem._cache] == [(COYOTE, 2, None, None)]

    def test_cache_entry_expires_after_ttl(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path, cache_ttl_seconds=10.0)
        _record_at(mem, CROW, [8], days=3)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mem.query_likelihood(CROW, TimeWindow(hour_of_day=8), now=now)
        key = (CROW, 8, None, None)
        assert mem._cache_get(key, now) is not None
        assert mem._cache_get(key, now + timedelta(seconds=11)) is None  # expired


class TestStateSpacePerformance:
    def test_query_under_100ms_on_representative_data(self, tmp_path: Path) -> None:
        mem = _mem(tmp_path)
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for d in range(30):  # 30 days x 24 hours = 720 events across many buckets
            day = base + timedelta(days=d)
            for h in range(24):
                ts = day.replace(hour=h).isoformat()
                mem.record_event({"entity_type": CROW, "timestamp": ts})
        start = time.perf_counter()
        mem.query_likelihood(CROW, TimeWindow(hour_of_day=8))
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        # Generous bound; the query is O(24) over pre-aggregated buckets. The
        # <100ms target is for the Jetson Orin NX (this dev box is faster).
        assert elapsed_ms < 100.0, f"query took {elapsed_ms:.1f}ms"
