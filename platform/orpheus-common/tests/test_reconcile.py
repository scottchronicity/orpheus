"""Tests for the event-sourcing reconciliation set-difference (contract §3.3)."""

from __future__ import annotations

from types import SimpleNamespace

from orpheus_common.reconcile import (
    collect_db_event_ids,
    collect_stream_event_ids,
    reconcile_event_ids,
)


class TestReconcileEventIds:
    def test_equivalent_when_stream_subset_of_db(self):
        # Shadow phase: the DB may have ids the stream doesn't (DB-only) — still OK.
        r = reconcile_event_ids({"a", "b"}, {"a", "b", "c"})
        assert r["equivalent"] is True
        assert r["db_only"] == ["c"]
        assert r["stream_only"] == []
        assert r["both"] == 2

    def test_stream_only_is_the_violation(self):
        r = reconcile_event_ids({"a", "x"}, {"a"})
        assert r["equivalent"] is False  # "x" published but never recorded in the DB
        assert r["stream_only"] == ["x"]

    def test_exact_match(self):
        r = reconcile_event_ids({"a", "b"}, {"a", "b"})
        assert r["equivalent"] is True
        assert r["db_only"] == [] and r["stream_only"] == []

    def test_empty_both(self):
        r = reconcile_event_ids(set(), set())
        assert r["equivalent"] is True
        assert r == {
            "stream_count": 0,
            "db_count": 0,
            "both": 0,
            "db_only": [],
            "stream_only": [],
            "equivalent": True,
        }


class _FakeBus:
    """stream_replay replays a fixed set of payloads into the callback."""

    def __init__(self, payloads):
        self._payloads = payloads

    def stream_replay(self, stream, callback, *, subject=None):
        for p in self._payloads:
            callback("t", p)
        return len(self._payloads)


def test_collect_stream_event_ids_filters_by_detection_type():
    bus = _FakeBus(
        [
            {"event_id": "a", "detection_type": "audio.motion"},
            {"event_id": "b", "detection_type": "species.detected"},  # ignored
            {"event_id": "c", "detection_type": "audio.motion"},
            {"detection_type": "audio.motion"},  # no event_id -> ignored
        ]
    )
    assert collect_stream_event_ids(bus, "orpheus_domain", "audio.motion") == {"a", "c"}


class _FakeDb:
    """iter_query() streams rows for the requested detection_type; the DB side of
    reconcile (streaming so the whole table can't OOM the Jetson)."""

    def __init__(self, rows):
        self._rows = rows

    def iter_query(self, *, detection_type, batch_size=1000):
        return (r for r in self._rows if r.detection_type == detection_type)


def test_collect_db_event_ids_filters_type_and_drops_missing_event_id():
    db = _FakeDb(
        [
            SimpleNamespace(event_id="a", detection_type="audio.motion"),
            SimpleNamespace(event_id="b", detection_type="species.detected"),  # other type
            SimpleNamespace(event_id="c", detection_type="audio.motion"),
            SimpleNamespace(event_id=None, detection_type="audio.motion"),  # no id -> dropped
        ]
    )
    assert collect_db_event_ids(db, "audio.motion") == {"a", "c"}
