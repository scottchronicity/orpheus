"""Tests for base event system Pydantic schemas."""

from datetime import datetime, timezone

from orpheus_common.events import InferenceEvent, OrpheusBaseEvent, SpatiotemporalContext


class TestSpatiotemporalContext:
    """Tests for SpatiotemporalContext model."""

    def test_default_values(self) -> None:
        """Should create context with sensible defaults."""
        ctx = SpatiotemporalContext()
        assert ctx.lat is None
        assert ctx.lon is None
        assert ctx.elevation is None
        assert ctx.sensor_id == ""
        assert ctx.timestamp.tzinfo is not None  # UTC default

    def test_with_gps_coordinates(self) -> None:
        """Should accept GPS coordinates."""
        ctx = SpatiotemporalContext(lat=47.6062, lon=-122.3321, elevation=56.0, sensor_id="mic-01")
        assert ctx.lat == 47.6062
        assert ctx.lon == -122.3321
        assert ctx.elevation == 56.0
        assert ctx.sensor_id == "mic-01"

    def test_serialization_round_trip(self) -> None:
        """Should serialize and deserialize correctly."""
        ctx = SpatiotemporalContext(lat=47.6, lon=-122.3, sensor_id="mic-02")
        data = ctx.model_dump(mode="json")
        restored = SpatiotemporalContext(**data)
        assert restored.lat == ctx.lat
        assert restored.lon == ctx.lon
        assert restored.sensor_id == ctx.sensor_id


class TestOrpheusBaseEvent:
    """Tests for OrpheusBaseEvent model."""

    def test_default_factories(self) -> None:
        """Should auto-generate event_id and event_timestamp."""
        event = OrpheusBaseEvent()
        assert event.event_id  # non-empty UUID string
        assert len(event.event_id) == 36  # UUID v4 format
        assert event.event_timestamp.tzinfo is not None
        assert event.context is None

    def test_unique_event_ids(self) -> None:
        """Each event should get a unique UUID."""
        e1 = OrpheusBaseEvent()
        e2 = OrpheusBaseEvent()
        assert e1.event_id != e2.event_id

    def test_explicit_event_id(self) -> None:
        """Should accept explicit event_id."""
        event = OrpheusBaseEvent(event_id="custom-id-123")
        assert event.event_id == "custom-id-123"

    def test_with_context(self) -> None:
        """Should accept spatiotemporal context."""
        ctx = SpatiotemporalContext(lat=47.6, lon=-122.3, sensor_id="mic-01")
        event = OrpheusBaseEvent(context=ctx)
        assert event.context is not None
        assert event.context.lat == 47.6

    def test_without_context_backward_compat(self) -> None:
        """Should work without context (backward compat)."""
        event = OrpheusBaseEvent()
        assert event.context is None

    def test_source_event_id_on_base(self) -> None:
        """OrpheusBaseEvent should carry source_event_id for lineage."""
        event = OrpheusBaseEvent(source_event_id="parent-event-uuid")
        assert event.source_event_id == "parent-event-uuid"

    def test_source_event_id_defaults_none(self) -> None:
        """source_event_id should default to None."""
        event = OrpheusBaseEvent()
        assert event.source_event_id is None


class TestInferenceEventAlias:
    """Tests that InferenceEvent alias still works for backward compat."""

    def test_alias_is_base(self) -> None:
        """InferenceEvent should be the same class as OrpheusBaseEvent."""
        assert InferenceEvent is OrpheusBaseEvent

    def test_inherits_base_fields(self) -> None:
        """Should have all base event fields via the alias."""
        event = InferenceEvent()
        assert event.event_id
        assert event.event_timestamp is not None
        assert event.context is None
        assert event.source_event_id is None

    def test_source_event_id(self) -> None:
        """Should accept source_event_id for lineage tracking."""
        event = InferenceEvent(source_event_id="parent-event-uuid")
        assert event.source_event_id == "parent-event-uuid"


class TestDetectionInheritsBaseEvent:
    """Tests that Detection properly inherits from OrpheusBaseEvent."""

    def test_detection_is_base_event(self) -> None:
        """Detection should be a subclass of OrpheusBaseEvent."""
        from orpheus_common.detection.models import Detection

        assert issubclass(Detection, OrpheusBaseEvent)

    def test_detection_has_base_fields(self) -> None:
        """Detection should have all base event fields."""
        from orpheus_common.detection.models import Detection

        detection = Detection(
            timestamp=datetime.now(timezone.utc),
            detection_type="species.detected",
        )
        assert detection.event_id  # auto-generated UUID
        assert detection.event_timestamp is not None
        assert detection.context is None
        assert detection.source_event_id is None

    def test_detection_with_context(self) -> None:
        """Detection should accept spatiotemporal context."""
        from orpheus_common.detection.models import Detection

        ctx = SpatiotemporalContext(lat=47.6, lon=-122.3, sensor_id="mic-01")
        detection = Detection(
            timestamp=datetime.now(timezone.utc),
            detection_type="species.detected",
            context=ctx,
        )
        assert detection.context is not None
        assert detection.context.lat == 47.6
