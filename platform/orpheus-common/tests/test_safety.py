"""Tests for the hardware circuit breaker (orpheus_common.safety) + its config."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orpheus_common.config import (
    CircuitBreakerLimit,
    ConfigError,
    OrpheusConfig,
    _parse_circuit_breakers,
)
from orpheus_common.safety import BreakerStatus, CircuitBreaker

T0 = datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)


def _breaker(tmp_path: Path, limits, on_trip=None) -> CircuitBreaker:
    return CircuitBreaker(limits, db_path=tmp_path / "cb.db", on_trip=on_trip)


class TestCircuitBreakerGherkin:
    """The acceptance scenarios from the [SAFETY] backlog item."""

    def test_allows_actions_within_limit(self, tmp_path: Path) -> None:
        cb = _breaker(tmp_path, {"audio_playback": (3, 3600)})
        cb.record("audio_playback", now=T0)
        cb.record("audio_playback", now=T0)
        assert cb.check("audio_playback", now=T0) is True

    def test_trips_at_limit_and_fires_on_trip(self, tmp_path: Path) -> None:
        trips: list[BreakerStatus] = []
        cb = _breaker(tmp_path, {"audio_playback": (3, 3600)}, on_trip=trips.append)
        for _ in range(3):
            cb.record("audio_playback", now=T0)
        assert cb.check("audio_playback", now=T0) is False
        assert len(trips) == 1
        assert trips[0].action == "audio_playback"
        assert trips[0].is_tripped is True
        assert trips[0].count == 3
        assert trips[0].limit == 3

    def test_resets_after_window_expires(self, tmp_path: Path) -> None:
        cb = _breaker(tmp_path, {"audio_playback": (3, 3600)})
        for _ in range(3):
            cb.record("audio_playback", now=T0)
        assert cb.check("audio_playback", now=T0) is False
        # 3601s later the window has slid past all three events → reset to 0.
        assert cb.check("audio_playback", now=T0 + timedelta(seconds=3601)) is True


class TestCircuitBreakerApi:
    def test_unconfigured_action_never_throttled(self, tmp_path: Path) -> None:
        cb = _breaker(tmp_path, {"audio_playback": (1, 3600)})
        for _ in range(10):
            cb.record("feeder_drop", now=T0)
        assert cb.check("feeder_drop", now=T0) is True
        status = cb.get_status("feeder_drop", now=T0)
        assert status.is_tripped is False
        assert status.limit == 0

    def test_reset_clears_counter(self, tmp_path: Path) -> None:
        cb = _breaker(tmp_path, {"a": (2, 3600)})
        cb.record("a", now=T0)
        cb.record("a", now=T0)
        assert cb.check("a", now=T0) is False
        cb.reset("a")
        assert cb.check("a", now=T0) is True
        assert cb.get_status("a", now=T0).count == 0

    def test_get_status_fields_and_resets_at(self, tmp_path: Path) -> None:
        cb = _breaker(tmp_path, {"a": (3, 3600)})
        cb.record("a", now=T0)
        status = cb.get_status("a", now=T0)
        assert isinstance(status, BreakerStatus)
        assert (status.action, status.count, status.limit, status.window_seconds) == (
            "a",
            1,
            3,
            3600,
        )
        assert status.is_tripped is False
        assert status.resets_at == (T0 + timedelta(seconds=3600)).isoformat()

    def test_status_resets_at_none_when_empty(self, tmp_path: Path) -> None:
        status = _breaker(tmp_path, {"a": (3, 3600)}).get_status("a", now=T0)
        assert status.count == 0
        assert status.resets_at is None

    def test_sliding_window_only_counts_recent(self, tmp_path: Path) -> None:
        cb = _breaker(tmp_path, {"a": (3, 100)})
        cb.record("a", now=T0)
        cb.record("a", now=T0 + timedelta(seconds=60))
        # At T0+120 the first event (age 120s) is outside the 100s window.
        assert cb.get_status("a", now=T0 + timedelta(seconds=120)).count == 1

    def test_state_persists_across_instances(self, tmp_path: Path) -> None:
        cb1 = _breaker(tmp_path, {"a": (2, 3600)})
        cb1.record("a", now=T0)
        cb1.record("a", now=T0)
        # A fresh breaker on the same DB file sees the prior records (restart-safe).
        cb2 = CircuitBreaker({"a": (2, 3600)}, db_path=tmp_path / "cb.db")
        assert cb2.check("a", now=T0) is False

    def test_naive_now_treated_as_utc(self, tmp_path: Path) -> None:
        cb = _breaker(tmp_path, {"a": (1, 3600)})
        naive = datetime(2026, 6, 25, 12, 0, 0)  # no tzinfo
        cb.record("a", now=naive)
        assert cb.check("a", now=naive) is False

    def test_on_trip_failure_never_breaks_the_gate(self, tmp_path: Path) -> None:
        def boom(_status: BreakerStatus) -> None:
            raise RuntimeError("notifier exploded")

        cb = _breaker(tmp_path, {"a": (1, 3600)}, on_trip=boom)
        cb.record("a", now=T0)
        # Even though on_trip raises, check() still returns the gate decision.
        assert cb.check("a", now=T0) is False

    def test_record_if_allowed_gates_and_records_atomically(self, tmp_path: Path) -> None:
        cb = _breaker(tmp_path, {"a": (2, 3600)})
        assert cb.record_if_allowed("a", now=T0) is True
        assert cb.record_if_allowed("a", now=T0) is True
        # The third is denied AND records nothing — the count stays at the limit.
        assert cb.record_if_allowed("a", now=T0) is False
        assert cb.get_status("a", now=T0).count == 2

    def test_record_if_allowed_unconfigured_always_allowed(self, tmp_path: Path) -> None:
        cb = _breaker(tmp_path, {"a": (1, 3600)})
        assert cb.record_if_allowed("unfused", now=T0) is True

    def test_on_trip_fires_once_per_transition(self, tmp_path: Path) -> None:
        trips: list[BreakerStatus] = []
        cb = _breaker(tmp_path, {"a": (1, 3600)}, on_trip=trips.append)
        cb.record("a", now=T0)
        assert cb.check("a", now=T0) is False
        assert cb.check("a", now=T0) is False  # still tripped → no repeat notification
        assert len(trips) == 1
        cb.reset("a")
        assert cb.check("a", now=T0) is True  # recovered → latch cleared
        cb.record("a", now=T0)
        assert cb.check("a", now=T0) is False  # trips again → second notification
        assert len(trips) == 2


class TestResetLatch:
    def test_reset_clears_the_trip_latch(self, tmp_path: Path) -> None:
        # After a manual reset, a re-trip via the record()-then-check() flow
        # (no intervening ALLOWED check to clear the latch through recovery) is
        # a FRESH allowed→denied edge and must re-fire on_trip.
        trips: list[BreakerStatus] = []
        cb = _breaker(tmp_path, {"a": (1, 3600)}, on_trip=trips.append)
        cb.record("a", now=T0)
        assert cb.check("a", now=T0) is False
        assert len(trips) == 1
        cb.reset("a")
        cb.record("a", now=T0)  # refill to the limit, no allowed check between
        assert cb.check("a", now=T0) is False
        assert len(trips) == 2  # fresh trip notified (latch was cleared by reset)


class TestGlobalSweep:
    """The cross-action sweep: per-record pruning is per-ACTION only, so dynamic
    one-off action keys (per-client rate limiting: rotated JWTs, garbage tokens)
    each leave immortal rows — the sweep bounds the ledger across ALL keys."""

    @staticmethod
    def _rows(tmp_path: Path) -> list[str]:
        import sqlite3

        conn = sqlite3.connect(tmp_path / "cb.db")
        try:
            return [
                r[0]
                for r in conn.execute(
                    "SELECT action FROM circuit_breaker_events ORDER BY action"
                )
            ]
        finally:
            conn.close()

    def test_every_nth_record_sweeps_dead_client_keys(self, tmp_path: Path) -> None:
        cb = CircuitBreaker({}, db_path=tmp_path / "cb.db", default_limit=(100, 60))
        cb._sweep_every = 3
        # A one-off client key records once and never returns (its rows are
        # untouchable by the per-action prune under any OTHER key).
        assert cb.record_if_allowed("dead-token", now=T0) is True
        t1 = T0 + timedelta(hours=1)
        assert cb.record_if_allowed("client-1", now=t1) is True
        assert cb.record_if_allowed("client-2", now=t1) is True  # 3rd record → sweep
        # The dead key's row (older than the 60s window at t1) is gone; the
        # in-window rows survive.
        assert self._rows(tmp_path) == ["client-1", "client-2"]

    def test_sweep_uses_largest_window_never_touching_live_rows(
        self, tmp_path: Path
    ) -> None:
        # Two windows (60s default, 3600s configured): the sweep cutoff is the
        # LARGEST, so the slow action's in-window rows are never collateral.
        cb = CircuitBreaker(
            {"slow": (10, 3600)}, db_path=tmp_path / "cb.db", default_limit=(100, 60)
        )
        cb._sweep_every = 2
        assert cb.record_if_allowed("slow", now=T0) is True
        # 30 min later: 'slow' is still inside its 3600s window.
        t1 = T0 + timedelta(minutes=30)
        assert cb.record_if_allowed("client", now=t1) is True  # 2nd record → sweep
        assert self._rows(tmp_path) == ["client", "slow"]  # slow row untouched

    def test_no_limits_configured_never_sweeps(self, tmp_path: Path) -> None:
        # Nothing gated ⇒ nothing recorded ⇒ the sweep is a no-op by design.
        cb = CircuitBreaker({}, db_path=tmp_path / "cb.db")
        assert cb._max_window_seconds() is None
        assert cb.record_if_allowed("anything", now=T0) is True  # ungated, unrecorded
        assert self._rows(tmp_path) == []


class TestCircuitBreakerConfig:
    def test_from_config_builds_limits(self, tmp_path: Path) -> None:
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "circuit_breakers": {"audio_playback": {"limit": 2, "window_seconds": 3600}},
            },
            source="<test>",
        )
        cb = CircuitBreaker.from_config(cfg, db_path=tmp_path / "cb.db")
        cb.record("audio_playback", now=T0)
        cb.record("audio_playback", now=T0)
        assert cb.check("audio_playback", now=T0) is False

    def test_parses_section(self) -> None:
        cfg = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "circuit_breakers": {"feeder_drop": {"limit": 1, "window_seconds": 86400}},
            },
            source="<test>",
        )
        assert cfg.circuit_breakers["feeder_drop"] == CircuitBreakerLimit(1, 86400)

    def test_absent_section_is_empty(self) -> None:
        cfg = OrpheusConfig.from_dict({"mqtt": {"broker_host": "localhost"}}, source="<test>")
        assert cfg.circuit_breakers == {}

    def test_to_dict_round_trips_flat_shape(self) -> None:
        section = {"relay_toggle": {"limit": 10, "window_seconds": 3600}}
        cfg = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}, "circuit_breakers": section},
            source="<test>",
        )
        assert cfg.to_dict()["circuit_breakers"] == section

    def test_missing_field_raises_config_error(self) -> None:
        with pytest.raises(ConfigError, match="circuit_breakers.audio_playback"):
            _parse_circuit_breakers({"audio_playback": {"limit": 3}})

    def test_nonpositive_window_raises(self) -> None:
        with pytest.raises(ConfigError, match="window_seconds"):
            _parse_circuit_breakers({"a": {"limit": 3, "window_seconds": 0}})

    def test_non_mapping_section_raises(self) -> None:
        with pytest.raises(ConfigError, match="must be a mapping"):
            _parse_circuit_breakers(["not", "a", "dict"])


class TestDefaultLimit:
    """default_limit — one policy over dynamic action keys (portal N2: the
    action is the client id). None (default) = historical never-throttled."""

    def test_none_default_preserves_unconfigured_pass(self, tmp_path):
        cb = CircuitBreaker({}, db_path=tmp_path / "cb.db")
        assert cb.record_if_allowed("client-a") is True
        assert cb.get_status("client-a").limit == 0  # ungated

    def test_default_limit_gates_any_action_key(self, tmp_path):
        cb = CircuitBreaker({}, db_path=tmp_path / "cb.db", default_limit=(2, 60))
        assert cb.record_if_allowed("client-a") is True
        assert cb.record_if_allowed("client-a") is True
        assert cb.record_if_allowed("client-a") is False  # tripped at the limit
        # per-client isolation: a different key has its own window
        assert cb.record_if_allowed("client-b") is True

    def test_configured_action_overrides_default(self, tmp_path):
        cb = CircuitBreaker(
            {"special": (1, 60)}, db_path=tmp_path / "cb.db", default_limit=(5, 60)
        )
        assert cb.record_if_allowed("special") is True
        assert cb.record_if_allowed("special") is False  # its own tighter limit
