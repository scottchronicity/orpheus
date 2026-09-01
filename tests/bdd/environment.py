"""behave hooks for the end-to-end cognitive-loop BDD suite.

Each scenario gets a FRESH event-correlator wired exactly like its real
``start()`` — minus the network: a Mock event bus captures publishes and a
tmp SQLite DB receives persistence. We drive the real entry points
(``_on_detection_event`` / ``_on_playback_event``) with synthetic detections
and force-expire clusters via ``flush_all``, so the whole loop
(parse → observation → cluster → entity_type derivation → corollary-discharge
tag → persist → publish) runs deterministically in-process.

Design note: the classifier leg (audio chunk → species) is NOT re-run on
synthetic audio (a sine wave can't be deterministically classified as a real
species) — it's covered by the audio-events tests. These scenarios inject the
post-classification detection. See docs/TESTING.md.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock

from orpheus_agent_event_correlator.cluster_manager import ClusterManager
from orpheus_agent_event_correlator.main import EventCorrelatorAgent
from orpheus_common.config import OrpheusConfig
from orpheus_common.detection import DetectionDB, TaxonomyEquivalenceDB, same_source


def before_scenario(context, scenario):
    context.tmpdir = Path(tempfile.mkdtemp(prefix="orpheus_bdd_"))

    # A real default config (so the agent's corollary_discharge / correlation
    # settings are real), installed as the singleton the agent reads.
    context.prev_config = OrpheusConfig._instance
    OrpheusConfig._instance = OrpheusConfig.from_dict(
        {
            "mqtt": {"broker_host": "localhost"},
            # The cognitive-loop scenarios exercise self-generated tagging,
            # which is opt-in (default off) since the Reversibility review.
            "corollary_discharge": {"enabled": True},
        },
        source="<bdd>",
    )

    agent = EventCorrelatorAgent(window_seconds=3.0)
    # The correlator publishes via self.bus (Actor base); a Mock captures publishes.
    agent.bus = Mock()
    agent.db = DetectionDB(db_path=context.tmpdir / "detections.db")
    agent.eq_db = TaxonomyEquivalenceDB(db_path=context.tmpdir / "equivalence.db")
    # Wire the cluster manager exactly as start() does (on_entity_ready drives
    # tag + persist + publish), minus the asyncio loop (we flush synchronously).
    agent.cluster_manager = ClusterManager(
        window_seconds=agent.window_seconds,
        max_cluster_duration_seconds=agent.max_cluster_duration_seconds,
        on_entity_ready=agent._on_entity_ready,
        is_equivalent=lambda a, b: same_source(a, b) or agent.eq_db.is_equivalent(a, b),
    )

    context.agent = agent
    context.detections = []
    context.published = []


def after_scenario(context, scenario):
    OrpheusConfig._instance = context.prev_config
    shutil.rmtree(context.tmpdir, ignore_errors=True)
