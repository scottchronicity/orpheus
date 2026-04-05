"""Backward compatibility tests for legacy V1 JSON deserialization."""

from orpheus_common.detection.models import Detection


class TestLegacyV1Deserialization:
    """Verify that old V1 JSON payloads (without event system fields)
    still parse correctly into the V2 Detection model."""

    # Hardcoded legacy V1 JSON string from current main branch format
    LEGACY_V1_JSON = {
        "event_id": "bird_det_20251204_223557_ch1_001_amecro",
        "timestamp": "2025-12-04T22:35:58.123456+00:00",
        "detection_type": "species.detected",
        "channel": 1,
        "species_code": "amecro",
        "species_common": "American Crow",
        "confidence": 0.87,
        "audio_clip_path": "/data/orpheus/audio/audio_motion/1/test.flac",
        "metadata": {
            "start_time": 0.5,
            "end_time": 1.2,
            "model_version": "BirdNET_V2.4",
            "inference_time_ms": 145,
            "is_corvid": True,
        },
        "source_event_id": "audio_motion_20251204_223555_ch1",
    }

    def test_legacy_json_parses_without_error(self) -> None:
        """Legacy V1 JSON (no context, no event_timestamp) should parse."""
        detection = Detection.from_dict(self.LEGACY_V1_JSON)
        assert detection.event_id == "bird_det_20251204_223557_ch1_001_amecro"
        assert detection.detection_type == "species.detected"
        assert detection.species_code == "amecro"
        assert detection.confidence == 0.87

    def test_legacy_json_generates_event_timestamp_default(self) -> None:
        """V1 JSON missing event_timestamp gets a default."""
        detection = Detection.from_dict(self.LEGACY_V1_JSON)
        assert detection.event_timestamp is not None

    def test_legacy_json_context_is_none(self) -> None:
        """V1 JSON missing context should default to None."""
        detection = Detection.from_dict(self.LEGACY_V1_JSON)
        assert detection.context is None

    def test_legacy_json_preserves_source_event_id(self) -> None:
        """V1 JSON with source_event_id should preserve it."""
        detection = Detection.from_dict(self.LEGACY_V1_JSON)
        assert detection.source_event_id == "audio_motion_20251204_223555_ch1"

    def test_legacy_json_preserves_metadata(self) -> None:
        """V1 JSON metadata should be preserved."""
        detection = Detection.from_dict(self.LEGACY_V1_JSON)
        assert detection.metadata["model_version"] == "BirdNET_V2.4"
        assert detection.metadata["is_corvid"] is True

    def test_minimal_legacy_json(self) -> None:
        """Minimal V1 JSON (only required fields) should parse."""
        minimal = {
            "event_id": "test_001",
            "timestamp": "2025-12-05T12:00:00",
            "detection_type": "audio.motion",
        }
        detection = Detection.from_dict(minimal)
        assert detection.event_id == "test_001"
        assert detection.detection_type == "audio.motion"
        assert detection.context is None
        assert detection.source_event_id is None

    def test_legacy_json_missing_event_id_gets_uuid(self) -> None:
        """V1 JSON missing event_id should get auto-generated UUID."""
        no_event_id = {
            "timestamp": "2025-12-05T12:00:00",
            "detection_type": "audio.motion",
        }
        detection = Detection.from_dict(no_event_id)
        assert detection.event_id  # non-empty
        assert len(detection.event_id) == 36  # UUID format

    def test_v2_json_with_context_parses(self) -> None:
        """V2 JSON with context field should parse correctly."""
        v2_data = dict(self.LEGACY_V1_JSON)
        v2_data["context"] = {
            "lat": 47.6062,
            "lon": -122.3321,
            "sensor_id": "mic-01",
        }
        detection = Detection.from_dict(v2_data)
        assert detection.context is not None
        assert detection.context.lat == 47.6062
        assert detection.context.sensor_id == "mic-01"
