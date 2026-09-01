"""Serialization coverage for the EntityEvent model ([ARCH])."""

from orpheus_common.events import EntityEvent

# A representative correlator emit dict (mirrors ClusterManager._build_one_entity
# — the same keys, minus the not-yet-derived entity_type).
EMIT = {
    "entity_id": "e1",
    "timestamp": "2026-06-26T12:00:00+00:00",
    "species_code": "amecro",
    "common_name": "American Crow",
    "confidence": 0.9,
    "context": {"lat": 47.6, "lon": -122.3, "timestamp": "2026-06-26T12:00:00+00:00"},
    "evidence": [{"event_id": "d1", "species_code": "amecro", "confidence": 0.9}],
    "also_detected": [{"species_code": "comrav"}],
    "event_signature": {
        "sensor_ids": ["mic-1"],
        "start_time": "2026-06-26T12:00:00+00:00",
        "end_time": "2026-06-26T12:00:03+00:00",
    },
    "is_self_generated": False,
}


class TestEntityEventSerialization:
    def test_round_trip_is_superset_with_entity_type(self) -> None:
        out = EntityEvent.from_dict(EMIT).to_dict()
        # Every legacy key preserved verbatim...
        for key, value in EMIT.items():
            assert out[key] == value
        # ...plus exactly one additive key, defaulting to None.
        assert out["entity_type"] is None
        assert set(out) == set(EMIT) | {"entity_type"}

    def test_entity_type_preserved_when_present(self) -> None:
        ev = EntityEvent.from_dict({**EMIT, "entity_type": "Animal.Bird.Crow"})
        assert ev.entity_type == "Animal.Bird.Crow"
        assert ev.to_dict()["entity_type"] == "Animal.Bird.Crow"

    def test_legacy_dict_without_entity_type_is_none(self) -> None:
        assert EntityEvent.from_dict(EMIT).entity_type is None

    def test_unknown_keys_ignored(self) -> None:
        ev = EntityEvent.from_dict({**EMIT, "some_future_field": 123})
        assert "some_future_field" not in ev.to_dict()
        assert ev.entity_id == "e1"

    def test_defaults_for_minimal_dict(self) -> None:
        ev = EntityEvent.from_dict({"entity_id": "x"})
        assert ev.entity_id == "x"
        assert ev.species_code == ""
        assert ev.confidence == 0.0
        assert ev.entity_type is None
        assert ev.is_self_generated is False
        assert ev.evidence == []
        assert ev.also_detected == []
        assert ev.context is None
        assert ev.event_signature is None

    def test_complex_fields_preserved(self) -> None:
        ev = EntityEvent.from_dict(EMIT)
        assert ev.context == EMIT["context"]
        assert ev.evidence == EMIT["evidence"]
        assert ev.also_detected == EMIT["also_detected"]
        assert ev.event_signature == EMIT["event_signature"]
        assert ev.is_self_generated is False
