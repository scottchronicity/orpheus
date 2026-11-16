"""The entity-stats species query: correct per-name counts, served from the date range.

Regression: ``GROUP BY species`` let SQLite walk idx_entity_species over the
whole entities table instead of using the requested date range, so the kiosk's
24-hour view took 80-150 s on the station (1.9 M entities). It also labelled a
species code shared by two species (``corvus``: American Crow and Common Raven)
with whichever name the scan met first.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from orpheus_common.detection import DetectionDB
from orpheus_common.detection.models import Entity, EntityEvidence

from orpheus_ui.api import entities as ent

NOW = datetime.now(timezone.utc)


def _entity(i, species, common_name, ts):
    return Entity(
        entity_id=f"ent-{i}",
        timestamp=ts,
        species=species,
        common_name=common_name,
        evidence=[EntityEvidence(event_id=f"ev-{i}", sensor_id="mic-1", confidence=0.9)],
    )


@pytest.fixture
def db(tmp_path):
    db = DetectionDB(db_path=tmp_path / "det.db")
    rows = [
        ("corvus", "American Crow", NOW - timedelta(hours=1)),
        ("corvus", "American Crow", NOW - timedelta(hours=2)),
        ("corvus", "American Crow", NOW - timedelta(hours=3)),
        ("corvus", "Common Raven", NOW - timedelta(hours=4)),
        ("poecil", "", NOW - timedelta(hours=5)),  # no common name: shown by code
        ("corvus", "American Crow", NOW - timedelta(days=40)),  # outside 24 h
    ]
    for i, (species, name, ts) in enumerate(rows):
        db.save_entity(_entity(i, species, name, ts))
    return db


def test_counts_each_display_name_within_the_window(db):
    stats = ent._compute_entity_stats(db, start_time=NOW - timedelta(hours=24))  # noqa: SLF001
    assert stats["species_distribution"] == {"American Crow": 3, "Common Raven": 1, "poecil": 1}
    assert stats["unique_species_count"] == 3
    assert stats["total_count"] == 5


@pytest.mark.parametrize(
    ("start", "end", "expected_total"),
    [
        (None, None, 6),  # all time
        (NOW - timedelta(days=60), NOW - timedelta(days=30), 1),  # custom range
        (NOW - timedelta(hours=2, minutes=30), None, 2),
    ],
)
def test_respects_every_date_range(db, start, end, expected_total):
    stats = ent._compute_entity_stats(db, start_time=start, end_time=end)  # noqa: SLF001
    assert sum(stats["species_distribution"].values()) == expected_total == stats["total_count"]


def test_species_query_uses_the_date_range_not_the_species_index(db, monkeypatch):
    """The statement the stats run must not be planned as a walk of
    idx_entity_species (a full-table scan in species order)."""
    seen = []
    real_open = ent.open_connection

    def tracing_open(*args, **kwargs):
        conn = real_open(*args, **kwargs)
        conn.set_trace_callback(seen.append)
        return conn

    monkeypatch.setattr(ent, "open_connection", tracing_open)
    ent._compute_entity_stats(db, start_time=NOW - timedelta(hours=24))  # noqa: SLF001

    (species_sql,) = [s for s in seen if "COUNT(*) as count" in s and "GROUP BY +species" in s]
    conn = sqlite3.connect(str(db.db_path))
    plan = " ".join(row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + species_sql))
    assert "idx_entity_species" not in plan
    assert "timestamp>?" in plan.replace(" ", "")
