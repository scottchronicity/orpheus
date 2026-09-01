"""Soup-to-nuts integration test for the cross-classifier-identity stack.

Simulates the full event pipeline:

    audio.motion (root)
        └─ bird-detection emits species.detected with (ioc, scientific) ref
        ├─ audio-events emits audio.classified with (audioset, mid) ref
        └─ crow-detection emits crow.analyzed (no taxonomy by design)

then drives all of those Observations through the correlator's
ClusterManager and asserts the resulting Entity captures every
classifier's opinion + the full chain + the right Layer 2 schema.

Validates the entire identity stack in one test — the closest we can
get to "real Jetson + real models" without the hardware. If this fails,
something in the cross-classifier-identity layers is broken end-to-end.

See docs/designs/cross-classifier-identity.md for the design this
exercises.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from orpheus_common.detection import (
    Detection,
    DetectionDB,
    Entity,
    TaxonomyEquivalenceDB,
    TaxonomyRef,
    TemporalInterval,
    discover_equivalences,
)

# Use the cluster manager directly — it's the correlator's core.
from orpheus_agent_event_correlator.cluster_manager import (  # type: ignore[import-not-found]
    ClusterManager,
    Observation,
)


@pytest.fixture
def db(tmp_path: Path) -> DetectionDB:
    return DetectionDB(db_path=tmp_path / "orpheus.db")


@pytest.fixture
def eq_db(tmp_path: Path) -> TaxonomyEquivalenceDB:
    return TaxonomyEquivalenceDB(db_path=tmp_path / "orpheus.db")  # shared file


@pytest.fixture
def t0() -> datetime:
    return datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)


def _persist_audio_motion(
    db: DetectionDB, *, event_id: str, t0: datetime
) -> Detection:
    """Simulate orpheus-agent-audio-motion emitting a Detection."""
    det = Detection(
        event_id=event_id,
        timestamp=t0,
        detection_type="audio.motion",
        channel=1,
        audio_clip_path=f"/data/orpheus/audio/{event_id}.flac",
        intervals=[TemporalInterval(start_seconds=0.0, end_seconds=10.0)],
    )
    det.root_event_id = det.event_id  # audio.motion is its own root
    db.save(det)
    return det


def _persist_bird_detection(
    db: DetectionDB, *, source: Detection, t0: datetime
) -> Detection:
    """Simulate orpheus-agent-bird-detection finding an American Crow.

    Emits one species.detected Detection (the per-species row that
    actually gets persisted; the aggregated MQTT event isn't persisted).
    """
    det = Detection(
        event_id=f"{source.event_id}_corvus",
        timestamp=t0,
        detection_type="species.detected",
        channel=1,
        species_code="corvus",
        species_common="American Crow",
        confidence=0.92,
        audio_clip_path=source.audio_clip_path,
        source_event_id=source.event_id,
        root_event_id=Detection.derive_root_event_id(source),
        taxonomy=TaxonomyRef(
            namespace="ioc",
            id="Corvus brachyrhynchos",
            common_name="American Crow",
        ),
        intervals=[
            TemporalInterval(start_seconds=0.0, end_seconds=3.0, confidence=0.7),
            TemporalInterval(start_seconds=3.0, end_seconds=6.0, confidence=0.92),
        ],
        metadata={"is_corvid": True, "species_scientific": "Corvus brachyrhynchos"},
    )
    db.save(det)
    return det


def _persist_audio_events(
    db: DetectionDB, *, source: Detection, t0: datetime
) -> Detection:
    """Simulate orpheus-agent-audio-events firing the AudioSet 'Crow' tag."""
    det = Detection(
        event_id=f"{source.event_id}_audioset_crow",
        timestamp=t0,
        detection_type="audio.classified",
        channel=1,
        species_code="audioset_/m/04s8yn",
        species_common="Crow",
        confidence=0.85,
        audio_clip_path=source.audio_clip_path,
        source_event_id=source.event_id,
        root_event_id=Detection.derive_root_event_id(source),
        taxonomy=TaxonomyRef(namespace="audioset", id="/m/04s8yn", common_name="Crow"),
        intervals=[
            TemporalInterval(start_seconds=0.5, end_seconds=2.8, confidence=0.85),
        ],
        metadata={"model": "panns_cnn14_sed"},
    )
    db.save(det)
    return det


def _persist_crow_analyzed(
    db: DetectionDB, *, bird_source: Detection, t0: datetime
) -> Detection:
    """Simulate orpheus-agent-crow-detection finding an alert call.

    Two hops from audio.motion — its source is bird-detection, but
    root_event_id traces all the way back via the chain.
    """
    det = Detection(
        event_id=f"crow_{bird_source.event_id}",
        timestamp=t0,
        detection_type="crow.analyzed",
        channel=1,
        species_code="crow",
        species_common="Crow",
        confidence=0.78,
        audio_clip_path=bird_source.audio_clip_path,
        source_event_id=bird_source.event_id,
        # 2-hop derive: bird-detection has root_event_id set, so we inherit it.
        root_event_id=Detection.derive_root_event_id(bird_source),
        taxonomy=None,  # crow-tools is a call-type analyzer, NOT a species classifier
        intervals=[
            TemporalInterval(start_seconds=1.2, end_seconds=1.9, confidence=0.78),
        ],
        metadata={"call_type": "alert", "age": "adult"},
    )
    db.save(det)
    return det


class TestSoupToNutsPipeline:
    """End-to-end test of the cross-classifier-identity stack."""

    def test_full_chain_pipeline(
        self,
        db: DetectionDB,
        t0: datetime,
    ) -> None:
        # ─── 1. Sensory input: audio.motion fires ────────────────────────
        audio_motion = _persist_audio_motion(db, event_id="am-001", t0=t0)
        assert audio_motion.root_event_id == "am-001"

        # ─── 2. Bird-detection enriches with species ─────────────────────
        bird = _persist_bird_detection(db, source=audio_motion, t0=t0)
        assert bird.source_event_id == "am-001"
        # The chain spine: bird's root_event_id traces back to audio.motion.
        assert bird.root_event_id == "am-001"
        assert bird.taxonomy == TaxonomyRef(
            namespace="ioc", id="Corvus brachyrhynchos"
        )

        # ─── 3. Audio-events enriches with AudioSet label ────────────────
        ae = _persist_audio_events(db, source=audio_motion, t0=t0)
        assert ae.root_event_id == "am-001"
        assert ae.taxonomy.namespace == "audioset"

        # ─── 4. Crow-detection enriches further (2 hops from audio.motion) ─
        crow = _persist_crow_analyzed(db, bird_source=bird, t0=t0)
        # Crow.analyzed's IMMEDIATE source is the bird event,
        # but its root_event_id traces all the way back to audio.motion.
        assert crow.source_event_id == bird.event_id
        assert crow.root_event_id == "am-001"
        assert crow.taxonomy is None  # crow-tools is a call-type analyzer

        # ─── 5. Verify the chain (the "metadata appended to metadata" view) ─
        chain = db.get_chain("am-001")
        assert len(chain) == 4
        types_in_chain = {d.detection_type for d in chain}
        assert types_in_chain == {
            "audio.motion",
            "species.detected",
            "audio.classified",
            "crow.analyzed",
        }
        # Chain is ordered by timestamp ascending.
        timestamps = [d.timestamp for d in chain]
        assert timestamps == sorted(timestamps)

        # ─── 6. Correlator clusters these into ONE Entity ────────────────
        # All three classifiers heard the SAME crow, overlapping in time.
        # BirdNET (ioc) and PANNs (audioset) are linked by a learned
        # equivalence; crow-tools shares the common name "Crow". So they
        # collapse into ONE crow Entity (source-identity, not co-occurrence).
        emitted: list[dict] = []

        def _crow_equivalent(a, b):
            ids = {getattr(a, "id", None), getattr(b, "id", None)}
            return ids == {"Corvus brachyrhynchos", "/m/04s8yn"}

        manager = ClusterManager(
            window_seconds=10.0,
            on_entity_ready=emitted.append,
            is_equivalent=_crow_equivalent,
        )
        # Construct Observations from each Detection (the correlator does
        # this internally in its MQTT handler — see _unpack_observations).
        for det in (bird, ae, crow):
            obs = Observation(
                species_code=det.species_code or "",
                common_name=det.species_common or "",
                confidence=det.confidence or 0.0,
                event_id=det.event_id,
                source_event_id=det.source_event_id,
                root_event_id=det.root_event_id,
                sensor_id="mic-1",
                clip_path=det.audio_clip_path,
                context=None,
                intervals=[iv.model_dump() for iv in (det.intervals or [])],
                taxonomy=det.taxonomy.model_dump() if det.taxonomy else None,
                detection_type=det.detection_type,
            )
            manager.process_observation(obs)
        # Force-flush the cluster. flush_all returns the entity events
        # rather than invoking the on_entity_ready callback (callback is
        # only for timer-driven expiration). Append them manually so the
        # rest of the test reads the same shape.
        emitted.extend(manager.flush_all())

        # ─── 7. Layer 2: ONE Entity with three pieces of evidence ───────
        assert len(emitted) == 1
        entity_event = emitted[0]
        assert len(entity_event["evidence"]) == 3
        evidence_by_type = {
            ev["detection_type"]: ev for ev in entity_event["evidence"]
        }
        assert set(evidence_by_type.keys()) == {
            "species.detected",
            "audio.classified",
            "crow.analyzed",
        }
        # Each piece of evidence carries its own species claim.
        assert evidence_by_type["species.detected"]["taxonomy"]["id"] == (
            "Corvus brachyrhynchos"
        )
        assert evidence_by_type["audio.classified"]["taxonomy"]["id"] == (
            "/m/04s8yn"
        )
        assert evidence_by_type["crow.analyzed"]["taxonomy"] is None
        # Legacy display fields populated from highest-confidence evidence (bird at 0.92).
        assert entity_event["species_code"] == "corvus"
        assert entity_event["common_name"] == "American Crow"

        # ─── 8. event_signature traces the chain ─────────────────────────
        sig = entity_event["event_signature"]
        assert "audio_motion_source_ids" in sig
        # All three observations came from audio.motion am-001.
        assert sig["audio_motion_source_ids"] == ["am-001"]

        # ─── 9. Persist the Entity round-trips through DB ────────────────
        entity = Entity.from_entity_event(entity_event)
        db.save_entity(entity)
        loaded = db.get_entities()
        assert len(loaded) == 1
        loaded_entity = loaded[0]
        assert loaded_entity.event_signature is not None
        assert loaded_entity.event_signature["audio_motion_source_ids"] == ["am-001"]
        # Per-evidence taxonomy survives DB round-trip.
        loaded_evs = {ev.detection_type: ev for ev in loaded_entity.evidence}
        assert loaded_evs["species.detected"].taxonomy == TaxonomyRef(
            namespace="ioc", id="Corvus brachyrhynchos"
        )
        assert loaded_evs["audio.classified"].taxonomy == TaxonomyRef(
            namespace="audioset", id="/m/04s8yn"
        )
        assert loaded_evs["crow.analyzed"].taxonomy is None

    def test_three_chains_produce_equivalence_via_auto_discovery(
        self,
        db: DetectionDB,
        eq_db: TaxonomyEquivalenceDB,
        t0: datetime,
    ) -> None:
        """When BirdNET and PANNs consistently fire together over many
        events, auto-discovery proposes the equivalence — without any
        hand-curated alias map."""
        # 10 audio.motion events, all with both BirdNET (ioc:Corvus
        # brachyrhynchos) and PANNs (audioset:/m/04s8yn) firing.
        for i in range(10):
            ts = t0 + timedelta(minutes=i)
            am = _persist_audio_motion(db, event_id=f"am-{i:03d}", t0=ts)
            _persist_bird_detection(db, source=am, t0=ts)
            _persist_audio_events(db, source=am, t0=ts)

        # Initially the equivalence graph is empty.
        crow_ioc = TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos")
        assert eq_db.equivalent_taxa(crow_ioc) == {crow_ioc}

        # Auto-discovery scans, sees perfect co-occurrence (Jaccard=1.0),
        # proposes as accepted. Anchor ``now`` to the fixture so the lookback
        # window always covers the synthetic events — without this the test
        # silently rots once wall-clock now drifts >lookback_days past t0.
        proposals = discover_equivalences(
            db,
            eq_db,
            lookback_days=30,
            min_cooccurrences=2,
            now=t0 + timedelta(hours=1),
        )
        recorded = [p for p in proposals if p["action"] == "recorded"]
        assert len(recorded) == 1
        assert recorded[0]["jaccard"] == 1.0
        assert recorded[0]["status"] == "accepted"

        # Now equivalent_taxa walks the new edge.
        assert eq_db.is_equivalent(
            TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos"),
            TaxonomyRef(namespace="audioset", id="/m/04s8yn"),
        ) is True

    def test_manual_equivalence_enables_cross_namespace_query(
        self,
        eq_db: TaxonomyEquivalenceDB,
    ) -> None:
        """Sanity: a manual equivalence row + an Entity with evidence
        in either namespace returns matching results when querying by
        either namespace's TaxonomyRef. This is the Layer-3-consumer use
        case for queries / corollary discharge / future Director."""
        crow_ioc = TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos")
        crow_audioset = TaxonomyRef(namespace="audioset", id="/m/04s8yn")

        # Record the equivalence manually (could come from auto-discovery,
        # seed data, or human input — all use the same primitive).
        eq_db.record_equivalence(
            crow_ioc, crow_audioset, confidence=1.0, source="manual"
        )

        # Confirm the equivalence walks both ways.
        eq_set = eq_db.equivalent_taxa(crow_ioc)
        assert crow_ioc in eq_set
        assert crow_audioset in eq_set
        eq_set2 = eq_db.equivalent_taxa(crow_audioset)
        assert crow_ioc in eq_set2
        assert crow_audioset in eq_set2
