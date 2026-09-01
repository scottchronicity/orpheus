"""Late-arrival enrichment (cross-classifier-identity §1 "enrich existing event").

A slow classifier emitting AFTER the 3s window used to spawn a duplicate entity
for the same acoustic moment. With ``correlation.late_enrichment.enabled`` the
ClusterManager keeps a TTL'd map of chain root → recently-emitted entities and
folds the late observation into the existing entity instead.

Test-mode note: the map is populated in ``_expire_cluster`` AFTER
``on_entity_ready`` (so the cached dict carries the agent's in-place
``is_self_generated`` verdict). Sync-mode tests therefore emit+register by
calling ``manager._expire_cluster()`` directly — NOT ``flush_all()``, which is
the shutdown path and deliberately does not register.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock, patch

from orpheus_common.config import OrpheusConfig
from orpheus_common.detection.entity_taxonomy import derive_entity_type

from orpheus_agent_event_correlator.cluster_manager import (
    ClusterManager,
    Observation,
    enrich_entity_event,
)
from orpheus_agent_event_correlator.main import (
    ENTITY_UPDATED_TOPIC,
    EventCorrelatorAgent,
)


def _obs(
    *,
    species_code: str = "amecro",
    common_name: str = "American Crow",
    confidence: float = 0.8,
    event_id: str = "evt-1",
    root: str | None = "AM-001",
    sensor_id: str = "mic-1",
    intervals: list[dict[str, Any]] | None = None,
    taxonomy: dict[str, Any] | None = None,
    detection_type: str = "species.detected",
) -> Observation:
    return Observation(
        species_code=species_code,
        common_name=common_name,
        confidence=confidence,
        event_id=event_id,
        source_event_id=root,
        sensor_id=sensor_id,
        clip_path=None,
        context=None,
        intervals=intervals if intervals is not None else [
            {"start_seconds": 0.0, "end_seconds": 3.0}
        ],
        taxonomy=taxonomy,
        detection_type=detection_type,
        root_event_id=root,
    )


def _manager(
    *,
    enabled: bool = True,
    ttl: float = 300.0,
    cap: int = 2000,
    on_ready=None,
    on_enrich=None,
) -> tuple[ClusterManager, list[dict], list[tuple[dict, Observation]]]:
    """Sync-mode manager + the emitted/enriched recorders (default fakes)."""
    emitted: list[dict] = []
    enriched: list[tuple[dict, Observation]] = []

    def default_enrich(entity_event: dict, obs: Observation) -> bool:
        enriched.append((entity_event, obs))
        return True

    manager = ClusterManager(
        window_seconds=3.0,
        on_entity_ready=on_ready if on_ready is not None else emitted.append,
        enrich_late_arrivals=enabled,
        late_ttl_seconds=ttl,
        late_max_tracked_roots=cap,
        on_entity_enrich=on_enrich if on_enrich is not None else default_enrich,
    )
    return manager, emitted, enriched


def _emit(manager: ClusterManager) -> None:
    """Close the open cluster: emit + (when the flag is on) register."""
    manager._expire_cluster()


class TestFlagOff:
    def test_flag_off_is_byte_identical_and_never_touches_the_map(self) -> None:
        manager, emitted, enriched = _manager(enabled=False)
        manager.process_observation(_obs(event_id="evt-1"))
        _emit(manager)
        assert len(emitted) == 1
        assert manager._recent == {}  # never populated

        # The late arrival clusters into a SECOND entity — today's behavior.
        manager.process_observation(_obs(event_id="evt-2", confidence=0.9))
        _emit(manager)
        assert len(emitted) == 2
        assert enriched == []
        assert emitted[0]["entity_id"] != emitted[1]["entity_id"]


class TestHappyPath:
    def test_late_same_source_obs_enriches_instead_of_duplicating(self) -> None:
        manager, emitted, enriched = _manager()
        manager.process_observation(_obs(event_id="evt-1", confidence=0.6))
        _emit(manager)
        assert len(emitted) == 1
        entity = emitted[0]

        manager.process_observation(_obs(event_id="evt-2", confidence=0.9))
        assert len(emitted) == 1  # NO second entity
        assert len(enriched) == 1
        target, late_obs = enriched[0]
        assert target["entity_id"] == entity["entity_id"]
        assert late_obs.event_id == "evt-2"
        assert [e["event_id"] for e in entity["evidence"]] == ["evt-1", "evt-2"]
        assert entity["confidence"] == 0.9  # max of evidence

    def test_display_swap_only_on_higher_confidence(self) -> None:
        manager, emitted, _ = _manager()
        manager.process_observation(_obs(event_id="evt-1", confidence=0.8))
        _emit(manager)
        entity = emitted[0]

        # Lower-confidence late arrival (same species_code => same source):
        # evidence appended, display label unchanged.
        manager.process_observation(
            _obs(event_id="evt-2", confidence=0.5, common_name="Crow (juvenile)")
        )
        assert entity["common_name"] == "American Crow"
        assert entity["confidence"] == 0.8
        # Higher-confidence late arrival: display + confidence follow it.
        manager.process_observation(
            _obs(event_id="evt-3", confidence=0.95, common_name="Crow (adult)")
        )
        assert entity["common_name"] == "Crow (adult)"
        assert entity["confidence"] == 0.95

    def test_display_swap_when_codeless_evidence_holds_entity_max(self) -> None:
        # Adversarial-review fix: the swap gate must mirror _group_display,
        # which picks the max over species-CODED observations only. Here a
        # CODELESS item holds the entity-wide max (0.9), so gating on
        # entity_event["confidence"] would freeze the display forever: a coded
        # late arrival beating every coded item (0.8 > 0.6) but not the
        # codeless max never swapped, though a from-scratch rebuild would
        # display it.
        taxon = {"namespace": "ioc", "id": "Corvus brachyrhynchos"}
        manager, emitted, enriched = _manager()
        manager.process_observation(
            _obs(event_id="evt-1", confidence=0.6, species_code="amecro",
                 common_name="American Crow", detection_type="species.detected",
                 taxonomy=taxon)
        )
        manager.process_observation(
            _obs(event_id="evt-2", confidence=0.9, species_code="",
                 common_name="Crow", detection_type="audio.classified",
                 taxonomy=taxon)
        )
        _emit(manager)
        assert len(emitted) == 1
        entity = emitted[0]
        assert entity["species_code"] == "amecro"  # display = best CODED item
        assert entity["confidence"] == 0.9  # entity max = the codeless item

        # Coded late arrival: beats the coded max, not the codeless max.
        manager.process_observation(
            _obs(event_id="evt-3", confidence=0.8, species_code="crow",
                 common_name="Crow", detection_type="crow.analyzed", taxonomy=None)
        )
        assert len(enriched) == 1
        assert entity["species_code"] == "crow"  # display swapped
        assert entity["common_name"] == "Crow"
        # entity_type stays consistent with the (new) display label, exactly
        # as _build_one_entity derives it.
        assert entity["entity_type"] == derive_entity_type(
            taxonomy=None, species_code="crow", common_name="Crow",
            detection_type="crow.analyzed",
        )
        assert entity["confidence"] == 0.9  # entity max is NOT display-gated

        # Negative control: below the coded max — no swap.
        manager.process_observation(
            _obs(event_id="evt-4", confidence=0.5, species_code="comrav",
                 common_name="Crow", detection_type="species.detected")
        )
        assert entity["species_code"] == "crow"

    def test_multi_root_entity_enrichable_under_every_root(self) -> None:
        manager, emitted, enriched = _manager()
        # Two mics, two clips (roots), same crow — one merged entity.
        manager.process_observation(_obs(event_id="evt-1", root="AM-001", sensor_id="mic-1"))
        manager.process_observation(_obs(event_id="evt-2", root="AM-002", sensor_id="mic-2"))
        _emit(manager)
        assert len(emitted) == 1
        # Late obs against the SECOND root still finds the entity.
        manager.process_observation(_obs(event_id="evt-3", root="AM-002", confidence=0.9))
        assert len(emitted) == 1
        assert len(enriched) == 1


class TestSameSourceGate:
    def test_incompatible_label_falls_through_to_new_entity(self) -> None:
        manager, emitted, enriched = _manager()
        manager.process_observation(_obs(event_id="evt-1"))
        _emit(manager)

        manager.process_observation(
            _obs(
                event_id="evt-2",
                species_code="comloo",
                common_name="Common Loon",
            )
        )
        _emit(manager)
        assert len(emitted) == 2  # not the same source — separate entity
        assert enriched == []

    def test_same_label_disjoint_intervals_falls_through(self) -> None:
        # The gate keeps the interval-overlap half of _same_source: a crow at
        # 0-3s and a crow at 25-28s of the SAME clip are different moments.
        manager, emitted, enriched = _manager()
        manager.process_observation(
            _obs(event_id="evt-1", intervals=[{"start_seconds": 0.0, "end_seconds": 3.0}])
        )
        _emit(manager)
        manager.process_observation(
            _obs(event_id="evt-2", intervals=[{"start_seconds": 25.0, "end_seconds": 28.0}])
        )
        _emit(manager)
        assert len(emitted) == 2
        assert enriched == []

    def test_gate_scans_every_evidence_item_not_just_display(self) -> None:
        manager, emitted, enriched = _manager()
        # One same-source group whose two members merged on EXACT taxonomy while
        # keeping different display labels. Display = the higher-confidence
        # BirdNET item ("American Crow"); the PANNs "Crow" item is secondary.
        taxon = {"namespace": "ioc", "id": "Corvus brachyrhynchos"}
        manager.process_observation(
            _obs(event_id="evt-1", confidence=0.9, species_code="amecro",
                 common_name="American Crow", detection_type="species.detected",
                 taxonomy=taxon)
        )
        manager.process_observation(
            _obs(event_id="evt-2", confidence=0.4, species_code="",
                 common_name="Crow", detection_type="audio.classified",
                 taxonomy=taxon)
        )
        _emit(manager)
        assert len(emitted) == 1
        assert emitted[0]["species_code"] == "amecro"  # display is the BirdNET item
        # The late crow.analyzed (species_code="crow", common_name="Crow",
        # taxonomy=None) matches ONLY the secondary PANNs item — proving the
        # gate scans every evidence item, not just the display label.
        manager.process_observation(
            _obs(event_id="evt-3", confidence=0.7, species_code="crow",
                 common_name="Crow", detection_type="crow.analyzed", taxonomy=None)
        )
        assert len(emitted) == 1
        assert len(enriched) == 1


class TestSiblings:
    def test_sibling_entities_from_one_clip_both_stay_enrichable(self) -> None:
        # One clip (root) yields TWO same-source groups (crow @0-3s, loon
        # @10-13s) => two entities under the same root. A single-value map
        # would have lost one; the list keeps both reachable.
        manager, emitted, enriched = _manager()
        manager.process_observation(
            _obs(event_id="evt-c", species_code="amecro", common_name="American Crow",
                 intervals=[{"start_seconds": 0.0, "end_seconds": 3.0}])
        )
        manager.process_observation(
            _obs(event_id="evt-l", species_code="comloo", common_name="Common Loon",
                 intervals=[{"start_seconds": 10.0, "end_seconds": 13.0}])
        )
        _emit(manager)
        assert len(emitted) == 2

        manager.process_observation(
            _obs(event_id="evt-c2", species_code="amecro", common_name="American Crow",
                 confidence=0.9, intervals=[{"start_seconds": 1.0, "end_seconds": 2.0}])
        )
        manager.process_observation(
            _obs(event_id="evt-l2", species_code="comloo", common_name="Common Loon",
                 confidence=0.9, intervals=[{"start_seconds": 11.0, "end_seconds": 12.0}])
        )
        assert len(emitted) == 2  # no new entities
        assert len(enriched) == 2
        enriched_ids = {t["entity_id"] for t, _ in enriched}
        assert enriched_ids == {e["entity_id"] for e in emitted}


class TestLifecycle:
    def test_ttl_eviction(self) -> None:
        manager, emitted, enriched = _manager(ttl=10.0)
        with patch(
            "orpheus_agent_event_correlator.cluster_manager.time.monotonic"
        ) as clock:
            clock.return_value = 1000.0
            manager.process_observation(_obs(event_id="evt-1"))
            _emit(manager)
            # Past the TTL the record is evicted — the late obs clusters anew.
            clock.return_value = 1011.0
            manager.process_observation(_obs(event_id="evt-2"))
        _emit(manager)
        assert len(emitted) == 2
        assert enriched == []

    def test_size_cap_fifo_evicts_oldest_root(self) -> None:
        manager, _emitted, _ = _manager(cap=2)
        for i in range(3):
            manager.process_observation(_obs(event_id=f"evt-{i}", root=f"AM-{i:03d}"))
            _emit(manager)
        assert len(manager._recent) == 2
        assert "AM-000" not in manager._recent  # oldest-emitted evicted first

    def test_same_code_different_taxon_subs_both_land(self) -> None:
        # Adversarial-review must-fix: BirdNET's 6-char species_code collapses
        # labels ('corvus' covers 32 crow/raven species) and all sub-detections
        # of one clip share the parent event_id. A dedup keyed on
        # (event_id, species_code) alone swallowed the SECOND same-code taxon —
        # a Common Raven arriving after an American Crow vanished entirely.
        manager, emitted, enriched = _manager()
        manager.process_observation(_obs(event_id="evt-1", confidence=0.6))
        _emit(manager)
        entity = emitted[0]

        crow_tax = {"namespace": "ioc", "id": "Corvus brachyrhynchos"}
        raven_tax = {"namespace": "ioc", "id": "Corvus corax"}
        manager.process_observation(
            _obs(event_id="evt-late", species_code="corvus", common_name="American Crow",
                 confidence=0.7, taxonomy=crow_tax)
        )
        manager.process_observation(
            _obs(event_id="evt-late", species_code="corvus", common_name="Common Raven",
                 confidence=0.9, taxonomy=raven_tax)
        )
        assert len(emitted) == 1  # both enriched, no duplicate entity
        assert len(enriched) == 2  # BOTH persisted — the raven is not swallowed
        taxa = [(e.get("taxonomy") or {}).get("id") for e in entity["evidence"]]
        assert "Corvus corax" in taxa
        assert entity["confidence"] == 0.9

        # A TRUE redelivery (same event_id + code + taxon) still dedups.
        manager.process_observation(
            _obs(event_id="evt-late", species_code="corvus", common_name="Common Raven",
                 confidence=0.9, taxonomy=raven_tax)
        )
        assert len(enriched) == 2  # consumed without a third persist

    def test_multi_root_cross_clip_evidence_does_not_spuriously_reject(self) -> None:
        # Adversarial-review fix: pinning EVERY evidence item to the lookup
        # root compared clip-A-relative offsets against a clip-B late arrival
        # as if they shared a t=0 origin — spuriously rejecting a genuine
        # same-source late arrival (clustering's cross-root fallback accepts).
        manager, emitted, enriched = _manager()
        # One merged entity from two clips: clip-A crow @0-3s, clip-B crow @13-16s.
        manager.process_observation(
            _obs(event_id="evt-a", root="AM-001",
                 intervals=[{"start_seconds": 0.0, "end_seconds": 3.0}])
        )
        manager.process_observation(
            _obs(event_id="evt-b", root="AM-002", sensor_id="mic-2",
                 intervals=[{"start_seconds": 13.0, "end_seconds": 16.0}])
        )
        _emit(manager)
        assert len(emitted) == 1
        # Late crow on clip B at 5-8s: disjoint from clip-B's own 13-16s
        # evidence AND from clip-A's 0-3s if (wrongly) pinned to AM-002. The
        # cross-root fallback must accept it (label-compatible, unprovable
        # origin) — enrich, not duplicate.
        manager.process_observation(
            _obs(event_id="evt-late", root="AM-002", confidence=0.9,
                 intervals=[{"start_seconds": 5.0, "end_seconds": 8.0}])
        )
        assert len(emitted) == 1
        assert len(enriched) == 1

    def test_idempotent_duplicate_redelivery_consumed_without_second_publish(self) -> None:
        manager, emitted, enriched = _manager()
        manager.process_observation(_obs(event_id="evt-1"))
        _emit(manager)
        late = _obs(event_id="evt-2", confidence=0.9)
        manager.process_observation(late)
        manager.process_observation(_obs(event_id="evt-2", confidence=0.9))  # redelivery
        entity = emitted[0]
        assert len(emitted) == 1  # consumed, no new entity
        assert len(enriched) == 1  # persisted/published ONCE
        assert [e["event_id"] for e in entity["evidence"]] == ["evt-1", "evt-2"]

    def test_not_found_drops_record_and_falls_through(self) -> None:
        # on_entity_enrich returning False = row aged out of the DB: the stale
        # record is dropped and the observation survives as a new entity.
        manager, emitted, _enriched = _manager(on_enrich=lambda _e, _o: False)
        manager.process_observation(_obs(event_id="evt-1"))
        _emit(manager)
        manager.process_observation(_obs(event_id="evt-2"))
        _emit(manager)
        assert len(emitted) == 2  # fell through to clustering
        assert manager._recent.get("AM-001") is not None  # re-registered by 2nd emit

    def test_open_cluster_independence(self) -> None:
        manager, emitted, enriched = _manager()
        manager.process_observation(_obs(event_id="evt-1", root="AM-001"))
        _emit(manager)
        # An unrelated cluster is now open...
        manager.process_observation(
            _obs(event_id="evt-x", root="AM-002", species_code="comloo",
                 common_name="Common Loon")
        )
        # ...when a late AM-001 arrival shows up: it must enrich the emitted
        # entity, NOT be dumped into the open AM-002 cluster.
        manager.process_observation(_obs(event_id="evt-2", root="AM-001", confidence=0.9))
        assert len(enriched) == 1
        _emit(manager)
        assert len(emitted) == 2
        assert len(emitted[1]["evidence"]) == 1  # the open cluster stayed clean

    def test_flush_all_does_not_register(self) -> None:
        # flush_all is the shutdown path — no enrichment after shutdown.
        manager, _emitted, _ = _manager()
        manager.process_observation(_obs(event_id="evt-1"))
        events = manager.flush_all()
        assert len(events) == 1
        assert manager._recent == {}


class TestIsSelfGeneratedPreserved:
    def test_emit_time_verdict_survives_enrichment(self) -> None:
        # The agent mutates is_self_generated in place inside on_entity_ready;
        # registration happens after, so the cached dict carries the verdict —
        # and enrichment must never recompute it against the widened span.
        def tagging_ready(entity_event: dict) -> None:
            entity_event["is_self_generated"] = True

        manager, _, enriched = _manager(on_ready=tagging_ready)
        manager.process_observation(_obs(event_id="evt-1"))
        _emit(manager)
        manager.process_observation(_obs(event_id="evt-2", confidence=0.9))
        assert len(enriched) == 1
        assert enriched[0][0]["is_self_generated"] is True

    def test_wild_entity_cannot_be_flipped_by_late_arrival(self) -> None:
        manager, emitted, enriched = _manager()
        manager.process_observation(_obs(event_id="evt-1"))
        _emit(manager)
        assert emitted[0]["is_self_generated"] is False
        manager.process_observation(_obs(event_id="evt-2", confidence=0.9))
        assert enriched[0][0]["is_self_generated"] is False


class TestEnrichEntityEventPure:
    def test_updates_event_signature_span_and_unions(self) -> None:
        manager, emitted, _ = _manager()
        manager.process_observation(_obs(event_id="evt-1", sensor_id="mic-1"))
        _emit(manager)
        entity = emitted[0]
        sig_before = dict(entity["event_signature"])

        late = _obs(event_id="evt-2", sensor_id="mic-2", root="AM-001")
        changed = enrich_entity_event(entity, late)
        assert changed is True
        sig = entity["event_signature"]
        assert "mic-2" in sig["sensor_ids"]
        assert sig["audio_motion_source_ids"] == sig_before["audio_motion_source_ids"]
        # The span end moved forward to the late obs's (later) timestamp.
        assert sig["end_time"] >= sig_before["end_time"]

    def test_duplicate_mutates_nothing(self) -> None:
        manager, emitted, _ = _manager()
        manager.process_observation(_obs(event_id="evt-1"))
        _emit(manager)
        entity = emitted[0]
        before = len(entity["evidence"])
        assert enrich_entity_event(entity, _obs(event_id="evt-1")) is False
        assert len(entity["evidence"]) == before


def _agent() -> EventCorrelatorAgent:
    cfg = OrpheusConfig.from_dict(
        {
            "mqtt": {"broker_host": "localhost"},
            "correlation": {"late_enrichment": {"enabled": True}},
        },
        source="<test>",
    )
    with patch("orpheus_agent_event_correlator.main.OrpheusConfig") as mock_cfg:
        mock_cfg.get_instance.return_value = cfg
        agent = EventCorrelatorAgent()
    agent.bus = Mock()
    agent.db = Mock()
    agent.state_space = Mock()
    return agent


class TestAgentEnrichCallback:
    def test_persists_and_publishes_on_update_topic_only(self) -> None:
        agent = _agent()
        agent.db.update_entity.return_value = True
        enriched = {"entity_id": "e1", "species_code": "amecro", "common_name": "c",
                    "confidence": 0.9, "evidence": [], "timestamp": "2026-07-01T00:00:00+00:00"}
        ok = agent._on_entity_enrich(enriched, _obs(event_id="late-1"))
        assert ok is True
        assert agent.entities_enriched == 1
        assert agent.entities_emitted == 0  # the create counter never moves
        topics = [c.args[0] for c in agent.bus.publish.call_args_list]
        assert topics == [ENTITY_UPDATED_TOPIC]  # never the create topic
        agent.state_space.record_event.assert_not_called()  # no double count

    def test_missing_row_returns_false_and_skips_publish(self) -> None:
        agent = _agent()
        agent.db.update_entity.return_value = False
        enriched = {"entity_id": "e1", "species_code": "amecro", "common_name": "c",
                    "confidence": 0.9, "evidence": [], "timestamp": "2026-07-01T00:00:00+00:00"}
        assert agent._on_entity_enrich(enriched, _obs()) is False
        agent.bus.publish.assert_not_called()
        assert agent.entities_enriched == 0

    def test_persist_error_falls_back_to_clustering(self) -> None:
        # A failed persist must NOT consume the observation: returning False
        # makes the caller drop the (merged-but-unpersisted) record and cluster
        # the observation — a duplicate entity (the flag-off baseline) instead
        # of silent evidence loss + a divergence that blocks redelivery repair.
        agent = _agent()
        agent.db.update_entity.side_effect = RuntimeError("disk full")
        enriched = {"entity_id": "e1", "species_code": "amecro", "common_name": "c",
                    "confidence": 0.9, "evidence": [], "timestamp": "2026-07-01T00:00:00+00:00"}
        assert agent._on_entity_enrich(enriched, _obs()) is False
        assert agent.errors_count == 1
        assert agent.last_error is not None
        assert agent.last_error.startswith("RuntimeError")
        agent.bus.publish.assert_not_called()

    def test_publish_error_after_successful_persist_does_not_fall_back(self) -> None:
        # The row IS updated; a bus hiccup must not trigger the clustering
        # fallback (that would duplicate an entity whose update persisted).
        agent = _agent()
        agent.db.update_entity.return_value = True
        agent.bus.publish.side_effect = RuntimeError("broker away")
        enriched = {"entity_id": "e1", "species_code": "amecro", "common_name": "c",
                    "confidence": 0.9, "evidence": [], "timestamp": "2026-07-01T00:00:00+00:00"}
        assert agent._on_entity_enrich(enriched, _obs()) is True
        assert agent.entities_enriched == 1
        assert agent.errors_count == 1  # the publish failure is still visible

    def test_config_defaults_off(self) -> None:
        cfg = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}}, source="<test>"
        )
        with patch("orpheus_agent_event_correlator.main.OrpheusConfig") as mock_cfg:
            mock_cfg.get_instance.return_value = cfg
            agent = EventCorrelatorAgent()
        assert agent.late_enrichment_enabled is False
        assert agent.late_enrichment_ttl_seconds == 300.0
        assert agent.late_enrichment_max_tracked_roots == 2000
