"""Generated agent-failure matrix (full powerset) through the real correlator.

Proves the matrix is GENERATED from the contract oracle (`matrix_gen`), not
hand-curated: every powerset row is driven through the in-process correlator and
asserted against the compositionally-derived expected outcome (entity count +
evidence-type set). The readable `@ci` frontier is also covered by
`agent_failure.feature`; this is the full-coverage layer. Fast — no models, no
docker. Run via `make sim-matrix-ci`.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, os.path.dirname(__file__))  # import the sibling oracle module
from matrix_gen import CONTRACT, generate_rows, synth_detection  # noqa: E402


@pytest.fixture
def correlator(tmp_path):
    """A fresh in-process event-correlator (Mock bus + tmp DB), wired like its
    real start() minus the network — mirrors tests/bdd/environment.py."""
    from orpheus_agent_event_correlator.cluster_manager import ClusterManager
    from orpheus_agent_event_correlator.main import EventCorrelatorAgent
    from orpheus_common.config import OrpheusConfig
    from orpheus_common.detection import DetectionDB, TaxonomyEquivalenceDB, same_source

    prev = OrpheusConfig._instance
    OrpheusConfig._instance = OrpheusConfig.from_dict(
        {"mqtt": {"broker_host": "localhost"}}, source="<matrix>"
    )
    agent = EventCorrelatorAgent(window_seconds=3.0)
    agent.bus = Mock()
    agent.db = DetectionDB(db_path=tmp_path / "detections.db")
    agent.eq_db = TaxonomyEquivalenceDB(db_path=tmp_path / "equivalence.db")
    agent.cluster_manager = ClusterManager(
        window_seconds=agent.window_seconds,
        max_cluster_duration_seconds=agent.max_cluster_duration_seconds,
        on_entity_ready=agent._on_entity_ready,
        is_equivalent=lambda a, b: same_source(a, b) or agent.eq_db.is_equivalent(a, b),
    )
    try:
        yield agent
    finally:
        OrpheusConfig._instance = prev


@pytest.mark.parametrize(
    "row", generate_rows(), ids=lambda r: "down=" + ("+".join(r.down) or "none")
)
def test_generated_matrix_row(correlator, row) -> None:
    for clf in row.surviving:
        correlator._on_detection_event(CONTRACT[clf]["topic"], synth_detection(clf))
    for entity_event in correlator.cluster_manager.flush_all():
        correlator._on_entity_ready(entity_event)

    entities = correlator.db.get_entities()
    assert len(entities) == row.expected_entities, (
        row.down,
        [e.species for e in entities],
    )
    if row.expected_entities:
        got = {ev.detection_type for ev in entities[0].evidence}
        assert got == set(row.expected_evidence), (row.down, got)
