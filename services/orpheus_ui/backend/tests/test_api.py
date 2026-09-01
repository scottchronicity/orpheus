"""Tests for API endpoints."""

import json as _json
from unittest.mock import MagicMock, patch

import pytest


def _det_to_row(det):
    """Detection -> detections-table row dict (DetectionDB.query_rows shape).

    The history/stats endpoints consume raw rows; tests keep building
    Detection models (readable) and convert here, mirroring
    save_detection's column serialisation. Plain dicts work as row
    doubles: the endpoints access ``row[key]`` and ``key in row.keys()``.
    """
    event_metadata = {}
    if det.context is not None:
        ctx = det.context
        event_metadata["context"] = (
            ctx.model_dump(mode="json") if hasattr(ctx, "model_dump") else dict(ctx)
        )
    return {
        "event_id": det.event_id,
        "timestamp": det.timestamp.isoformat(),
        "detection_type": det.detection_type,
        "channel": det.channel,
        "species_code": det.species_code,
        "species_common": det.species_common,
        "confidence": det.confidence,
        "audio_clip_path": det.audio_clip_path,
        "metadata": _json.dumps(det.metadata) if det.metadata else None,
        "source_event_id": det.source_event_id,
        "root_event_id": det.root_event_id,
        "event_metadata": _json.dumps(event_metadata) if event_metadata else None,
        "intervals_json": (
            _json.dumps([iv.model_dump(mode="json") for iv in det.intervals])
            if det.intervals
            else None
        ),
        "taxonomy_namespace": det.taxonomy.namespace if det.taxonomy else None,
        "taxonomy_id": det.taxonomy.id if det.taxonomy else None,
    }


class TestSystemAPI:
    """Tests for system API endpoints."""

    def test_health_response_model(self):
        """Test HealthResponse model structure."""
        from orpheus_ui.api.system import HealthResponse

        health = HealthResponse(
            status="ok",
            cpu_percent=25.5,
            memory_percent=60.0,
            disk_percent=45.0,
            uptime_seconds=86400,
        )
        assert health.status == "ok"
        assert health.cpu_percent == 25.5
        assert health.uptime_seconds == 86400

    def test_service_status_model(self):
        """Test ServiceStatus model structure."""
        from orpheus_ui.api.system import ServiceStatus

        status = ServiceStatus(
            name="orpheus-backplane",
            status="running",
            reason="",
        )
        assert status.name == "orpheus-backplane"
        assert status.status == "running"

    def test_services_response_model(self):
        """Test ServicesResponse model structure."""
        from orpheus_ui.api.system import ServicesResponse, ServiceStatus

        services = [
            ServiceStatus(name="orpheus-backplane", status="running", reason=""),
            ServiceStatus(name="orpheus-ui", status="running", reason=""),
        ]
        response = ServicesResponse(services=services)
        assert len(response.services) == 2

    def test_get_health_endpoint(self):
        """Test get_health endpoint returns valid metrics."""
        from orpheus_ui.api.system import get_health
        from orpheus_ui.auth.models import User

        # Create a mock user
        mock_user = MagicMock(spec=User)

        # Call the endpoint
        result = get_health(user=mock_user)

        assert result.status == "ok"
        assert 0 <= result.cpu_percent <= 100
        assert 0 <= result.memory_percent <= 100
        assert 0 <= result.disk_percent <= 100
        assert result.uptime_seconds > 0

    def test_get_health_endpoint_includes_disk_info(self):
        """Test get_health endpoint includes disk_system and disk_data."""
        from orpheus_ui.api.system import get_health
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch("orpheus_ui.api.system.get_data_storage_usage") as mock_storage:
            mock_storage.return_value = {
                "ok": True,
                "path": "/data/orpheus",
                "total": 500000000000,
                "used": 200000000000,
                "free": 300000000000,
                "percent": 40.0,
            }
            result = get_health(user=mock_user)

            # Verify disk_system is present and valid
            assert result.disk_system is not None
            assert result.disk_system.path == "/"
            assert 0 <= result.disk_system.percent <= 100
            assert result.disk_system.ok is True

            # Verify disk_data is present and valid
            assert result.disk_data is not None
            assert result.disk_data.path == "/data/orpheus"
            assert result.disk_data.percent == 40.0
            assert result.disk_data.ok is True

    def test_get_storage_data_endpoint(self):
        """Test get_storage_data endpoint."""
        from orpheus_ui.api.system import get_storage_data
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch("orpheus_ui.api.system.get_data_storage_usage") as mock_storage:
            mock_storage.return_value = {
                "total_gb": 500,
                "used_gb": 200,
                "free_gb": 300,
                "percent_used": 40.0,
            }
            result = get_storage_data(user=mock_user)
            assert result["total_gb"] == 500
            assert result["percent_used"] == 40.0

    def test_get_storage_hardware_endpoint(self):
        """Test get_storage_hardware endpoint."""
        from orpheus_ui.api.system import get_storage_hardware
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch("orpheus_ui.api.system.get_storage_hardware_info") as mock_hw:
            mock_hw.return_value = {"drives": [{"name": "sda", "size": "500GB"}]}
            result = get_storage_hardware(user=mock_user)
            assert "drives" in result

    def test_get_services_status_no_systemctl(self):
        """Test services status when systemctl is not available."""
        from orpheus_ui.api.system import get_services_status
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        mock_config = MagicMock()
        mock_config.dashboard_services.return_value = ["orpheus-ui", "orpheus-backplane"]

        with patch("shutil.which", return_value=None):
            with patch("os.path.exists", return_value=False):
                with patch("orpheus_common.OrpheusConfig.get_instance", return_value=mock_config):
                    result = get_services_status(user=mock_user)
                    assert len(result.services) == 2
                    # orpheus-ui should show as running in dev mode
                    orpheus_ui_status = next(s for s in result.services if s.name == "orpheus-ui")
                    assert orpheus_ui_status.status == "running"

    def test_get_services_status_with_systemctl(self):
        """Test services status when systemctl is available."""

        from orpheus_ui.api.system import get_services_status
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        mock_config = MagicMock()
        mock_config.dashboard_services.return_value = ["orpheus-ui"]

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("shutil.which", return_value="/bin/systemctl"):
            with patch("subprocess.run", return_value=mock_result) as _:
                with patch("orpheus_common.OrpheusConfig.get_instance", return_value=mock_config):
                    result = get_services_status(user=mock_user)
                    assert len(result.services) == 1
                    assert result.services[0].status == "running"

    def test_get_services_status_timeout(self):
        """Test services status handles timeout."""
        import subprocess

        from orpheus_ui.api.system import get_services_status
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        mock_config = MagicMock()
        mock_config.dashboard_services.return_value = ["orpheus-ui"]

        with patch("shutil.which", return_value="/bin/systemctl"):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("systemctl", 2)):
                with patch("orpheus_common.OrpheusConfig.get_instance", return_value=mock_config):
                    result = get_services_status(user=mock_user)
                    assert result.services[0].status == "unknown"
                    assert "Timeout" in result.services[0].reason


class TestDiagnosticsAPI:
    """Tests for diagnostics API endpoints."""

    def test_non_bird_sounds_filter(self):
        """Test is_bird_sound helper function."""
        from orpheus_ui.api.diagnostics import NON_BIRD_SOUNDS, is_bird_sound

        # Check that non-bird sounds are filtered (case-insensitive)
        assert not is_bird_sound("Human whistle")
        assert not is_bird_sound("human whistle")
        assert not is_bird_sound("SIREN")
        assert not is_bird_sound("Engine")
        assert not is_bird_sound("Dog")

        # Check that bird sounds pass through
        assert is_bird_sound("American Crow")
        assert is_bird_sound("House Sparrow")

        # Verify the underlying set is lowercase
        for item in NON_BIRD_SOUNDS:
            assert item == item.lower(), f"NON_BIRD_SOUNDS should be lowercase: {item}"

    def test_set_mqtt_client(self):
        """Test MQTT client reference setter."""
        from orpheus_ui.api.diagnostics import set_mqtt_client

        mock_client = MagicMock()
        set_mqtt_client(mock_client)

        # Module-level variable should be updated
        from orpheus_ui.api import diagnostics

        assert diagnostics._mqtt_client == mock_client

    def test_bus_diagnostics_reports_unapplied_subscriptions(self):
        """A connected bus with pending subscriptions is a UI that looks live and
        is serving stale data — the endpoint has to say so."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.auth.models import User

        bus = MagicMock()
        bus.dispatch_stats.return_value = {"queue_depth": 0, "dropped": 0}
        bus.subscription_status.return_value = {
            "connected": True,
            "subscribed": ["orpheus.detection.crow.events"],
            "pending": ["orpheus.system.audio.health"],
            "requested": 2,
        }
        previous = diagnostics._mqtt_client
        diagnostics.set_mqtt_client(bus)
        try:
            out = diagnostics.get_bus_diagnostics(user=MagicMock(spec=User))
        finally:
            diagnostics.set_mqtt_client(previous)
        assert out["available"] is True
        assert out["dropped"] == 0  # dispatch stats unchanged
        assert out["subscriptions"]["pending"] == ["orpheus.system.audio.health"]

    def test_bus_diagnostics_survives_a_bus_without_subscription_status(self):
        """The mqtt backend has no subscription_status; the endpoint keeps
        serving dispatch stats rather than 500ing."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.auth.models import User

        bus = MagicMock(spec=["dispatch_stats"])
        bus.dispatch_stats.return_value = {"queue_depth": 1, "dropped": 2}
        previous = diagnostics._mqtt_client
        diagnostics.set_mqtt_client(bus)
        try:
            out = diagnostics.get_bus_diagnostics(user=MagicMock(spec=User))
        finally:
            diagnostics.set_mqtt_client(previous)
        assert out == {"available": True, "queue_depth": 1, "dropped": 2}

    def test_audio_health_message_handler(self):
        """Test audio health message handler."""
        from orpheus_ui.api.diagnostics import on_audio_health_message

        payload = {
            "running": True,
            "channels": [{"id": "1", "active": True}],
            "xrun": {"total": 0},
        }

        on_audio_health_message("orpheus/system/audio/health", payload)

        from orpheus_ui.api import diagnostics

        assert diagnostics._audio_health_cache == payload

    def test_video_health_message_handler(self):
        """Test video health message handler."""
        from orpheus_ui.api.diagnostics import on_video_health_message

        payload = {
            "running": True,
            "cameras": [{"id": "orpheus-eye-1", "active": True}],
        }

        on_video_health_message("orpheus/system/video/health", payload)

        from orpheus_ui.api import diagnostics

        assert diagnostics._video_health_cache == payload

    def test_audio_detection_message_handler(self):
        """Test audio detection message handler with nested metadata payload."""
        from orpheus_ui.api.diagnostics import (
            on_audio_detection_message,
        )

        payload = {
            "event_id": "abc-123",
            "timestamp": "2025-01-01T12:00:00Z",
            "detection_type": "audio.motion",
            "channel": 1,
            "audio_clip_path": "/data/orpheus/audio/audio_motion/1/20250101T120000.flac",
            "context": {"lat": 47.0, "lon": -122.0, "sensor_id": "mic-1"},
            "metadata": {
                "channel_id": "1",
                "duration_seconds": 2.5,
                "peak_energy_db": -15.0,
                "average_energy_db": -30.0,
                "frame_count": 50,
            },
        }

        on_audio_detection_message("orpheus/audio/motion/events", payload)

        from orpheus_ui.api import diagnostics

        assert len(diagnostics._audio_detections_cache) >= 1
        assert "1" in diagnostics._audio_detections_by_channel

        # Verify flattening: top-level fields should be populated from metadata
        cached = diagnostics._audio_detections_by_channel["1"]
        assert cached["channel_id"] == "1"
        assert cached["duration_seconds"] == 2.5
        assert cached["peak_energy_db"] == -15.0

    def test_video_detection_message_handler(self):
        """Test video detection message handler."""
        from orpheus_ui.api.diagnostics import on_video_detection_message

        payload = {
            "camera_id": "orpheus-eye-1",
            "duration_seconds": 5.0,
            "peak_motion_value": 25.0,
            "timestamp": "2025-01-01T12:00:00Z",
        }

        on_video_detection_message("orpheus/video/motion/events", payload)

        from orpheus_ui.api import diagnostics

        assert len(diagnostics._video_detections_cache) >= 1
        assert "orpheus-eye-1" in diagnostics._video_detections_by_camera

    def test_bird_detection_message_handler(self):
        """Test bird detection message handler."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import on_bird_detection_message

        payload = {
            "channel_id": "2",
            "species_code": "amecro",
            "confidence": 0.85,
            "timestamp": "2025-01-01T12:00:00Z",
        }

        on_bird_detection_message("orpheus/bird/detection", payload)

        assert len(diagnostics._bird_detections_cache) >= 1
        assert "2" in diagnostics._bird_detections_by_channel

    def test_crow_detection_message_handler(self):
        """Test crow detection message handler."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import on_crow_detection_message

        payload = {
            "channel_id": "3",
            "age": "adult",
            "confidence": 0.92,
            "timestamp": "2025-01-01T12:00:00Z",
        }

        on_crow_detection_message("orpheus/crow/detection", payload)

        assert len(diagnostics._crow_detections_cache) >= 1
        assert "3" in diagnostics._crow_detections_by_channel

    def test_get_audio_diagnostics_no_cache(self):
        """Test audio diagnostics with empty cache."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import get_audio_diagnostics
        from orpheus_ui.auth.models import User

        # Clear the cache
        diagnostics._audio_health_cache = None

        mock_user = MagicMock(spec=User)
        result = get_audio_diagnostics(user=mock_user)

        assert result["running"] is False
        assert "Waiting for audio health data" in result["message"]

    def test_get_audio_diagnostics_with_cache(self):
        """Test audio diagnostics with cached data and channel transform."""
        from orpheus_ui.api.diagnostics import get_audio_diagnostics, on_audio_health_message
        from orpheus_ui.auth.models import User

        # Populate the cache with real health payload format (channel_id/has_signal)
        cached_data = {
            "running": True,
            "channels": [{"channel_id": "1", "has_signal": True, "level_db": -30.0}],
            "xrun": {"total": 5},
        }
        on_audio_health_message("test", cached_data)

        mock_user = MagicMock(spec=User)
        result = get_audio_diagnostics(user=mock_user)

        assert result["running"] is True
        assert result["xrun"]["total"] == 5
        # Verify channel transform: channel_id→id, has_signal→active
        assert len(result["channels"]) == 1
        assert result["channels"][0]["id"] == "1"
        assert result["channels"][0]["active"] is True

    def test_get_video_diagnostics_no_cache(self):
        """Test video diagnostics with empty cache."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import get_video_diagnostics
        from orpheus_ui.auth.models import User

        # Clear the cache
        diagnostics._video_health_cache = None
        diagnostics._video_detections_by_camera.clear()

        mock_user = MagicMock(spec=User)
        result = get_video_diagnostics(user=mock_user)

        assert result["running"] is False
        assert result["camera_count"] == 0

    def test_get_video_diagnostics_with_detections(self):
        """Test video diagnostics infers status from detections."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import get_video_diagnostics, on_video_detection_message
        from orpheus_ui.auth.models import User

        # Clear video health cache but add detection
        diagnostics._video_health_cache = None
        on_video_detection_message(
            "test",
            {
                "camera_id": "orpheus-eye-1",
                "timestamp": "2025-01-01T12:00:00Z",
            },
        )

        mock_user = MagicMock(spec=User)
        result = get_video_diagnostics(user=mock_user)

        assert result["running"] is True
        assert result["camera_count"] >= 1

    def test_get_audio_detections(self):
        """Test audio detections endpoint with nested metadata payload."""
        from orpheus_ui.api.diagnostics import get_audio_detections, on_audio_detection_message
        from orpheus_ui.auth.models import User

        on_audio_detection_message(
            "test",
            {
                "timestamp": "2025-01-01T12:00:00Z",
                "channel": 1,
                "metadata": {"channel_id": "1", "duration_seconds": 5.0, "peak_energy_db": -20.0},
            },
        )

        mock_user = MagicMock(spec=User)
        result = get_audio_detections(user=mock_user)

        assert "summary" in result
        assert "history" in result
        assert "mqtt_connected" in result
        # Verify the flattened channel_id is used for summary keying
        assert result["summary"]["1"] is not None
        assert result["summary"]["1"]["channel_id"] == "1"
        assert result["summary"]["1"]["duration_seconds"] == 5.0

    def test_get_video_detections(self):
        """Test video detections endpoint."""
        from orpheus_ui.api.diagnostics import get_video_detections, on_video_detection_message
        from orpheus_ui.auth.models import User

        on_video_detection_message(
            "test", {"camera_id": "orpheus-eye-1", "timestamp": "2025-01-01T12:00:00Z"}
        )

        mock_user = MagicMock(spec=User)
        result = get_video_detections(user=mock_user)

        assert "summary" in result
        assert "history" in result
        assert "orpheus-eye-1" in result["summary"]

    def test_get_bird_detections(self):
        """Test bird detections endpoint."""
        from orpheus_ui.api.diagnostics import get_bird_detections, on_bird_detection_message
        from orpheus_ui.auth.models import User

        on_bird_detection_message(
            "test",
            {
                "channel_id": "1",
                "audio_clip_path": "/path/to/clip.flac",
                "timestamp": "2025-01-01T12:00:00Z",
            },
        )

        mock_user = MagicMock(spec=User)
        result = get_bird_detections(user=mock_user)

        assert "summary" in result
        assert "history" in result
        # Verify audio_clip_path is aliased to clip_path
        assert any("clip_path" in h for h in result["history"])

    def test_get_crow_detections(self):
        """Test crow detections endpoint."""
        from orpheus_ui.api.diagnostics import get_crow_detections, on_crow_detection_message
        from orpheus_ui.auth.models import User

        on_crow_detection_message("test", {"channel_id": "1", "timestamp": "2025-01-01T12:00:00Z"})

        mock_user = MagicMock(spec=User)
        result = get_crow_detections(user=mock_user)

        assert "summary" in result
        assert "history" in result

    def test_get_audio_clip_invalid_channel(self):
        """Test audio clip endpoint with invalid channel."""
        from fastapi import HTTPException

        from orpheus_ui.api.diagnostics import get_audio_clip
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with pytest.raises(HTTPException) as exc_info:
            get_audio_clip(channel_id="invalid", filename="test.flac", user=mock_user)

        assert exc_info.value.status_code == 400
        assert "Invalid channel ID" in str(exc_info.value.detail)

    def test_get_audio_clip_path_traversal(self):
        """Test audio clip endpoint blocks path traversal."""
        from fastapi import HTTPException

        from orpheus_ui.api.diagnostics import get_audio_clip
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with pytest.raises(HTTPException) as exc_info:
            get_audio_clip(channel_id="1", filename="../../../etc/passwd", user=mock_user)

        assert exc_info.value.status_code in [400, 404]

    def test_get_video_clip_invalid_camera(self):
        """Test video clip endpoint with invalid camera."""
        from fastapi import HTTPException

        from orpheus_ui.api.diagnostics import get_video_clip
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with pytest.raises(HTTPException) as exc_info:
            get_video_clip(camera_id="invalid-camera", filename="test.mp4", user=mock_user)

        assert exc_info.value.status_code == 400
        assert "Invalid camera ID" in str(exc_info.value.detail)

    def test_get_video_clips_nonexistent_camera(self):
        """Test video clips list for camera with no clips directory."""
        from orpheus_ui.api.diagnostics import get_video_clips
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch("orpheus_ui.api.diagnostics.get_video_path") as mock_path:
            mock_path.return_value = MagicMock()
            mock_path.return_value.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)

            result = get_video_clips(camera_id="orpheus-eye-1", user=mock_user)
            assert result["clips"] == []
            assert result["error"] is None

    def test_get_video_diagnostics_with_cache(self):
        """Test video diagnostics returns cached data when available."""
        from orpheus_ui.api.diagnostics import get_video_diagnostics, on_video_health_message
        from orpheus_ui.auth.models import User

        # Populate video health cache
        cached_data = {
            "running": True,
            "cameras": [{"id": "orpheus-eye-1", "active": True}],
            "camera_count": 1,
        }
        on_video_health_message("test", cached_data)

        mock_user = MagicMock(spec=User)
        result = get_video_diagnostics(user=mock_user)

        # Should return cached data
        assert result["running"] is True
        assert result["cameras"] == [{"id": "orpheus-eye-1", "active": True}]

    def test_get_audio_diagnostics_exception(self):
        """Test audio diagnostics handles exceptions gracefully."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import get_audio_diagnostics
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        # Simulate exception by mocking the lock to raise
        original_lock = diagnostics._audio_health_lock
        diagnostics._audio_health_lock = MagicMock()
        diagnostics._audio_health_lock.__enter__ = MagicMock(side_effect=RuntimeError("Lock error"))

        try:
            result = get_audio_diagnostics(user=mock_user)
            assert result["running"] is False
            assert "error" in result
        finally:
            diagnostics._audio_health_lock = original_lock

    def test_get_video_diagnostics_exception(self):
        """Test video diagnostics handles exceptions gracefully."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import get_video_diagnostics
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        # Simulate exception by mocking the lock to raise
        original_lock = diagnostics._video_health_lock
        diagnostics._video_health_lock = MagicMock()
        diagnostics._video_health_lock.__enter__ = MagicMock(side_effect=RuntimeError("Lock error"))

        try:
            result = get_video_diagnostics(user=mock_user)
            assert result["running"] is False
            assert "error" in result
        finally:
            diagnostics._video_health_lock = original_lock

    def test_get_audio_detections_exception(self):
        """Test audio detections handles exceptions gracefully."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import get_audio_detections
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        # Simulate exception
        original_lock = diagnostics._audio_detections_lock
        diagnostics._audio_detections_lock = MagicMock()
        diagnostics._audio_detections_lock.__enter__ = MagicMock(
            side_effect=RuntimeError("Lock error")
        )

        try:
            result = get_audio_detections(user=mock_user)
            assert "error" in result
        finally:
            diagnostics._audio_detections_lock = original_lock

    def test_get_video_detections_exception(self):
        """Test video detections handles exceptions gracefully."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import get_video_detections
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        # Simulate exception
        original_lock = diagnostics._video_detections_lock
        diagnostics._video_detections_lock = MagicMock()
        diagnostics._video_detections_lock.__enter__ = MagicMock(
            side_effect=RuntimeError("Lock error")
        )

        try:
            result = get_video_detections(user=mock_user)
            assert "error" in result
        finally:
            diagnostics._video_detections_lock = original_lock

    def test_get_bird_detections_exception(self):
        """Test bird detections handles exceptions gracefully."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import get_bird_detections
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        # Simulate exception
        original_lock = diagnostics._bird_detections_lock
        diagnostics._bird_detections_lock = MagicMock()
        diagnostics._bird_detections_lock.__enter__ = MagicMock(
            side_effect=RuntimeError("Lock error")
        )

        try:
            result = get_bird_detections(user=mock_user)
            assert "error" in result
        finally:
            diagnostics._bird_detections_lock = original_lock

    def test_get_crow_detections_exception(self):
        """Test crow detections handles exceptions gracefully."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import get_crow_detections
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        # Simulate exception
        original_lock = diagnostics._crow_detections_lock
        diagnostics._crow_detections_lock = MagicMock()
        diagnostics._crow_detections_lock.__enter__ = MagicMock(
            side_effect=RuntimeError("Lock error")
        )

        try:
            result = get_crow_detections(user=mock_user)
            assert "error" in result
        finally:
            diagnostics._crow_detections_lock = original_lock

    def test_get_available_sounds(self):
        """Test get available sounds endpoint."""
        from orpheus_ui.api.diagnostics import get_available_sounds
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch("orpheus_common.audio.get_sound_registry") as mock_registry:
            mock_reg_instance = MagicMock()
            mock_reg_instance.list_sounds.return_value = ["sound1", "sound2", "crow_call"]
            mock_registry.return_value = mock_reg_instance

            result = get_available_sounds(user=mock_user)

            assert "sounds" in result
            assert len(result["sounds"]) == 3
            assert result["count"] == 3

    def test_get_available_sounds_error(self):
        """Test get available sounds handles errors."""
        from fastapi import HTTPException

        from orpheus_ui.api.diagnostics import get_available_sounds
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch("orpheus_common.audio.get_sound_registry") as mock_registry:
            mock_registry.side_effect = Exception("Registry unavailable")

            with pytest.raises(HTTPException) as exc_info:
                get_available_sounds(user=mock_user)

            assert exc_info.value.status_code == 500

    def test_play_sound_no_mqtt(self):
        """Test play sound fails when MQTT not connected."""
        from fastapi import HTTPException

        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import PlaybackRequest, play_sound
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        original_client = diagnostics._mqtt_client
        diagnostics._mqtt_client = None

        try:
            request = PlaybackRequest(sound_name="test_sound")
            with pytest.raises(HTTPException) as exc_info:
                play_sound(request=request, user=mock_user)

            assert exc_info.value.status_code == 503
        finally:
            diagnostics._mqtt_client = original_client

    def test_play_sound_success(self):
        """Test play sound sends MQTT message."""
        from orpheus_ui.api import diagnostics
        from orpheus_ui.api.diagnostics import PlaybackRequest, play_sound
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        mock_client = MagicMock()
        original_client = diagnostics._mqtt_client
        diagnostics._mqtt_client = mock_client

        try:
            request = PlaybackRequest(sound_name="crow_call", repeat_count=2, pause_between=1.0)
            result = play_sound(request=request, user=mock_user)

            assert result.success is True
            assert "crow_call" in result.message
            mock_client.publish.assert_called_once()
        finally:
            diagnostics._mqtt_client = original_client

    def test_play_sound_invalid_params(self):
        """Test play sound validates parameters via Pydantic."""
        from pydantic import ValidationError

        from orpheus_ui.api.diagnostics import PlaybackRequest

        # Test invalid repeat_count (less than 1)
        with pytest.raises(ValidationError):
            PlaybackRequest(sound_name="test", repeat_count=0)

        # Test invalid pause_between (negative)
        with pytest.raises(ValidationError):
            PlaybackRequest(sound_name="test", pause_between=-1.0)

        # Test repeat_count too high
        with pytest.raises(ValidationError):
            PlaybackRequest(sound_name="test", repeat_count=100)

    # ------------------------------------------------------------------
    # Tests for GET /api/diagnostics/logs/{service_name}
    # ------------------------------------------------------------------

    def test_get_service_logs_success(self):
        """Test service logs endpoint returns journalctl output as line array."""
        from orpheus_ui.api.diagnostics import get_service_logs
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        mock_result = MagicMock()
        mock_result.stdout = (
            "Mar 21 10:00:01 host svc[1]: started\nMar 21 10:00:02 host svc[1]: ready\n"
        )

        with (
            patch("subprocess.run", return_value=mock_result) as mock_run,
            patch("orpheus_ui.api.diagnostics.shutil") as mock_shutil,
        ):
            mock_shutil.which.side_effect = lambda cmd: "/usr/bin/" + cmd
            result = get_service_logs(service_name="orpheus-agent-audio-motion", user=mock_user)

        assert result["service_name"] == "orpheus-agent-audio-motion"
        assert isinstance(result["lines"], list)
        assert len(result["lines"]) == 2
        assert "started" in result["lines"][0]
        expected_cmd = [
            "/usr/bin/sudo",
            "-n",
            "/usr/bin/journalctl",
            "-u",
            "orpheus-agent-audio-motion",
            "-n",
            "100",
            "--no-pager",
        ]
        mock_run.assert_called_once_with(
            expected_cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_get_service_logs_invalid_service_name(self):
        """Test service logs endpoint rejects names with shell-injection characters."""
        from fastapi import HTTPException

        from orpheus_ui.api.diagnostics import get_service_logs
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        for bad_name in ["svc; rm -rf /", "svc && evil", "svc|cat /etc/passwd", "svc$(id)"]:
            with pytest.raises(HTTPException) as exc_info:
                get_service_logs(service_name=bad_name, user=mock_user)
            assert exc_info.value.status_code == 400
            assert "Invalid service name" in exc_info.value.detail

    def test_get_service_logs_journalctl_not_found(self):
        """Test service logs endpoint handles missing journalctl gracefully."""
        from orpheus_ui.api.diagnostics import get_service_logs
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = get_service_logs(service_name="orpheus-backplane", user=mock_user)

        assert result["service_name"] == "orpheus-backplane"
        assert isinstance(result["lines"], list)
        assert len(result["lines"]) == 1
        assert "not available" in result["lines"][0]

    def test_get_service_logs_timeout(self):
        """Test service logs endpoint returns 504 on journalctl timeout."""
        import subprocess

        from fastapi import HTTPException

        from orpheus_ui.api.diagnostics import get_service_logs
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(["journalctl"], 10),
        ):
            with pytest.raises(HTTPException) as exc_info:
                get_service_logs(service_name="orpheus-backplane", user=mock_user)

        assert exc_info.value.status_code == 504

    def test_get_service_logs_empty_output(self):
        """Test service logs endpoint handles empty journalctl output."""
        from orpheus_ui.api.diagnostics import get_service_logs
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        mock_result = MagicMock()
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = get_service_logs(service_name="orpheus-backplane", user=mock_user)

        assert result["lines"] == []

    def test_get_audio_diagnostics_includes_channel_levels(self):
        """Test audio diagnostics includes level_db, peak_db, level_color fields."""
        from orpheus_ui.api.diagnostics import get_audio_diagnostics, on_audio_health_message
        from orpheus_ui.auth.models import User

        # Populate cache with full channel payload from audio agent
        on_audio_health_message(
            "test",
            {
                "running": True,
                "channels": [
                    {
                        "channel_id": "1",
                        "has_signal": True,
                        "level_db": -25.5,
                        "peak_db": -20.0,
                        "level_color": "green",
                    }
                ],
                "xrun": {"total": 0},
            },
        )

        mock_user = MagicMock(spec=User)
        result = get_audio_diagnostics(user=mock_user)

        assert result["running"] is True
        ch = result["channels"][0]
        assert ch["id"] == "1"
        assert ch["active"] is True
        assert ch["level_db"] == -25.5
        assert ch["peak_db"] == -20.0
        assert ch["level_color"] == "green"
        assert ch["has_signal"] is True

    @patch("orpheus_ui.api.diagnostics.get_detection_db")
    def test_crow_scatter_spans_full_date_range(self, mock_db_class):
        """scatter_sample spans the full date range, not just the 2000-row table slice.

        Regression test: the scatter was previously built from the truncated
        detection_list (2000 most recent rows), so old detections were invisible
        in the scatter chart even though they appeared in the stats totals.
        """
        from datetime import datetime, timezone

        from orpheus_ui.api.diagnostics import get_crow_stats
        from orpheus_ui.auth.models import User

        def make_det(ts_iso):
            ts = datetime.fromisoformat(ts_iso).replace(tzinfo=timezone.utc)
            # Raw row-dict double for query_rows (row[key] / key in row.keys()).
            return {
                "timestamp": ts.isoformat(),
                "confidence": 0.8,
                "channel": 1,
                "metadata": None,
                "event_metadata": None,
                "audio_clip_path": None,
            }

        # 1500 old detections + 1000 recent = 2500 total.
        # After truncation the table slice keeps the 1000 recent + 500 old,
        # but scatter must still span BOTH days.
        old = [make_det("2026-03-08T10:00:00+00:00") for _ in range(1500)]
        recent = [make_det("2026-03-15T10:00:00+00:00") for _ in range(1000)]
        mock_db_class.return_value.query_rows.return_value = old + recent

        mock_user = MagicMock(spec=User)
        result = get_crow_stats(start_date="2026-03-08", end_date="2026-03-15", user=mock_user)

        scatter_dates = {s["timestamp"][:10] for s in result["scatter_sample"]}
        assert "2026-03-08" in scatter_dates, "scatter_sample must include old detections"
        assert "2026-03-15" in scatter_dates, "scatter_sample must include recent detections"


class TestCamerasAPI:
    """Tests for cameras API endpoints."""

    def test_cameras_router_exists(self):
        """Test cameras router is configured."""
        from orpheus_ui.api.cameras import router

        assert router is not None
        assert router.prefix == "/api"
        assert "cameras" in router.tags

    def test_get_cameras(self):
        """Test get cameras endpoint."""
        from orpheus_ui.api.cameras import get_cameras
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        mock_config = MagicMock()

        mock_camera = MagicMock()
        mock_camera.get_health_status.return_value = {
            "name": "orpheus-eye-1",
            "status": "ok",
            "last_snapshot": "2025-01-01T12:00:00Z",
        }
        mock_config.camera_registry.return_value = [mock_camera]
        mock_config.dashboard_poll_interval.return_value = 5000

        with patch("orpheus_ui.api.cameras.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_cameras(user=mock_user)

            assert len(result) == 1
            assert result[0]["name"] == "orpheus-eye-1"

    def test_get_camera_snapshot_not_found(self):
        """Test camera snapshot endpoint with unknown camera."""
        from fastapi import HTTPException

        from orpheus_ui.api.cameras import get_camera_snapshot
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        mock_config = MagicMock()
        mock_config.camera_registry.return_value = []

        with patch("orpheus_ui.api.cameras.OrpheusConfig.get_instance", return_value=mock_config):
            with pytest.raises(HTTPException) as exc_info:
                get_camera_snapshot(camera_name="unknown", user=mock_user)

            assert exc_info.value.status_code == 404
            assert "Camera not found" in str(exc_info.value.detail)

    def test_get_camera_snapshot_unavailable(self):
        """Test camera snapshot endpoint when snapshot fails."""
        from fastapi import HTTPException

        from orpheus_ui.api.cameras import get_camera_snapshot
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        mock_config = MagicMock()

        mock_camera = MagicMock()
        mock_camera.name = "orpheus-eye-1"
        mock_camera.capture_snapshot.return_value = {
            "ok": False,
            "error": "Camera offline",
        }
        mock_config.camera_registry.return_value = [mock_camera]

        with patch("orpheus_ui.api.cameras.OrpheusConfig.get_instance", return_value=mock_config):
            with pytest.raises(HTTPException) as exc_info:
                get_camera_snapshot(camera_name="orpheus-eye-1", user=mock_user)

            assert exc_info.value.status_code == 503

    def test_get_camera_snapshot_success(self):
        """Test camera snapshot endpoint returns image."""
        from orpheus_ui.api.cameras import get_camera_snapshot
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        mock_config = MagicMock()

        mock_camera = MagicMock()
        mock_camera.name = "orpheus-eye-1"
        mock_camera.capture_snapshot.return_value = {
            "ok": True,
            "image_data": b"fake-jpeg-data",
            "cached_at": "2025-01-01T12:00:00Z",
        }
        mock_config.camera_registry.return_value = [mock_camera]

        with patch("orpheus_ui.api.cameras.OrpheusConfig.get_instance", return_value=mock_config):
            result = get_camera_snapshot(camera_name="orpheus-eye-1", user=mock_user)

            assert result.body == b"fake-jpeg-data"
            assert result.media_type == "image/jpeg"


class TestEntitiesAPI:
    """Tests for entities API endpoints.

    The entities API reads from SQLite via DetectionDB.  Tests mock the
    ``_get_db`` helper so no real database is needed.
    """

    def _make_entity(
        self,
        entity_id,
        species="amcr",
        common_name="American Crow",
        confidence=0.92,
        evidence=None,
        context=None,
    ):
        """Helper to build an Entity object for test assertions."""
        from datetime import datetime, timezone

        from orpheus_common.detection import Entity, EntityEvidence

        ev_list = []
        for ev in evidence or []:
            ev_list.append(EntityEvidence(**ev))

        return Entity(
            entity_id=entity_id,
            timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            species=species,
            common_name=common_name,
            confidence=confidence,
            evidence=ev_list,
            context=context,
        )

    def test_entity_event_message_handler_is_noop(self):
        """on_entity_event_message is a no-op (entities are persisted by the correlator)."""
        from orpheus_ui.api.entities import on_entity_event_message

        # Should not raise — the callback is intentionally a no-op
        on_entity_event_message("orpheus/entities/animal", {"entity_id": "x"})

    @patch("orpheus_ui.api.entities._get_db")
    def test_get_entities_endpoint(self, mock_get_db):
        """Test GET /api/entities returns entities from DB."""
        from orpheus_ui.api.entities import get_entities
        from orpheus_ui.auth.models import User

        sample_entities = [self._make_entity(f"entity-{i}") for i in range(3)]
        mock_get_db.return_value.get_entities.return_value = sample_entities

        mock_user = MagicMock(spec=User)
        result = get_entities(
            species=None,
            exclude_species=None,
            start_date=None,
            end_date=None,
            limit=100,
            user=mock_user,
        )

        assert result["count"] == 3
        assert len(result["entities"]) == 3

    @patch("orpheus_ui.api.entities._get_db")
    def test_pagination_returns_only_page_slice(self, mock_get_db):
        """Server-side pagination: page=1, page_size=10 returns 10 of 50
        rows + correct total_pages."""
        from orpheus_ui.api.entities import get_entities
        from orpheus_ui.auth.models import User

        sample_entities = [self._make_entity(f"entity-{i:03d}") for i in range(50)]
        mock_get_db.return_value.get_entities.return_value = sample_entities

        mock_user = MagicMock(spec=User)
        result = get_entities(
            species=None,
            exclude_species=None,
            start_date=None,
            end_date=None,
            page=1,
            page_size=10,
            user=mock_user,
        )

        # ``count`` is the full filtered total, not the page slice length.
        assert result["count"] == 50
        assert len(result["entities"]) == 10
        assert result["page"] == 1
        assert result["page_size"] == 10
        assert result["total_pages"] == 5

    @patch("orpheus_ui.api.entities._get_db")
    def test_pagination_page_two_offsets_correctly(self, mock_get_db):
        """Page 2 returns the second batch, not the first."""
        from orpheus_ui.api.entities import get_entities
        from orpheus_ui.auth.models import User

        sample_entities = [self._make_entity(f"entity-{i:03d}") for i in range(50)]
        mock_get_db.return_value.get_entities.return_value = sample_entities

        mock_user = MagicMock(spec=User)
        result = get_entities(
            species=None,
            exclude_species=None,
            start_date=None,
            end_date=None,
            page=2,
            page_size=10,
            user=mock_user,
        )

        assert result["page"] == 2
        # Second page = rows 10-19.
        assert len(result["entities"]) == 10
        assert result["entities"][0]["entity_id"] == "entity-010"
        assert result["entities"][9]["entity_id"] == "entity-019"

    @patch("orpheus_ui.api.entities._get_db")
    def test_pagination_bypasses_legacy_2000_cap(self, mock_get_db):
        """The pagination path must NOT cap at 2000 — that's the bug
        this is fixing."""
        from orpheus_ui.api.entities import get_entities
        from orpheus_ui.auth.models import User

        # 3000 entities — beyond the legacy 2000 cap.
        sample_entities = [self._make_entity(f"entity-{i:04d}") for i in range(3000)]
        mock_get_db.return_value.get_entities.return_value = sample_entities

        mock_user = MagicMock(spec=User)
        result = get_entities(
            species=None,
            exclude_species=None,
            start_date=None,
            end_date=None,
            page=30,  # rows 2900-2999
            page_size=100,
            user=mock_user,
        )

        # The full 3000 are counted, total_pages reflects them.
        assert result["count"] == 3000
        assert result["total_pages"] == 30
        # Page 30 has the last 100 rows.
        assert result["entities"][0]["entity_id"] == "entity-2900"
        assert result["entities"][-1]["entity_id"] == "entity-2999"

    @patch("orpheus_ui.api.entities._get_db")
    def test_get_entities_empty(self, mock_get_db):
        """Test GET /api/entities returns empty when no entities in DB."""
        from orpheus_ui.api.entities import get_entities
        from orpheus_ui.auth.models import User

        mock_get_db.return_value.get_entities.return_value = []

        mock_user = MagicMock(spec=User)
        result = get_entities(
            species=None,
            exclude_species=None,
            start_date=None,
            end_date=None,
            limit=100,
            user=mock_user,
        )

        assert result["count"] == 0
        assert result["entities"] == []

    @patch("orpheus_ui.api.entities._get_db")
    def test_get_entity_by_id(self, mock_get_db):
        """Test GET /api/entities/{entity_id} returns specific entity."""
        from orpheus_ui.api.entities import get_entity_by_id
        from orpheus_ui.auth.models import User

        target = self._make_entity(
            "lookup-entity",
            common_name="American Crow",
            confidence=0.85,
            context={"lat": 47.6, "lon": -122.3},
        )
        mock_get_db.return_value.get_entity_by_id.return_value = target

        mock_user = MagicMock(spec=User)
        result = get_entity_by_id(entity_id="lookup-entity", user=mock_user)

        assert result["entity_id"] == "lookup-entity"
        assert result["common_name"] == "American Crow"
        # Direct DB-level lookup, not a linear scan.
        mock_get_db.return_value.get_entity_by_id.assert_called_once_with(
            "lookup-entity"
        )

    @patch("orpheus_ui.api.entities._get_db")
    def test_get_entity_by_id_not_found(self, mock_get_db):
        """Test GET /api/entities/{entity_id} returns 404 for missing entity."""
        from orpheus_ui.api.entities import get_entity_by_id
        from orpheus_ui.auth.models import User

        mock_get_db.return_value.get_entity_by_id.return_value = None

        mock_user = MagicMock(spec=User)
        with pytest.raises(Exception) as exc_info:
            get_entity_by_id(entity_id="nonexistent", user=mock_user)

        assert "404" in str(exc_info.value.status_code)

    @patch("orpheus_ui.api.entities._get_db")
    def test_get_entity_by_id_finds_old_entity_outside_recent_window(
        self, mock_get_db
    ):
        """Regression: old code fetched limit=5000 recent entities and
        linear-scanned, returning 404 for any older entity even though
        it existed in the DB. The new direct-lookup path must find it."""
        from orpheus_ui.api.entities import get_entity_by_id
        from orpheus_ui.auth.models import User

        old = self._make_entity(
            "very-old-entity",
            common_name="American Robin",
        )
        # The new code path: db.get_entity_by_id directly returns the
        # target without scanning a recent-N window.
        mock_get_db.return_value.get_entity_by_id.return_value = old

        mock_user = MagicMock(spec=User)
        result = get_entity_by_id(entity_id="very-old-entity", user=mock_user)
        assert result["entity_id"] == "very-old-entity"
        # The old (buggy) implementation would have called get_entities
        # with limit=5000; the new one must NOT.
        mock_get_db.return_value.get_entities.assert_not_called()

    @patch("orpheus_ui.api.entities._get_db")
    @patch("orpheus_ui.api.entities._fetch_detection_metadata")
    def test_get_entities_with_metadata_enrichment(self, mock_fetch_metadata, mock_get_db):
        """Test that entities are enriched with metadata from detections."""
        from orpheus_ui.api.entities import get_entities
        from orpheus_ui.auth.models import User

        # Create entity with evidence
        sample_entity = self._make_entity(
            "entity-1",
            species="corvus",
            common_name="American Crow",
            evidence=[
                {"event_id": "det-1", "sensor_id": "mic-1", "confidence": 0.9},
                {"event_id": "det-2", "sensor_id": "mic-2", "confidence": 0.85},
            ],
        )
        mock_get_db.return_value.get_entities.return_value = [sample_entity]

        # Mock detection metadata
        mock_fetch_metadata.return_value = {
            "det-1": {
                "call_type": "alert",
                "attributes": {"age": "adult", "alert": 0.92, "begging": 0.01},
            },
            "det-2": {
                "call_type": "rattle",
                "attributes": {"age": "adult", "rattle": 0.88, "alert": 0.1},
            },
        }

        mock_user = MagicMock(spec=User)
        result = get_entities(
            species=None,
            exclude_species=None,
            start_date=None,
            end_date=None,
            limit=500,
            user=mock_user,
        )

        assert result["count"] == 1
        entity = result["entities"][0]

        # Verify metadata_aggregate is present
        assert "metadata_aggregate" in entity
        meta_agg = entity["metadata_aggregate"]

        # Verify aggregated data
        assert meta_agg["call_types"] == ["alert", "rattle"]
        assert meta_agg["ages"] == ["adult", "adult"]
        assert meta_agg["evidence_count"] == 2

        # Verify averaged behaviors
        assert "avg_behaviors" in meta_agg
        # alert: (0.92 + 0.1) / 2 = 0.51
        assert abs(meta_agg["avg_behaviors"]["alert"] - 0.51) < 0.01

    @patch("orpheus_ui.api.entities._get_db")
    @patch("orpheus_ui.api.entities._fetch_detection_metadata")
    def test_get_entities_handles_missing_metadata(self, mock_fetch_metadata, mock_get_db):
        """Test that entities handle missing detection metadata gracefully."""
        from orpheus_ui.api.entities import get_entities
        from orpheus_ui.auth.models import User

        sample_entity = self._make_entity(
            "entity-1",
            evidence=[
                {"event_id": "det-1", "sensor_id": "mic-1", "confidence": 0.9},
            ],
        )
        mock_get_db.return_value.get_entities.return_value = [sample_entity]

        # Return empty metadata
        mock_fetch_metadata.return_value = {}

        mock_user = MagicMock(spec=User)
        result = get_entities(
            species=None,
            exclude_species=None,
            start_date=None,
            end_date=None,
            limit=500,
            user=mock_user,
        )

        entity = result["entities"][0]
        meta_agg = entity["metadata_aggregate"]

        # Should have empty lists when no metadata found
        assert meta_agg["call_types"] == []
        assert meta_agg["ages"] == []
        assert meta_agg["avg_behaviors"] == {}

    def test_aggregate_evidence_metadata(self):
        """Test _aggregate_evidence_metadata helper function."""
        from orpheus_ui.api.entities import _aggregate_evidence_metadata

        # Create mock entity with evidence
        entity = self._make_entity(
            "entity-1",
            evidence=[
                {"event_id": "det-1", "sensor_id": "mic-1", "confidence": 0.9},
                {"event_id": "det-2", "sensor_id": "mic-2", "confidence": 0.8},
                {"event_id": "det-3", "sensor_id": "mic-3", "confidence": 0.75},
            ],
        )

        detection_metadata = {
            "det-1": {
                "call_type": "alert",
                "attributes": {"age": "adult", "alert": 1.0, "begging": 0.0, "rattle": 0.5},
            },
            "det-2": {
                "call_type": "alert",
                "attributes": {"age": "juvenile", "alert": 0.8, "begging": 0.2},
            },
            "det-3": {
                "call_type": "rattle",
                "attributes": {"age": "adult", "rattle": 0.9, "soft_song": 0.1},
            },
        }

        result = _aggregate_evidence_metadata(entity, detection_metadata)

        # Verify call types aggregation
        assert result["call_types"] == ["alert", "alert", "rattle"]

        # Verify age aggregation
        assert result["ages"] == ["adult", "juvenile", "adult"]

        # Verify behavior averaging
        # alert: (1.0 + 0.8) / 2 = 0.9
        assert abs(result["avg_behaviors"]["alert"] - 0.9) < 0.01
        # rattle: (0.5 + 0.9) / 2 = 0.7
        assert abs(result["avg_behaviors"]["rattle"] - 0.7) < 0.01
        # begging: (0.0 + 0.2) / 2 = 0.1
        assert abs(result["avg_behaviors"]["begging"] - 0.1) < 0.01

        # Verify evidence count
        assert result["evidence_count"] == 3

    @patch("orpheus_ui.api.entities._get_db")
    def test_get_entities_end_date_sets_to_end_of_day(self, mock_get_db):
        """Test that end_date is converted to end of day (23:59:59.999999)."""
        from orpheus_ui.api.entities import get_entities
        from orpheus_ui.auth.models import User

        mock_get_db.return_value.get_entities.return_value = []
        mock_user = MagicMock(spec=User)

        # Call with end_date parameter
        get_entities(
            species=None,
            exclude_species=None,
            start_date=None,
            end_date="2026-02-17T00:00:00Z",
            limit=500,
            user=mock_user,
        )

        # Verify get_entities was called with end_time set to end of day
        call_kwargs = mock_get_db.return_value.get_entities.call_args[1]
        assert "end_time" in call_kwargs
        end_time = call_kwargs["end_time"]

        # Should be 2026-02-17 but at 23:59:59.999999
        assert end_time.year == 2026
        assert end_time.month == 2
        assert end_time.day == 17
        assert end_time.hour == 23
        assert end_time.minute == 59
        assert end_time.second == 59
        assert end_time.microsecond == 999999

    @patch("orpheus_ui.api.entities._get_db")
    @patch("orpheus_ui.api.entities._fetch_detection_metadata")
    def test_get_entity_by_id_includes_metadata(self, mock_fetch_metadata, mock_get_db):
        """Test that get_entity_by_id enriches entity with metadata."""
        from orpheus_ui.api.entities import get_entity_by_id
        from orpheus_ui.auth.models import User

        target = self._make_entity(
            "entity-with-metadata",
            evidence=[
                {"event_id": "det-1", "sensor_id": "mic-1", "confidence": 0.9},
                {"event_id": "det-2", "sensor_id": "mic-2", "confidence": 0.85},
            ],
        )
        mock_get_db.return_value.get_entity_by_id.return_value = target

        # Mock detection metadata
        mock_fetch_metadata.return_value = {
            "det-1": {
                "call_type": "alert",
                "attributes": {"age": "adult", "alert": 0.9},
            },
            "det-2": {
                "call_type": "rattle",
                "attributes": {"age": "juvenile", "rattle": 0.8},
            },
        }

        mock_user = MagicMock(spec=User)
        result = get_entity_by_id(entity_id="entity-with-metadata", user=mock_user)

        # Verify metadata_aggregate is present
        assert "metadata_aggregate" in result
        meta_agg = result["metadata_aggregate"]

        assert meta_agg["call_types"] == ["alert", "rattle"]
        assert meta_agg["ages"] == ["adult", "juvenile"]
        assert meta_agg["evidence_count"] == 2

    def test_fetch_detection_metadata_empty_event_ids(self):
        """Test _fetch_detection_metadata handles empty event_ids gracefully."""
        from orpheus_ui.api.entities import _fetch_detection_metadata

        # Mock DB (won't be used since we return early)
        mock_db = MagicMock()

        result = _fetch_detection_metadata(mock_db, [])

        # Should return empty dict without querying database
        assert result == {}

    @patch("orpheus_ui.api.entities.open_connection")
    @patch("orpheus_ui.api.entities.sqlite3")
    def test_fetch_detection_metadata_handles_null_metadata(
        self, mock_sqlite3, mock_open_connection
    ):
        """Test _fetch_detection_metadata handles NULL metadata in database."""
        from orpheus_ui.api.entities import _fetch_detection_metadata

        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Simulate row with NULL metadata
        mock_row = {"event_id": "det-1", "metadata": None}
        mock_cursor.fetchall.return_value = [mock_row]
        mock_conn.cursor.return_value = mock_cursor
        # ``_fetch_detection_metadata`` now routes through
        # ``open_connection`` (project-standard pragmas) rather than a
        # raw sqlite3.connect, so the mock is on the helper.
        mock_open_connection.return_value = mock_conn
        mock_sqlite3.Row = dict  # For row_factory

        mock_db = MagicMock()
        mock_db.db_path = "/fake/path.db"

        result = _fetch_detection_metadata(mock_db, ["det-1"])

        # Should return empty dict for event with NULL metadata
        assert result == {"det-1": {}}

    @patch("orpheus_ui.api.entities.open_connection")
    @patch("orpheus_ui.api.entities.sqlite3")
    def test_fetch_detection_metadata_handles_malformed_json(
        self, mock_sqlite3, mock_open_connection
    ):
        """Test _fetch_detection_metadata handles malformed JSON gracefully."""
        from orpheus_ui.api.entities import _fetch_detection_metadata

        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Simulate row with malformed JSON
        mock_row = {"event_id": "det-1", "metadata": "{bad json}"}
        mock_cursor.fetchall.return_value = [mock_row]
        mock_conn.cursor.return_value = mock_cursor
        mock_open_connection.return_value = mock_conn
        mock_sqlite3.Row = dict

        mock_db = MagicMock()
        mock_db.db_path = "/fake/path.db"

        # Should raise an exception (json.loads will fail)
        with pytest.raises(Exception):
            _fetch_detection_metadata(mock_db, ["det-1"])

    def test_aggregate_evidence_metadata_non_dict_attributes(self):
        """Test _aggregate_evidence_metadata handles non-dict attributes."""
        from orpheus_ui.api.entities import _aggregate_evidence_metadata

        entity = self._make_entity(
            "entity-1",
            evidence=[
                {"event_id": "det-1", "sensor_id": "mic-1", "confidence": 0.9},
            ],
        )

        # Metadata with non-dict attributes
        detection_metadata = {
            "det-1": {
                "call_type": "alert",
                "attributes": "not-a-dict",  # Invalid type
            },
        }

        result = _aggregate_evidence_metadata(entity, detection_metadata)

        # Should handle gracefully - call_type extracted, but no ages/behaviors
        assert result["call_types"] == ["alert"]
        assert result["ages"] == []
        assert result["avg_behaviors"] == {}

    def test_aggregate_evidence_metadata_mixed_behavior_values(self):
        """Test _aggregate_evidence_metadata handles mixed valid/invalid behavior values."""
        from orpheus_ui.api.entities import _aggregate_evidence_metadata

        entity = self._make_entity(
            "entity-1",
            evidence=[
                {"event_id": "det-1", "sensor_id": "mic-1", "confidence": 0.9},
                {"event_id": "det-2", "sensor_id": "mic-2", "confidence": 0.8},
                {"event_id": "det-3", "sensor_id": "mic-3", "confidence": 0.7},
            ],
        )

        detection_metadata = {
            "det-1": {
                "attributes": {"alert": 0.9, "begging": "invalid"},  # Invalid begging value
            },
            "det-2": {
                "attributes": {"alert": 0.8, "begging": 0.5},  # Valid
            },
            "det-3": {
                "attributes": {"alert": None, "begging": 0.3},  # None should be skipped
            },
        }

        result = _aggregate_evidence_metadata(entity, detection_metadata)

        # alert: (0.9 + 0.8) / 2 = 0.85 (det-3's None is skipped)
        assert abs(result["avg_behaviors"]["alert"] - 0.85) < 0.01
        # begging: (0.5 + 0.3) / 2 = 0.4 (det-1's "invalid" is skipped)
        assert abs(result["avg_behaviors"]["begging"] - 0.4) < 0.01

    def test_aggregate_evidence_metadata_no_behaviors(self):
        """Test _aggregate_evidence_metadata when no behavior data exists."""
        from orpheus_ui.api.entities import _aggregate_evidence_metadata

        entity = self._make_entity(
            "entity-1",
            evidence=[
                {"event_id": "det-1", "sensor_id": "mic-1", "confidence": 0.9},
            ],
        )

        # Metadata with no behavior attributes
        detection_metadata = {
            "det-1": {
                "call_type": "alert",
                "attributes": {},  # Empty attributes
            },
        }

        result = _aggregate_evidence_metadata(entity, detection_metadata)

        assert result["call_types"] == ["alert"]
        assert result["avg_behaviors"] == {}  # No behaviors to average

    @patch("orpheus_ui.api.entities._compute_entity_stats")
    @patch("orpheus_ui.api.entities._get_db")
    def test_get_entities_scatter_comes_from_full_range(self, mock_get_db, mock_compute_stats):
        """scatter_sample in get_entities comes from _compute_entity_stats (full range).

        Regression test: the scatter was previously built from entity_dicts which
        is capped at 2000 most-recent rows, so older detections were absent from
        the chart even though the stats total included them.
        """
        from orpheus_ui.api.entities import get_entities
        from orpheus_ui.auth.models import User

        # entity_dicts has only today's entities (most-recent 2000 cap)
        mock_get_db.return_value.get_entities.return_value = [
            self._make_entity("e1"),
        ]

        # _compute_entity_stats returns a scatter spanning the full 7-day range
        full_range_scatter = [
            {
                "timestamp": "2026-03-08T10:00:00+00:00",
                "species_code": "turdus",
                "common_name": "Robin",
                "confidence": 0.9,
            },
            {
                "timestamp": "2026-03-15T10:00:00+00:00",
                "species_code": "parus",
                "common_name": "Chickadee",
                "confidence": 0.8,
            },
        ]
        mock_compute_stats.return_value = {
            "total_count": 5000,
            "unique_species_count": 10,
            "hourly_activity": [],
            "daily_activity": [],
            "species_distribution": {},
            "scatter_sample": full_range_scatter,
        }

        mock_user = MagicMock(spec=User)
        result = get_entities(
            species=None,
            exclude_species=None,
            start_date="2026-03-08",
            end_date="2026-03-15",
            limit=100,
            user=mock_user,
        )

        # scatter_sample must be the full-range sample from _compute_entity_stats
        assert result["scatter_sample"] == full_range_scatter
        scatter_dates = {s["timestamp"][:10] for s in result["scatter_sample"]}
        assert "2026-03-08" in scatter_dates
        assert "2026-03-15" in scatter_dates

        # _compute_entity_stats must have been called with species filter args
        mock_compute_stats.assert_called_once()
        call_kwargs = mock_compute_stats.call_args[1]
        assert call_kwargs.get("exclude_species") is None  # no filter in this call
        assert call_kwargs.get("species") is None


class TestEntitySpeciesFilterEquivalence:
    """The species filter on /api/entities uses the Layer 3 equivalence
    graph + per-evidence matching so a search for "Corvus brachyrhynchos"
    hits Entities where ONLY an evidence row has that taxonomy ref.

    Layer 2 makes Entity.species (the legacy display column) just a
    label from the highest-confidence observation. The authoritative
    species claim is in evidence[].taxonomy. The filter must respect
    that to be useful as the equivalence graph grows."""

    def test_legacy_species_column_still_matches(self) -> None:
        """Back-compat: a filter that matches Entity.species directly
        still works (no equivalence expansion needed)."""
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        from orpheus_common.detection import Entity

        from orpheus_ui.api.entities import (
            _entity_matches_species_filter,
            expand_species_filter,
        )

        legacy, taxa = expand_species_filter("corvus")
        assert "corvus" in legacy

        ent = Entity(
            entity_id="e1",
            timestamp=_dt.now(_tz.utc),
            species="corvus",
            evidence=[],
        )
        assert _entity_matches_species_filter(
            ent.species, ent.evidence, legacy, taxa
        ) is True

    def test_dropdown_common_name_filter_matches_entity(self) -> None:
        """REPRO: user-reported bug. The species-filter dropdown is
        populated from `_compute_all_species_in_range` which returns
        ``COALESCE(NULLIF(common_name,''), species)`` — so the dropdown
        shows ``"American Robin"`` (common name) not ``"amerob"``
        (slug). When the user clicks ``"American Robin"`` the frontend
        sends ``?species=American Robin``. The filter must match
        Entities whose common_name OR species_common is that string.

        Without this test the user can SEE robin entities in the
        unfiltered list but selecting "American Robin" from the
        dropdown returns zero. The Birds page works because its
        dropdown sends slugs (``amerob``) which match the Entity's
        ``species`` column directly.
        """
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        from orpheus_common.detection import Entity, EntityEvidence

        from orpheus_ui.api.entities import (
            _entity_matches_species_filter,
            expand_species_filter,
        )

        legacy, taxa = expand_species_filter("American Robin")
        assert "American Robin" in legacy

        # A typical Layer 2 Robin Entity: legacy display column is the
        # slug (highest-confidence observation's species_code) and
        # common_name is the human-readable form.
        ent = Entity(
            entity_id="e-dropdown-1",
            timestamp=_dt.now(_tz.utc),
            species="amerob",
            common_name="American Robin",
            evidence=[
                EntityEvidence(
                    event_id="ev-1",
                    sensor_id="mic-1",
                    confidence=0.85,
                    species_code="amerob",
                    species_common="American Robin",
                    detection_type="species.detected",
                ),
            ],
        )
        assert _entity_matches_species_filter(
            ent.species, ent.evidence, legacy, taxa
        ) is True, (
            "Filter built from dropdown common-name value 'American "
            "Robin' should match an Entity whose evidence species_common "
            "is 'American Robin'."
        )

    def test_dropdown_common_name_matches_when_evidence_lacks_species_common(
        self,
    ) -> None:
        """Pre-Layer-2 Entities (or partial-data rows) have evidence
        with ``species_common = None``. The filter must still match
        via the Entity's own ``common_name`` field, not just walk
        evidence."""
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        from orpheus_common.detection import Entity, EntityEvidence

        from orpheus_ui.api.entities import (
            _entity_matches_species_filter,
            expand_species_filter,
        )

        legacy, taxa = expand_species_filter("American Robin")

        # Legacy Entity row from before Layer 2 — evidence rows don't
        # carry per-evidence species_common. Filter must fall back to
        # the Entity's own common_name to match.
        ent = Entity(
            entity_id="e-legacy",
            timestamp=_dt.now(_tz.utc),
            species="amerob",
            common_name="American Robin",
            evidence=[
                EntityEvidence(
                    event_id="ev-legacy",
                    sensor_id="mic-1",
                    confidence=0.85,
                    # NB: no species_code, no species_common, no taxonomy
                ),
            ],
        )
        assert _entity_matches_species_filter(
            ent.species, ent.evidence, legacy, taxa,
            ent_common_name=ent.common_name,
        ) is True, (
            "Filter must consider Entity.common_name as a fallback "
            "when evidence rows don't carry per-evidence species names."
        )

    def test_evidence_only_match(self) -> None:
        """Entity.species is something else, but an evidence row has the
        searched species. Must still match — that's the whole point."""
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        from orpheus_common.detection import Entity, EntityEvidence

        from orpheus_ui.api.entities import (
            _entity_matches_species_filter,
            expand_species_filter,
        )

        legacy, taxa = expand_species_filter("amerob")
        ent = Entity(
            entity_id="e2",
            timestamp=_dt.now(_tz.utc),
            # Layer 2 legacy display: highest-confidence evidence was a crow.
            species="corvus",
            common_name="American Crow",
            evidence=[
                EntityEvidence(
                    event_id="ev-bird",
                    sensor_id="mic-1",
                    confidence=0.92,
                    species_code="corvus",
                    species_common="American Crow",
                    detection_type="species.detected",
                ),
                # But there was ALSO a robin in the same window.
                EntityEvidence(
                    event_id="ev-robin",
                    sensor_id="mic-1",
                    confidence=0.65,
                    species_code="amerob",
                    species_common="American Robin",
                    detection_type="species.detected",
                ),
            ],
        )
        assert _entity_matches_species_filter(
            ent.species, ent.evidence, legacy, taxa
        ) is True

    def test_taxonomy_namespace_id_pair_filter(self) -> None:
        """Passing a `namespace:id` filter (e.g. `audioset:/m/04s8yn`)
        matches evidence with that exact TaxonomyRef."""
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        from orpheus_common.detection import Entity, EntityEvidence, TaxonomyRef

        from orpheus_ui.api.entities import (
            _entity_matches_species_filter,
            expand_species_filter,
        )

        legacy, taxa = expand_species_filter("audioset:/m/04s8yn")
        # The pair appears in taxa (either directly or via equivalence expansion).
        assert ("audioset", "/m/04s8yn") in taxa

        ent = Entity(
            entity_id="e3",
            timestamp=_dt.now(_tz.utc),
            species="anything",
            evidence=[
                EntityEvidence(
                    event_id="ev1",
                    sensor_id="mic-1",
                    confidence=0.85,
                    species_code="audioset_/m/04s8yn",
                    species_common="Crow",
                    taxonomy=TaxonomyRef(namespace="audioset", id="/m/04s8yn"),
                    detection_type="audio.classified",
                ),
            ],
        )
        assert _entity_matches_species_filter(
            ent.species, ent.evidence, legacy, taxa
        ) is True

    def test_no_match_returns_false(self) -> None:
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        from orpheus_common.detection import Entity, EntityEvidence

        from orpheus_ui.api.entities import (
            _entity_matches_species_filter,
            expand_species_filter,
        )

        legacy, taxa = expand_species_filter("amerob")
        ent = Entity(
            entity_id="e4",
            timestamp=_dt.now(_tz.utc),
            species="corvus",
            common_name="American Crow",
            evidence=[
                EntityEvidence(
                    event_id="ev1",
                    sensor_id="mic-1",
                    confidence=0.92,
                    species_code="corvus",
                    species_common="American Crow",
                    detection_type="species.detected",
                ),
            ],
        )
        assert _entity_matches_species_filter(
            ent.species, ent.evidence, legacy, taxa
        ) is False

    def test_empty_filter_matches_everything(self) -> None:
        from orpheus_ui.api.entities import _entity_matches_species_filter

        # Empty filter sets → match all.
        assert _entity_matches_species_filter("anything", [], set(), set()) is True


class TestEquivalencesEndpoint:
    """Tests for /api/equivalences and the accept/reject mutators.

    These endpoints expose the Layer 3 equivalence graph to the UI so
    humans can see what auto-discovery has learned and approve / reject
    pending proposals."""

    def test_lists_accepted_and_pending(self, tmp_path):
        """Both accepted rows and pending_review rows appear in the
        respective buckets, deduplicated by canonical pair."""
        from orpheus_common.detection import TaxonomyEquivalenceDB, TaxonomyRef

        from orpheus_ui.api.entities import list_equivalences
        from orpheus_ui.auth.models import User

        eq_db = TaxonomyEquivalenceDB(db_path=tmp_path / "eq.db")
        eq_db.record_equivalence(
            TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos"),
            TaxonomyRef(namespace="audioset", id="/m/04s8yn"),
            confidence=1.0,
            source="auto_discovered",
            status="accepted",
        )
        eq_db.record_equivalence(
            TaxonomyRef(namespace="ioc", id="Turdus migratorius"),
            TaxonomyRef(namespace="audioset", id="/m/020bb7"),
            confidence=0.7,
            source="auto_discovered",
            status="pending_review",
        )

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.entities.TaxonomyEquivalenceDB", return_value=eq_db
        ):
            result = list_equivalences(user=mock_user)

        assert result["counts"]["accepted"] == 1
        assert result["counts"]["pending_review"] == 1
        assert result["counts"]["non_equivalences"] == 0
        assert len(result["accepted"]) == 1
        assert len(result["pending_review"]) == 1

    def test_lists_non_equivalences(self, tmp_path):
        from orpheus_common.detection import TaxonomyEquivalenceDB, TaxonomyRef

        from orpheus_ui.api.entities import list_equivalences
        from orpheus_ui.auth.models import User

        eq_db = TaxonomyEquivalenceDB(db_path=tmp_path / "eq.db")
        eq_db.record_non_equivalence(
            TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos"),
            TaxonomyRef(namespace="audioset", id="/m/0bt9lr"),  # Dog NOT a crow
            source="manual",
            notes="auto-discovery proposed this in error",
        )

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.entities.TaxonomyEquivalenceDB", return_value=eq_db
        ):
            result = list_equivalences(user=mock_user)

        assert result["counts"]["non_equivalences"] == 1
        assert (
            result["non_equivalences"][0]["notes"]
            == "auto-discovery proposed this in error"
        )

    def test_accept_promotes_pending(self, tmp_path):
        from orpheus_common.detection import TaxonomyEquivalenceDB, TaxonomyRef

        from orpheus_ui.api.entities import accept_equivalence
        from orpheus_ui.auth.models import User

        eq_db = TaxonomyEquivalenceDB(db_path=tmp_path / "eq.db")
        a = TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos")
        b = TaxonomyRef(namespace="audioset", id="/m/04s8yn")
        eq_db.record_equivalence(
            a, b, confidence=0.8, source="auto_discovered", status="pending_review"
        )
        assert eq_db.is_equivalent(a, b) is False

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.entities.TaxonomyEquivalenceDB", return_value=eq_db
        ):
            result = accept_equivalence(
                {
                    "a": {"namespace": "ioc", "id": "Corvus brachyrhynchos"},
                    "b": {"namespace": "audioset", "id": "/m/04s8yn"},
                },
                user=mock_user,
            )

        assert result["status"] == "accepted"
        assert eq_db.is_equivalent(a, b) is True

    def test_reject_records_non_equivalence(self, tmp_path):
        from orpheus_common.detection import TaxonomyEquivalenceDB, TaxonomyRef

        from orpheus_ui.api.entities import reject_equivalence
        from orpheus_ui.auth.models import User

        eq_db = TaxonomyEquivalenceDB(db_path=tmp_path / "eq.db")
        a = TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos")
        b = TaxonomyRef(namespace="audioset", id="/m/0bt9lr")
        eq_db.record_equivalence(a, b, confidence=0.95, source="auto_discovered")
        assert eq_db.is_equivalent(a, b) is True

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.entities.TaxonomyEquivalenceDB", return_value=eq_db
        ):
            result = reject_equivalence(
                {
                    "a": {"namespace": "ioc", "id": "Corvus brachyrhynchos"},
                    "b": {"namespace": "audioset", "id": "/m/0bt9lr"},
                    "notes": "Crow != Dog",
                },
                user=mock_user,
            )

        assert result["status"] == "rejected"
        assert eq_db.is_equivalent(a, b) is False


class TestAutoDiscoveryStatusEndpoint:
    """Tests for /api/auto-discovery/status — caches the latest MQTT
    health publish from the correlator's background worker."""

    def test_returns_never_run_when_no_health_received(self):
        from orpheus_ui.api import entities as entities_mod
        from orpheus_ui.api.entities import get_auto_discovery_status
        from orpheus_ui.auth.models import User

        entities_mod.LATEST_AUTO_DISCOVERY_HEALTH = None
        mock_user = MagicMock(spec=User)
        result = get_auto_discovery_status(user=mock_user)
        assert result == {"status": "never_run"}

    def test_returns_cached_health_when_received(self):
        from orpheus_ui.api import entities as entities_mod
        from orpheus_ui.api.entities import (
            get_auto_discovery_status,
            on_auto_discovery_health_message,
        )
        from orpheus_ui.auth.models import User

        entities_mod.LATEST_AUTO_DISCOVERY_HEALTH = None
        on_auto_discovery_health_message(
            "orpheus/system/auto-discovery/health",
            {
                "status": "ok",
                "ran_at": "2026-05-22T03:30:11+00:00",
                "total_proposals": 5,
                "recorded": 3,
                "skipped_existing": 1,
                "skipped_blocked": 1,
                "lifetime_runs": 12,
                "lifetime_proposals": 14,
            },
        )
        mock_user = MagicMock(spec=User)
        result = get_auto_discovery_status(user=mock_user)
        assert result["status"] == "ok"
        assert result["ran_at"] == "2026-05-22T03:30:11+00:00"
        assert result["recorded"] == 3
        assert result["lifetime_runs"] == 12


class TestErrorFeed:
    """Cross-agent error feed sourced from MQTT health publishes.
    Each agent's health may carry `last_error` + `errors_count`; the
    UI backend rings these and exposes /api/errors/recent."""

    def test_appends_entries_from_health_publishes(self):
        from orpheus_ui.api import entities as entities_mod
        from orpheus_ui.api.entities import (
            get_recent_errors,
            on_agent_health_message,
        )
        from orpheus_ui.auth.models import User

        entities_mod.ERROR_FEED.clear()
        on_agent_health_message(
            "orpheus/system/audio-events/health",
            {
                "status": "online",
                "last_error": "ValueError: bad audio",
                "errors_count": 1,
            },
        )
        result = get_recent_errors(limit=50, user=MagicMock(spec=User))
        assert result["total"] == 1
        assert result["errors"][0]["agent"] == "audio-events"
        assert result["errors"][0]["message"] == "ValueError: bad audio"
        assert result["errors"][0]["count"] == 1

    def test_dedups_repeated_identical_errors(self):
        """Same agent + same error within the dedup window coalesces."""
        from orpheus_ui.api import entities as entities_mod
        from orpheus_ui.api.entities import (
            get_recent_errors,
            on_agent_health_message,
        )
        from orpheus_ui.auth.models import User

        entities_mod.ERROR_FEED.clear()
        for i in range(5):
            on_agent_health_message(
                "orpheus/system/audio-events/health",
                {
                    "status": "online",
                    "last_error": "RuntimeError: GPU OOM",
                    "errors_count": i + 1,
                },
            )
        result = get_recent_errors(limit=50, user=MagicMock(spec=User))
        # All 5 collapsed into a single entry with count=5.
        assert result["total"] == 1
        assert result["errors"][0]["count"] == 5
        assert result["errors"][0]["errors_count"] == 5

    def test_skips_payloads_with_no_last_error(self):
        """Health publishes from healthy agents don't pollute the feed."""
        from orpheus_ui.api import entities as entities_mod
        from orpheus_ui.api.entities import (
            get_recent_errors,
            on_agent_health_message,
        )
        from orpheus_ui.auth.models import User

        entities_mod.ERROR_FEED.clear()
        on_agent_health_message(
            "orpheus/system/audio-events/health",
            {"status": "online", "errors_count": 0},
        )
        result = get_recent_errors(limit=50, user=MagicMock(spec=User))
        assert result["total"] == 0

    def test_ring_buffer_caps_at_max(self):
        """Adding more than ERROR_FEED_MAX distinct errors trims the
        oldest. Test with the real max."""
        from orpheus_ui.api import entities as entities_mod
        from orpheus_ui.api.entities import (
            ERROR_FEED_MAX,
            on_agent_health_message,
        )

        entities_mod.ERROR_FEED.clear()
        for i in range(ERROR_FEED_MAX + 10):
            on_agent_health_message(
                f"orpheus/system/agent-{i}/health",
                {
                    "status": "online",
                    "last_error": f"DistinctError-{i}",
                    "errors_count": 1,
                },
            )
        assert len(entities_mod.ERROR_FEED) == ERROR_FEED_MAX

    def test_multiple_agents_tracked_separately(self):
        from orpheus_ui.api import entities as entities_mod
        from orpheus_ui.api.entities import (
            get_recent_errors,
            on_agent_health_message,
        )
        from orpheus_ui.auth.models import User

        entities_mod.ERROR_FEED.clear()
        on_agent_health_message(
            "orpheus/system/audio-events/health",
            {"last_error": "PANNs OOM", "errors_count": 1},
        )
        on_agent_health_message(
            "orpheus/system/bird-detection/health",
            {"last_error": "BirdNET load failed", "errors_count": 1},
        )
        result = get_recent_errors(limit=50, user=MagicMock(spec=User))
        assert result["total"] == 2
        agents = {e["agent"] for e in result["errors"]}
        assert agents == {"audio-events", "bird-detection"}


class TestAudioEventsHealthEndpoint:
    """/api/audio-events/health caches the MQTT heartbeat from the
    audio-events agent (PANNs liveness, latency, errors)."""

    def test_returns_never_seen_when_no_heartbeat(self):
        from orpheus_ui.api import entities as entities_mod
        from orpheus_ui.api.entities import get_audio_events_health
        from orpheus_ui.auth.models import User

        entities_mod.LATEST_AUDIO_EVENTS_HEALTH = None
        mock_user = MagicMock(spec=User)
        result = get_audio_events_health(user=mock_user)
        assert result == {"status": "never_seen"}

    def test_returns_cached_heartbeat(self):
        from orpheus_ui.api import entities as entities_mod
        from orpheus_ui.api.entities import (
            get_audio_events_health,
            on_audio_events_health_message,
        )
        from orpheus_ui.auth.models import User

        entities_mod.LATEST_AUDIO_EVENTS_HEALTH = None
        on_audio_events_health_message(
            "orpheus/system/audio-events/health",
            {
                "status": "online",
                "model_loaded": True,
                "events_processed": 42,
                "detections_emitted": 137,
                "errors_count": 0,
                "inference_latency_ms": {
                    "samples": 42,
                    "p50": 145.0,
                    "p95": 220.0,
                    "max": 280.0,
                },
            },
        )
        mock_user = MagicMock(spec=User)
        result = get_audio_events_health(user=mock_user)
        assert result["status"] == "online"
        assert result["model_loaded"] is True
        assert result["inference_latency_ms"]["p95"] == 220.0


class TestCorrelatorHealthEndpoint:
    """/api/correlator/health detects late-arrival cases."""

    def test_healthy_state_one_entity_per_root(self, tmp_path):
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        from orpheus_common.detection import (
            DetectionDB,
            Entity,
            EntityEvidence,
        )

        from orpheus_ui.api.entities import get_correlator_health
        from orpheus_ui.auth.models import User

        db = DetectionDB(db_path=tmp_path / "det.db")
        ts = _dt.now(_tz.utc)
        for i in range(5):
            db.save_entity(
                Entity(
                    entity_id=f"ent-{i}",
                    timestamp=ts,
                    species="corvus",
                    evidence=[
                        EntityEvidence(
                            event_id=f"am-{i}", sensor_id="mic-1", confidence=0.9
                        )
                    ],
                    event_signature={
                        "audio_motion_source_ids": [f"am-{i}"],
                        "sensor_ids": ["mic-1"],
                        "start_time": ts.isoformat(),
                        "end_time": ts.isoformat(),
                    },
                )
            )

        mock_user = MagicMock(spec=User)
        with patch("orpheus_ui.api.entities._get_db", return_value=db):
            result = get_correlator_health(lookback_hours=24, user=mock_user)

        assert result["roots_examined"] == 5
        assert result["multi_entity_root_count"] == 0
        assert result["multi_entity_root_pct"] == 0.0
        assert result["entities_per_root_histogram"]["1"] == 5
        assert result["late_arrival_examples"] == []

    def test_legacy_entities_table_without_event_signature_does_not_crash(self, tmp_path):
        """A read-only DB whose entities table predates event_signature (the
        replica / degrade-to-read-only path on an un-migrated DB) must return
        an empty result, not 500 with 'no such column: event_signature'."""
        import sqlite3

        from orpheus_common.detection import DetectionDB

        from orpheus_ui.api.entities import get_correlator_health
        from orpheus_ui.auth.models import User

        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE entities (entity_id TEXT, timestamp TEXT, species TEXT)"
        )
        conn.execute(
            "INSERT INTO entities VALUES ('e1', '2025-01-01T00:00:00+00:00', 'corvus')"
        )
        conn.commit()
        conn.close()

        db = DetectionDB(db_path=db_path, read_only=True)  # read_only skips migration
        mock_user = MagicMock(spec=User)
        with patch("orpheus_ui.api.entities._get_db", return_value=db):
            result = get_correlator_health(lookback_hours=24, user=mock_user)

        assert result["roots_examined"] == 0
        assert result["multi_entity_root_count"] == 0

    def test_detects_late_arrival_case(self, tmp_path):
        """Two Entities sharing the same audio_motion_source_id = late-arrival."""
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        from orpheus_common.detection import (
            DetectionDB,
            Entity,
            EntityEvidence,
        )

        from orpheus_ui.api.entities import get_correlator_health
        from orpheus_ui.auth.models import User

        db = DetectionDB(db_path=tmp_path / "det.db")
        ts = _dt.now(_tz.utc)
        for i in range(2):
            db.save_entity(
                Entity(
                    entity_id=f"ent-late-{i}",
                    timestamp=ts,
                    species="corvus",
                    evidence=[
                        EntityEvidence(
                            event_id=f"ev-{i}", sensor_id="mic-1", confidence=0.9
                        )
                    ],
                    event_signature={
                        "audio_motion_source_ids": ["am-shared"],
                        "sensor_ids": ["mic-1"],
                        "start_time": ts.isoformat(),
                        "end_time": ts.isoformat(),
                    },
                )
            )

        mock_user = MagicMock(spec=User)
        with patch("orpheus_ui.api.entities._get_db", return_value=db):
            result = get_correlator_health(lookback_hours=24, user=mock_user)

        assert result["roots_examined"] == 1
        assert result["multi_entity_root_count"] == 1
        assert result["entities_per_root_histogram"]["2"] == 1
        assert len(result["late_arrival_examples"]) == 1
        assert result["late_arrival_examples"][0]["root_event_id"] == "am-shared"
        assert result["late_arrival_examples"][0]["entity_count"] == 2


class TestDiagnoseEquivalencesEndpoint:
    """/api/equivalences/diagnose surfaces near-miss pairs."""

    def test_diagnose_returns_near_misses(self, tmp_path):
        from datetime import datetime as _dt
        from datetime import timedelta
        from datetime import timezone as _tz

        from orpheus_common.detection import (
            Detection,
            DetectionDB,
            TaxonomyEquivalenceDB,
            TaxonomyRef,
        )

        from orpheus_ui.api.entities import diagnose_auto_discovery
        from orpheus_ui.auth.models import User

        det_db = DetectionDB(db_path=tmp_path / "det.db")
        eq_db = TaxonomyEquivalenceDB(db_path=tmp_path / "eq.db")
        now = _dt.now(_tz.utc)
        for i in range(3):
            ts = now - timedelta(hours=i)
            root = f"am-{i}"
            det_db.save(
                Detection(
                    event_id=f"bd-{i}",
                    timestamp=ts,
                    detection_type="species.detected",
                    species_code="corvus",
                    root_event_id=root,
                    taxonomy=TaxonomyRef(
                        namespace="ioc", id="Corvus brachyrhynchos"
                    ),
                )
            )
            det_db.save(
                Detection(
                    event_id=f"ae-{i}",
                    timestamp=ts,
                    detection_type="audio.classified",
                    species_code="audioset_/m/04s8yn",
                    root_event_id=root,
                    taxonomy=TaxonomyRef(namespace="audioset", id="/m/04s8yn"),
                )
            )

        mock_user = MagicMock(spec=User)
        mock_config = MagicMock()
        mock_config.correlation.auto_discovery.propose_threshold = 0.6
        mock_config.correlation.auto_discovery.min_cooccurrences = 5
        with patch(
            "orpheus_ui.api.entities._get_db", return_value=det_db
        ), patch(
            "orpheus_ui.api.entities.TaxonomyEquivalenceDB", return_value=eq_db
        ), patch(
            "orpheus_common.OrpheusConfig.get_instance", return_value=mock_config
        ):
            result = diagnose_auto_discovery(lookback_days=30, user=mock_user)

        assert result["total_detections"] == 6
        assert result["distinct_taxa_observed"] == 2
        # min_cooccurrences=5 but the pair fires only 3 times → near-miss-below-min-cooc.
        assert len(result["near_miss_below_min_cooc"]) == 1
        assert result["near_miss_below_min_cooc"][0]["jaccard"] == 1.0
        assert result["near_miss_below_min_cooc"][0]["cooccurrence"] == 3


class TestScanEquivalencesEndpoint:
    """POST /api/equivalences/scan triggers auto-discovery inline.

    Lets ops/UI run a scan on demand rather than waiting 6h for the
    correlator's periodic worker."""

    def test_scan_runs_and_returns_proposal_summary(self, tmp_path):
        """A scan with no co-occurrence data returns zero proposals,
        not an error."""
        from orpheus_common.detection import DetectionDB, TaxonomyEquivalenceDB

        from orpheus_ui.api.entities import scan_equivalences_now
        from orpheus_ui.auth.models import User

        det_db = DetectionDB(db_path=tmp_path / "det.db")
        eq_db = TaxonomyEquivalenceDB(db_path=tmp_path / "eq.db")

        mock_user = MagicMock(spec=User)
        mock_config = MagicMock()
        mock_config.correlation.auto_discovery.lookback_days = 7
        mock_config.correlation.auto_discovery.propose_threshold = 0.6
        mock_config.correlation.auto_discovery.accept_threshold = 0.9
        mock_config.correlation.auto_discovery.min_cooccurrences = 5
        with patch(
            "orpheus_ui.api.entities._get_db", return_value=det_db
        ), patch(
            "orpheus_ui.api.entities.TaxonomyEquivalenceDB", return_value=eq_db
        ), patch(
            "orpheus_common.OrpheusConfig.get_instance", return_value=mock_config
        ):
            result = scan_equivalences_now(payload={}, user=mock_user)

        assert "ran_at" in result
        assert result["total_proposals"] == 0
        assert result["recorded"] == 0
        assert result["proposals"] == []

    def test_scan_with_real_cooccurrence_records_equivalences(self, tmp_path):
        """Pump co-occurrence data into the detection DB and trigger a
        scan — auto-discovery records the proposal end-to-end."""
        from datetime import datetime as _dt
        from datetime import timedelta
        from datetime import timezone as _tz

        from orpheus_common.detection import (
            Detection,
            DetectionDB,
            TaxonomyEquivalenceDB,
            TaxonomyRef,
        )

        from orpheus_ui.api.entities import scan_equivalences_now
        from orpheus_ui.auth.models import User

        det_db = DetectionDB(db_path=tmp_path / "det.db")
        eq_db = TaxonomyEquivalenceDB(db_path=tmp_path / "eq.db")
        now = _dt.now(_tz.utc)
        # 3 audio.motion events, each with bird-detection + audio-events.
        for i in range(3):
            ts = now - timedelta(hours=i)
            root = f"am-{i}"
            det_db.save(
                Detection(
                    event_id=f"bd-{i}",
                    timestamp=ts,
                    detection_type="species.detected",
                    species_code="corvus",
                    root_event_id=root,
                    taxonomy=TaxonomyRef(
                        namespace="ioc", id="Corvus brachyrhynchos"
                    ),
                )
            )
            det_db.save(
                Detection(
                    event_id=f"ae-{i}",
                    timestamp=ts,
                    detection_type="audio.classified",
                    species_code="audioset_/m/04s8yn",
                    root_event_id=root,
                    taxonomy=TaxonomyRef(
                        namespace="audioset", id="/m/04s8yn"
                    ),
                )
            )

        mock_user = MagicMock(spec=User)
        mock_config = MagicMock()
        mock_config.correlation.auto_discovery.lookback_days = 30
        mock_config.correlation.auto_discovery.propose_threshold = 0.6
        mock_config.correlation.auto_discovery.accept_threshold = 0.9
        mock_config.correlation.auto_discovery.min_cooccurrences = 2
        with patch(
            "orpheus_ui.api.entities._get_db", return_value=det_db
        ), patch(
            "orpheus_ui.api.entities.TaxonomyEquivalenceDB", return_value=eq_db
        ), patch(
            "orpheus_common.OrpheusConfig.get_instance", return_value=mock_config
        ):
            result = scan_equivalences_now(
                payload={"min_cooccurrences": 2, "lookback_days": 30}, user=mock_user
            )

        assert result["recorded"] == 1
        recorded = next(
            p for p in result["proposals"] if p["action"] == "recorded"
        )
        assert recorded["jaccard"] == 1.0
        assert recorded["status"] == "accepted"


class TestChainEndpoint:
    """Tests for /api/chain/{root_event_id} — the lineage view."""

    def _det(self, event_id, root, detection_type, timestamp, source_event_id=None):
        from datetime import datetime as _dt

        from orpheus_common.detection.models import Detection

        if isinstance(timestamp, str):
            timestamp = _dt.fromisoformat(timestamp.replace("Z", "+00:00"))
        return Detection(
            event_id=event_id,
            timestamp=timestamp,
            detection_type=detection_type,
            root_event_id=root,
            source_event_id=source_event_id,
        )

    def test_returns_full_chain(self):
        """A root_event_id with multiple chain members returns them all."""
        from orpheus_ui.api.entities import get_chain
        from orpheus_ui.auth.models import User

        chain = [
            self._det("am-001", "am-001", "audio.motion", "2026-01-01T12:00:00+00:00"),
            self._det(
                "bd-001", "am-001", "species.detected",
                "2026-01-01T12:00:00.500000+00:00", "am-001",
            ),
            self._det(
                "ae-001", "am-001", "audio.classified",
                "2026-01-01T12:00:01+00:00", "am-001",
            ),
            self._det(
                "cd-001", "am-001", "crow.analyzed",
                "2026-01-01T12:00:02+00:00", "bd-001",
            ),
        ]
        mock_db = MagicMock()
        mock_db.get_chain.return_value = chain

        mock_user = MagicMock(spec=User)
        with patch("orpheus_ui.api.entities._get_db", return_value=mock_db):
            result = get_chain("am-001", user=mock_user)

        assert result["root_event_id"] == "am-001"
        assert result["count"] == 4
        types = [d["detection_type"] for d in result["chain"]]
        assert types == [
            "audio.motion",
            "species.detected",
            "audio.classified",
            "crow.analyzed",
        ]

    def test_empty_chain_returns_404(self):
        """No chain rows → 404 (not an empty 200)."""
        from fastapi import HTTPException

        from orpheus_ui.api.entities import get_chain
        from orpheus_ui.auth.models import User

        mock_db = MagicMock()
        mock_db.get_chain.return_value = []

        mock_user = MagicMock(spec=User)
        with patch("orpheus_ui.api.entities._get_db", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                get_chain("am-does-not-exist", user=mock_user)
            assert exc_info.value.status_code == 404


class TestBirdHistoryEndpoint:
    """Tests for the /api/data/birds/history endpoint query params.

    Covers: backward-compat (no page/page_size -> legacy 2000 cap),
    server-side pagination, and the species filter.
    """

    def _make_detection(self, timestamp, species_code, species_common, confidence=0.9):
        from datetime import datetime as _dt

        from orpheus_common.detection.models import Detection

        if isinstance(timestamp, str):
            timestamp = _dt.fromisoformat(timestamp.replace("Z", "+00:00"))
        return Detection(
            timestamp=timestamp,
            detection_type="species.detected",
            channel=1,
            species_code=species_code,
            species_common=species_common,
            confidence=confidence,
            audio_clip_path=None,
        )

    def _fake_db(self, detections):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [_det_to_row(d) for d in detections]
        return mock_db

    def test_bad_start_date_returns_400_not_500(self):
        """Regression: an unparseable start_date must surface as a clean 400,
        not a 500 leaking the raw ValueError.

        The five diagnostics history endpoints used to parse the ISO date with
        no try/except, so ``?start_date=garbage`` raised ValueError that the
        bare ``except Exception`` re-wrapped as an HTTP 500. resolve_date_range
        now raises HTTPException(400), and the endpoint re-raises HTTPException
        untouched.
        """
        from fastapi import HTTPException

        from orpheus_ui.api.diagnostics import get_bird_history
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db([]),
        ):
            with pytest.raises(HTTPException) as exc_info:
                get_bird_history(start_date="garbage", user=mock_user)

        assert exc_info.value.status_code == 400
        assert "start_date" in exc_info.value.detail

    def test_legacy_shape_when_no_pagination_params(self):
        """Omitting page/page_size preserves the original response shape (2000-cap)."""
        from orpheus_ui.api.diagnostics import get_bird_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_detection("2026-01-01T12:00:00+00:00", "amecro", "American Crow"),
            self._make_detection("2026-01-02T12:00:00+00:00", "norcar", "Northern Cardinal"),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_bird_history(
                start_date="2026-01-01",
                end_date="2026-01-07",
                user=mock_user,
            )

        assert "detections" in result
        assert "stats" in result
        assert result["stats"]["total_count"] == 2
        assert "page" not in result
        assert "page_size" not in result
        assert "total_pages" not in result
        assert "all_species" in result["stats"]

    def test_pagination_slices_detections(self):
        """page+page_size returns the 1-indexed slice and total_pages."""
        from orpheus_ui.api.diagnostics import get_bird_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_detection(
                f"2026-01-{i:02d}T12:00:00+00:00", "amecro", "American Crow"
            )
            for i in range(1, 11)
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            page1 = get_bird_history(
                start_date="2026-01-01",
                end_date="2026-01-31",
                page=1,
                page_size=3,
                user=mock_user,
            )
            page2 = get_bird_history(
                start_date="2026-01-01",
                end_date="2026-01-31",
                page=2,
                page_size=3,
                user=mock_user,
            )

        assert page1["page"] == 1
        assert page1["page_size"] == 3
        assert page1["total_pages"] == 4  # ceil(10/3)
        assert len(page1["detections"]) == 3
        assert page1["stats"]["total_count"] == 10

        assert page2["page"] == 2
        assert len(page2["detections"]) == 3
        # Most-recent-first sort: page1 should contain newer timestamps than page2
        assert page1["detections"][0]["timestamp"] > page2["detections"][0]["timestamp"]

    def test_species_filter_keeps_only_matching_rows(self):
        """species=csv filters detections to the listed species (case-insensitive)."""
        from orpheus_ui.api.diagnostics import get_bird_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_detection("2026-01-01T12:00:00+00:00", "amecro", "American Crow"),
            self._make_detection("2026-01-02T12:00:00+00:00", "norcar", "Northern Cardinal"),
            self._make_detection("2026-01-03T12:00:00+00:00", "amecro", "American Crow"),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_bird_history(
                start_date="2026-01-01",
                end_date="2026-01-31",
                species="American Crow",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 2
        assert all(d["species_common"] == "American Crow" for d in result["detections"])
        # all_species should still include both species so the dropdown stays populated
        assert set(result["stats"]["all_species"].keys()) == {
            "American Crow",
            "Northern Cardinal",
        }
        # species_distribution reflects the filter
        assert set(result["stats"]["species_distribution"].keys()) == {"American Crow"}

    def test_species_filter_matches_species_code(self):
        """Species filter also matches on species_code, not just common name."""
        from orpheus_ui.api.diagnostics import get_bird_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_detection("2026-01-01T12:00:00+00:00", "amecro", "American Crow"),
            self._make_detection("2026-01-02T12:00:00+00:00", "norcar", "Northern Cardinal"),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_bird_history(
                start_date="2026-01-01",
                end_date="2026-01-31",
                species="amecro",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 1
        assert result["detections"][0]["species_code"] == "amecro"

    def test_non_bird_sounds_still_filtered(self):
        """is_bird_sound filter must run before species filter, not after."""
        from orpheus_ui.api.diagnostics import get_bird_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_detection("2026-01-01T12:00:00+00:00", "human", "Human whistle"),
            self._make_detection("2026-01-02T12:00:00+00:00", "amecro", "American Crow"),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_bird_history(
                start_date="2026-01-01",
                end_date="2026-01-31",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 1
        assert result["filtered_count"] == 1


class TestAudioEventsHistoryEndpoint:
    """Tests for the /api/data/audio-events/history endpoint.

    Mirrors TestBirdHistoryEndpoint but for the audio.classified detection
    type. Verifies intervals + taxonomy fields are surfaced per ADR 0011.
    """

    def _make_audio_event_detection(
        self,
        timestamp,
        species_code,
        species_common,
        confidence=0.7,
        intervals=None,
        taxonomy_namespace="audioset",
        taxonomy_id=None,
    ):
        from datetime import datetime as _dt

        from orpheus_common.detection.models import (
            Detection,
            TaxonomyRef,
            TemporalInterval,
        )

        if isinstance(timestamp, str):
            timestamp = _dt.fromisoformat(timestamp.replace("Z", "+00:00"))

        interval_objs = None
        if intervals is not None:
            interval_objs = [TemporalInterval(**i) for i in intervals]

        taxonomy = None
        if taxonomy_id is not None:
            taxonomy = TaxonomyRef(
                namespace=taxonomy_namespace,
                id=taxonomy_id,
                common_name=species_common,
            )

        return Detection(
            timestamp=timestamp,
            detection_type="audio.classified",
            channel=1,
            species_code=species_code,
            species_common=species_common,
            confidence=confidence,
            audio_clip_path="/data/orpheus/audio/test.flac",
            intervals=interval_objs,
            taxonomy=taxonomy,
        )

    def _fake_db(self, detections):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [_det_to_row(d) for d in detections]
        return mock_db

    def test_legacy_shape_no_pagination(self):
        """Omitting page/page_size preserves the 2000-cap response shape."""
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_audio_event_detection(
                "2026-01-01T12:00:00+00:00",
                "audioset_/m/0bt9lr",
                "Dog",
                taxonomy_id="/m/0bt9lr",
            ),
            self._make_audio_event_detection(
                "2026-01-02T12:00:00+00:00",
                "audioset_/m/03m9d0z",
                "Rain",
                taxonomy_id="/m/03m9d0z",
            ),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_audio_events_history(
                start_date="2026-01-01",
                end_date="2026-01-07",
                user=mock_user,
            )

        assert "detections" in result
        assert "stats" in result
        assert result["stats"]["total_count"] == 2
        assert result["stats"]["unique_label_count"] == 2
        assert "all_labels" in result["stats"]
        assert "page" not in result

    def test_scatter_sample_present_and_spans_range(self):
        """Audio Events history returns a scatter_sample (same shape as
        /data/birds/history) so the page can reuse the shared
        ConfidenceScatterChart. It spans the full range, ascending."""
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_audio_event_detection(
                "2026-01-01T12:00:00+00:00",
                "audioset_/m/0bt9lr",
                "Dog",
                confidence=0.61,
                taxonomy_id="/m/0bt9lr",
            ),
            self._make_audio_event_detection(
                "2026-01-05T12:00:00+00:00",
                "audioset_/m/09xqv",
                "Cricket",
                confidence=0.52,
                taxonomy_id="/m/09xqv",
            ),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_audio_events_history(
                start_date="2026-01-01",
                end_date="2026-01-07",
                user=mock_user,
            )

        assert "scatter_sample" in result
        assert len(result["scatter_sample"]) == 2
        point = result["scatter_sample"][0]
        assert set(point.keys()) == {
            "timestamp",
            "species_code",
            "species_common",
            "confidence",
        }
        scatter_dates = {s["timestamp"][:10] for s in result["scatter_sample"]}
        assert scatter_dates == {"2026-01-01", "2026-01-05"}

    def test_intervals_and_taxonomy_surfaced_in_payload(self):
        """ADR 0011: per-detection intervals + taxonomy are in the response."""
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_audio_event_detection(
                "2026-01-01T12:00:00+00:00",
                "audioset_/m/0bt9lr",
                "Dog",
                taxonomy_id="/m/0bt9lr",
                intervals=[
                    {"start_seconds": 0.5, "end_seconds": 2.0, "confidence": 0.85},
                    {"start_seconds": 4.0, "end_seconds": 5.5, "confidence": 0.72},
                ],
            ),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_audio_events_history(
                start_date="2026-01-01",
                end_date="2026-01-07",
                user=mock_user,
            )

        det = result["detections"][0]
        assert det["intervals"] is not None
        assert len(det["intervals"]) == 2
        assert det["intervals"][0]["start_seconds"] == 0.5
        assert det["taxonomy"] is not None
        assert det["taxonomy"]["namespace"] == "audioset"
        assert det["taxonomy"]["id"] == "/m/0bt9lr"

    def test_labels_filter_by_common_name(self):
        """labels= keeps only rows matching common name (case-insensitive)."""
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_audio_event_detection(
                "2026-01-01T12:00:00+00:00", "audioset_dog", "Dog", taxonomy_id="/m/0bt9lr"
            ),
            self._make_audio_event_detection(
                "2026-01-02T12:00:00+00:00",
                "audioset_rain",
                "Rain",
                taxonomy_id="/m/03m9d0z",
            ),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_audio_events_history(
                start_date="2026-01-01",
                end_date="2026-01-07",
                labels="dog",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 1
        assert result["detections"][0]["species_common"] == "Dog"
        # All-labels still shows both (so the dropdown can show options).
        assert "Rain" in result["stats"]["all_labels"]

    def test_labels_filter_by_machine_id(self):
        """labels= also accepts AudioSet machine_ids via taxonomy.id."""
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_audio_event_detection(
                "2026-01-01T12:00:00+00:00", "audioset_dog", "Dog", taxonomy_id="/m/0bt9lr"
            ),
            self._make_audio_event_detection(
                "2026-01-02T12:00:00+00:00",
                "audioset_rain",
                "Rain",
                taxonomy_id="/m/03m9d0z",
            ),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_audio_events_history(
                start_date="2026-01-01",
                end_date="2026-01-07",
                labels="/m/0bt9lr",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 1
        assert result["detections"][0]["taxonomy"]["id"] == "/m/0bt9lr"

    def test_labels_filter_pipe_separated_preserves_comma_in_value(self):
        """Pipe separator lets a single label containing a comma round-
        trip cleanly. AudioSet labels routinely contain commas (e.g.
        'Heart sounds, heartbeat' — /m/03qc9zr). The frontend's
        useUrlMultiSelect('label', { separator: '|' }) feeds the
        backend pipe-joined; the parser splits on '|' when present and
        falls back to ',' otherwise (legacy / external callers)."""
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_audio_event_detection(
                "2026-01-01T12:00:00+00:00",
                "audioset_heart",
                "Heart sounds, heartbeat",
                taxonomy_id="/m/03qc9zr",
            ),
            self._make_audio_event_detection(
                "2026-01-02T12:00:00+00:00",
                "audioset_crow",
                "Crow",
                taxonomy_id="/m/015lz1",
            ),
            self._make_audio_event_detection(
                "2026-01-03T12:00:00+00:00",
                "audioset_rain",
                "Rain",
                taxonomy_id="/m/03m9d0z",
            ),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_audio_events_history(
                start_date="2026-01-01",
                end_date="2026-01-07",
                labels="Heart sounds, heartbeat|Crow",
                user=mock_user,
            )

        # The Heart row + the Crow row should match; Rain should not.
        # Crucially: 'Heart sounds, heartbeat' is ONE label, not three
        # ghost matches against 'Heart sounds', ' heartbeat', 'Crow'.
        assert result["stats"]["total_count"] == 2
        names = {d["species_common"] for d in result["detections"]}
        assert names == {"Heart sounds, heartbeat", "Crow"}

    def test_labels_filter_single_comma_bearing_label_matches(self):
        """Single-label pick of a comma-bearing AudioSet display name
        matches the row. Regression for the joined-no-pipe bug: when
        the frontend joins a single-element selection with '|' the
        result has no pipe character, and a prior pipe-or-comma
        fallback parser would split the value on the embedded comma
        and break the match. The parser now always splits on '|'."""
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_audio_event_detection(
                "2026-01-01T12:00:00+00:00",
                "audioset_heart",
                "Heart sounds, heartbeat",
                taxonomy_id="/m/03qc9zr",
            ),
            self._make_audio_event_detection(
                "2026-01-02T12:00:00+00:00",
                "audioset_rain",
                "Rain",
                taxonomy_id="/m/03m9d0z",
            ),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_audio_events_history(
                start_date="2026-01-01",
                end_date="2026-01-07",
                # SINGLE label — no pipe in the joined string.
                labels="Heart sounds, heartbeat",
                user=mock_user,
            )

        # Should match the single Heart row; Rain excluded.
        assert result["stats"]["total_count"] == 1
        assert result["detections"][0]["species_common"] == "Heart sounds, heartbeat"

    def test_pagination(self):
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_audio_event_detection(
                f"2026-01-{i:02d}T12:00:00+00:00", "audioset_dog", "Dog", taxonomy_id="/m/0bt9lr"
            )
            for i in range(1, 8)
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            page1 = get_audio_events_history(
                start_date="2026-01-01",
                end_date="2026-01-31",
                page=1,
                page_size=3,
                user=mock_user,
            )

        assert page1["page"] == 1
        assert page1["page_size"] == 3
        assert page1["total_pages"] == 3  # ceil(7/3)
        assert len(page1["detections"]) == 3

    def test_legacy_detection_without_intervals_or_taxonomy(self):
        """Legacy detections (pre-ADR 0011) surface intervals=None / taxonomy=None
        rather than crashing the endpoint."""
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._make_audio_event_detection(
                "2026-01-01T12:00:00+00:00",
                "audioset_unknown",
                "Unknown",
                intervals=None,
                taxonomy_id=None,
            ),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_audio_events_history(
                start_date="2026-01-01",
                end_date="2026-01-07",
                user=mock_user,
            )

        det = result["detections"][0]
        assert det["intervals"] is None
        assert det["taxonomy"] is None


class TestExpandedBirdLikeAudioset:
    """Cross-classifier-identity §5 (step 15): the bird-like AudioSet
    set grows dynamically as the equivalence graph learns new edges."""

    def test_seed_set_works_with_no_equivalence_data(self, tmp_path):
        """With an empty equivalence DB, is_bird_like_audioset still
        works using just the hardcoded seed list."""
        from orpheus_common.detection import TaxonomyEquivalenceDB

        from orpheus_ui.api.diagnostics import (
            BIRD_LIKE_AUDIOSET_MIDS,
            is_bird_like_audioset,
            reset_bird_like_audioset_cache,
        )

        eq_db = TaxonomyEquivalenceDB(db_path=tmp_path / "eq.db")
        reset_bird_like_audioset_cache()
        with patch(
            "orpheus_common.detection.TaxonomyEquivalenceDB", return_value=eq_db
        ):
            # Seed mid recognised.
            seed_mid = next(iter(BIRD_LIKE_AUDIOSET_MIDS))
            assert (
                is_bird_like_audioset(None, seed_mid) is True
            )
            # Random non-seed mid not recognised.
            assert is_bird_like_audioset(None, "/m/not-a-bird") is False

    def test_expansion_picks_up_learned_audioset_equivalents(self, tmp_path):
        """After auto-discovery learns audioset:/m/04s8yn ≡ audioset:/m/some-new-mid,
        the new mid is also bird-like."""
        from orpheus_common.detection import (
            TaxonomyEquivalenceDB,
            TaxonomyRef,
        )

        from orpheus_ui.api.diagnostics import (
            is_bird_like_audioset,
            reset_bird_like_audioset_cache,
        )

        eq_db = TaxonomyEquivalenceDB(db_path=tmp_path / "eq.db")
        # New mid equivalence learned by auto-discovery (hypothetical
        # audioset synonym for Crow).
        eq_db.record_equivalence(
            TaxonomyRef(namespace="audioset", id="/m/04s8yn"),  # known crow
            TaxonomyRef(namespace="audioset", id="/m/synthetic_new"),
            confidence=1.0,
            source="auto_discovered",
        )

        reset_bird_like_audioset_cache()
        with patch(
            "orpheus_common.detection.TaxonomyEquivalenceDB", return_value=eq_db
        ):
            # The new mid is now recognised as bird-like.
            assert (
                is_bird_like_audioset(None, "/m/synthetic_new") is True
            )

    def test_reset_cache_picks_up_new_equivalences(self, tmp_path):
        """Calling reset_bird_like_audioset_cache after adding a new
        equivalence makes it visible on the next is_bird_like check."""
        from orpheus_common.detection import (
            TaxonomyEquivalenceDB,
            TaxonomyRef,
        )

        from orpheus_ui.api.diagnostics import (
            is_bird_like_audioset,
            reset_bird_like_audioset_cache,
        )

        eq_db = TaxonomyEquivalenceDB(db_path=tmp_path / "eq.db")
        reset_bird_like_audioset_cache()
        with patch(
            "orpheus_common.detection.TaxonomyEquivalenceDB", return_value=eq_db
        ):
            assert is_bird_like_audioset(None, "/m/freshly_learned") is False

            # New equivalence added live.
            eq_db.record_equivalence(
                TaxonomyRef(namespace="audioset", id="/m/04s8yn"),
                TaxonomyRef(namespace="audioset", id="/m/freshly_learned"),
                confidence=1.0,
                source="manual",
            )
            # Without cache bust, still False (stale).
            assert is_bird_like_audioset(None, "/m/freshly_learned") is False

            # After bust, picks it up.
            reset_bird_like_audioset_cache()
            assert is_bird_like_audioset(None, "/m/freshly_learned") is True

    def test_reset_during_compute_is_not_clobbered(self):
        """A reset() that fires WHILE the expansion is being computed must not be lost:
        the in-flight pre-reset snapshot is discarded (generation moved), so the cache
        stays cleared and the next call recomputes post-reset instead of being pinned to
        the stale graph for the full 5-minute TTL."""
        import orpheus_ui.api.diagnostics as diag

        diag.reset_bird_like_audioset_cache()

        class _ResetMidWalk:
            """Fake equivalence DB whose walk fires a reset() the first time it's asked
            — standing in for a concurrent accept/reject landing during the compute."""

            def __init__(self):
                self._fired = False

            def equivalent_taxa(self, seed):
                if not self._fired:
                    self._fired = True
                    diag.reset_bird_like_audioset_cache()  # bump generation mid-compute
                return []

        with patch(
            "orpheus_common.detection.TaxonomyEquivalenceDB",
            return_value=_ResetMidWalk(),
        ):
            result = diag._expanded_bird_like_audioset_mids()

        # This call still gets a usable (seed) set...
        assert result >= set(diag.BIRD_LIKE_AUDIOSET_MIDS)
        # ...but the pre-reset snapshot was NOT installed: the cache is still cleared, so
        # the next call recomputes with the post-reset graph (the bug installed it and
        # pinned the UI for the TTL).
        assert diag._EXPANDED_BIRD_LIKE_CACHE is None
        diag.reset_bird_like_audioset_cache()  # leave clean for other tests


class TestAudioEventsBirdCorrelation:
    """Tests for the /api/data/audio-events/bird-correlation endpoint.

    This endpoint is the gating signal for putting bird-detection behind
    audio-events. It MUST
    correctly identify the four cohorts and compute parity_ratio."""

    def _audio_motion(self, event_id, timestamp_str):
        from datetime import datetime as _dt

        from orpheus_common.detection.models import Detection

        return Detection(
            event_id=event_id,
            timestamp=_dt.fromisoformat(timestamp_str.replace("Z", "+00:00")),
            detection_type="audio.motion",
            channel=1,
            audio_clip_path=f"/data/orpheus/audio/{event_id}.flac",
        )

    def _bird_det(
        self,
        source_id,
        timestamp_str,
        species_common="American Crow",
        species_code="amecro",
    ):
        from datetime import datetime as _dt

        from orpheus_common.detection.models import Detection

        return Detection(
            event_id=f"bird_{source_id}",
            timestamp=_dt.fromisoformat(timestamp_str.replace("Z", "+00:00")),
            detection_type="species.detected",
            channel=1,
            species_code=species_code,
            species_common=species_common,
            confidence=0.9,
            source_event_id=source_id,
        )

    def _audio_event(
        self,
        source_id,
        timestamp_str,
        is_bird=True,
        machine_id=None,
        label="Bird",
    ):
        from datetime import datetime as _dt

        from orpheus_common.detection.models import Detection, TaxonomyRef

        mid = machine_id or ("/m/020bb7" if is_bird else "/m/0bt9lr")  # Bird vocalization | Dog
        common = label if is_bird else "Dog"
        return Detection(
            event_id=f"audio_{source_id}",
            timestamp=_dt.fromisoformat(timestamp_str.replace("Z", "+00:00")),
            detection_type="audio.classified",
            channel=1,
            species_code=f"audioset_{mid}",
            species_common=common,
            confidence=0.8,
            source_event_id=source_id,
            taxonomy=TaxonomyRef(namespace="audioset", id=mid, common_name=common),
        )

    def _fake_db(self, audio_motion, bird, audio_events):
        mock_db = MagicMock()

        def _query(detection_type=None, **kwargs):
            if detection_type == "audio.motion":
                return [_det_to_row(d) for d in audio_motion]
            if detection_type == "species.detected":
                return [_det_to_row(d) for d in bird]
            if detection_type == "audio.classified":
                return [_det_to_row(d) for d in audio_events]
            return []

        mock_db.query_rows.side_effect = _query
        return mock_db

    def test_both_cohort_both_caught_same_clip(self):
        """Audio.motion event where both BirdNET and audio-events fire on
        a bird → counts toward the 'both' cohort."""
        from orpheus_ui.api.diagnostics import get_audio_events_bird_correlation
        from orpheus_ui.auth.models import User

        evt_ts = "2026-01-01T12:00:00+00:00"
        motion = [self._audio_motion("am-001", evt_ts)]
        bird = [self._bird_det("am-001", evt_ts)]
        audio = [self._audio_event("am-001", evt_ts, is_bird=True)]

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(motion, bird, audio),
        ):
            result = get_audio_events_bird_correlation(
                start_date="2026-01-01",
                end_date="2026-01-07",
                user=mock_user,
            )

        s = result["summary"]
        assert s["audio_motion_count"] == 1
        assert s["both_count"] == 1
        assert s["birdnet_only_count"] == 0
        assert s["audio_events_only_count"] == 0
        assert s["neither_count"] == 0
        assert s["parity_ratio"] == 1.0
        assert s["ready_to_gate"] is True

    def test_birdnet_only_cohort_is_the_red_flag(self):
        """Audio.motion where BirdNET caught a bird and audio-events
        didn't → 'birdnet_only' (the cohort that BLOCKS gating)."""
        from orpheus_ui.api.diagnostics import get_audio_events_bird_correlation
        from orpheus_ui.auth.models import User

        evt_ts = "2026-01-01T12:00:00+00:00"
        motion = [self._audio_motion("am-002", evt_ts)]
        bird = [self._bird_det("am-002", evt_ts)]
        audio = []  # audio-events caught nothing

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(motion, bird, audio),
        ):
            result = get_audio_events_bird_correlation(
                start_date="2026-01-01",
                end_date="2026-01-07",
                user=mock_user,
            )

        s = result["summary"]
        assert s["birdnet_only_count"] == 1
        assert s["both_count"] == 0
        assert s["parity_ratio"] == 0.0
        assert s["ready_to_gate"] is False
        # The clip surfaces in birdnet_only_clips for actionable review.
        assert len(result["birdnet_only_clips"]) == 1
        assert result["birdnet_only_clips"][0]["audio_motion_event_id"] == "am-002"

    def test_audio_events_only_cohort_is_a_good_signal(self):
        """audio-events firing on a bird that BirdNET missed is GOOD —
        audio-events is more permissive (a candidate gate property)."""
        from orpheus_ui.api.diagnostics import get_audio_events_bird_correlation
        from orpheus_ui.auth.models import User

        evt_ts = "2026-01-01T12:00:00+00:00"
        motion = [self._audio_motion("am-003", evt_ts)]
        bird = []
        audio = [self._audio_event("am-003", evt_ts, is_bird=True)]

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(motion, bird, audio),
        ):
            result = get_audio_events_bird_correlation(
                start_date="2026-01-01",
                end_date="2026-01-07",
                user=mock_user,
            )

        s = result["summary"]
        assert s["audio_events_only_count"] == 1
        # No BirdNET denominator → parity_ratio is undefined.
        assert s["parity_ratio"] is None

    def test_neither_cohort_is_non_bird_noise(self):
        """Audio.motion that nobody flagged as a bird (e.g. a car) is the
        'neither' bucket — neutral, not a parity signal."""
        from orpheus_ui.api.diagnostics import get_audio_events_bird_correlation
        from orpheus_ui.auth.models import User

        evt_ts = "2026-01-01T12:00:00+00:00"
        motion = [self._audio_motion("am-004", evt_ts)]
        bird = []
        audio = [self._audio_event("am-004", evt_ts, is_bird=False)]

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(motion, bird, audio),
        ):
            result = get_audio_events_bird_correlation(
                start_date="2026-01-01",
                end_date="2026-01-07",
                user=mock_user,
            )

        s = result["summary"]
        assert s["neither_count"] == 1
        assert s["both_count"] == 0
        assert s["birdnet_only_count"] == 0
        assert s["audio_events_only_count"] == 0

    def test_parity_ratio_aggregates_across_clips(self):
        """parity_ratio is audio_events_caught / birdnet_caught aggregated
        over the entire date range (not per-clip)."""
        from orpheus_ui.api.diagnostics import get_audio_events_bird_correlation
        from orpheus_ui.auth.models import User

        ts1 = "2026-01-01T12:00:00+00:00"
        ts2 = "2026-01-02T12:00:00+00:00"
        ts3 = "2026-01-03T12:00:00+00:00"
        ts4 = "2026-01-04T12:00:00+00:00"

        motion = [
            self._audio_motion("am-1", ts1),  # both
            self._audio_motion("am-2", ts2),  # both
            self._audio_motion("am-3", ts3),  # birdnet-only (miss)
            self._audio_motion("am-4", ts4),  # audio-events-only (bonus)
        ]
        bird = [
            self._bird_det("am-1", ts1),
            self._bird_det("am-2", ts2),
            self._bird_det("am-3", ts3),
        ]
        audio = [
            self._audio_event("am-1", ts1, is_bird=True),
            self._audio_event("am-2", ts2, is_bird=True),
            self._audio_event("am-4", ts4, is_bird=True),
        ]

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(motion, bird, audio),
        ):
            result = get_audio_events_bird_correlation(
                start_date="2026-01-01",
                end_date="2026-01-07",
                user=mock_user,
            )

        s = result["summary"]
        # BirdNET caught 3 (am-1, am-2, am-3); audio caught 3 (am-1, am-2, am-4).
        assert s["birdnet_caught_count"] == 3
        assert s["audio_events_caught_count"] == 3
        assert s["parity_ratio"] == 1.0
        # ready_to_gate is True at parity 1.0
        assert s["ready_to_gate"] is True

    def test_daily_counts_are_per_calendar_day(self):
        from orpheus_ui.api.diagnostics import get_audio_events_bird_correlation
        from orpheus_ui.auth.models import User

        motion = [
            self._audio_motion("am-d1", "2026-01-01T12:00:00+00:00"),
            self._audio_motion("am-d2", "2026-01-02T12:00:00+00:00"),
        ]
        bird = [self._bird_det("am-d1", "2026-01-01T12:00:00+00:00")]
        audio = [self._audio_event("am-d1", "2026-01-01T12:00:00+00:00", is_bird=True)]

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(motion, bird, audio),
        ):
            result = get_audio_events_bird_correlation(
                start_date="2026-01-01",
                end_date="2026-01-07",
                user=mock_user,
            )

        days_with_data = {d["date"]: d for d in result["daily_counts"]}
        assert days_with_data["2026-01-01"]["both"] == 1
        assert days_with_data["2026-01-02"]["neither"] == 1


class TestCrowStatsEndpoint:
    """Tests for the /api/data/crows/stats endpoint query params."""

    def _make_crow_detection(self, timestamp, call_type, confidence=0.8):
        from datetime import datetime as _dt

        from orpheus_common.detection.models import Detection

        if isinstance(timestamp, str):
            timestamp = _dt.fromisoformat(timestamp.replace("Z", "+00:00"))
        return Detection(
            timestamp=timestamp,
            detection_type="crow.analyzed",
            channel=1,
            confidence=confidence,
            audio_clip_path=None,
            metadata={"call_type": call_type, "attributes": {"age": "adult"}},
        )

    def _fake_db(self, detections):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [_det_to_row(d) for d in detections]
        return mock_db

    def test_legacy_shape_when_no_pagination_params(self):
        from orpheus_ui.api.diagnostics import get_crow_stats
        from orpheus_ui.auth.models import User

        detections = [
            self._make_crow_detection("2026-01-01T12:00:00+00:00", "caw"),
            self._make_crow_detection("2026-01-02T12:00:00+00:00", "rattle"),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_crow_stats(
                start_date="2026-01-01",
                end_date="2026-01-31",
                user=mock_user,
            )

        assert "page" not in result
        assert result["total_detections"] == 2
        assert "all_call_types" in result
        assert set(result["all_call_types"].keys()) == {"caw", "rattle"}

    def test_call_types_filter(self):
        from orpheus_ui.api.diagnostics import get_crow_stats
        from orpheus_ui.auth.models import User

        detections = [
            self._make_crow_detection("2026-01-01T12:00:00+00:00", "caw"),
            self._make_crow_detection("2026-01-02T12:00:00+00:00", "rattle"),
            self._make_crow_detection("2026-01-03T12:00:00+00:00", "caw"),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_crow_stats(
                start_date="2026-01-01",
                end_date="2026-01-31",
                call_types="caw",
                user=mock_user,
            )

        assert result["total_detections"] == 2
        assert all(d["call_type"] == "caw" for d in result["detections"])
        # all_call_types unfiltered so dropdown still shows both
        assert set(result["all_call_types"].keys()) == {"caw", "rattle"}
        # call_types (filtered distribution) only has caw
        assert set(result["call_types"].keys()) == {"caw"}

    def test_pagination_slices_detections(self):
        from orpheus_ui.api.diagnostics import get_crow_stats
        from orpheus_ui.auth.models import User

        detections = [
            self._make_crow_detection(f"2026-01-{i:02d}T12:00:00+00:00", "caw")
            for i in range(1, 11)
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            page1 = get_crow_stats(
                start_date="2026-01-01",
                end_date="2026-01-31",
                page=1,
                page_size=4,
                user=mock_user,
            )

        assert page1["page"] == 1
        assert page1["page_size"] == 4
        assert page1["total_pages"] == 3  # ceil(10/4)
        assert len(page1["detections"]) == 4
        assert page1["total_detections"] == 10


class TestTimeOfDayFilter:
    """Endpoint-level tests for the start_time/end_time/tz query params."""

    def _bird_detection(self, ts_iso):
        from datetime import datetime as _dt

        from orpheus_common.detection.models import Detection

        ts = _dt.fromisoformat(ts_iso.replace("Z", "+00:00"))
        return Detection(
            timestamp=ts,
            detection_type="species.detected",
            channel=1,
            species_code="amecro",
            species_common="American Crow",
            confidence=0.9,
            audio_clip_path=None,
        )

    def _crow_detection(self, ts_iso, call_type="caw"):
        from datetime import datetime as _dt

        from orpheus_common.detection.models import Detection

        ts = _dt.fromisoformat(ts_iso.replace("Z", "+00:00"))
        return Detection(
            timestamp=ts,
            detection_type="crow.analyzed",
            channel=1,
            confidence=0.8,
            audio_clip_path=None,
            metadata={"call_type": call_type, "attributes": {"age": "adult"}},
        )

    def _audio_event_detection(self, ts_iso, label="Bird"):
        from datetime import datetime as _dt

        from orpheus_common.detection.models import Detection

        ts = _dt.fromisoformat(ts_iso.replace("Z", "+00:00"))
        return Detection(
            timestamp=ts,
            detection_type="audio.classified",
            channel=1,
            species_code=f"audioset_{label.lower()}",
            species_common=label,
            confidence=0.7,
            audio_clip_path=None,
        )

    def _fake_db(self, detections):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [_det_to_row(d) for d in detections]
        return mock_db

    def test_birds_time_window_keeps_daytime_only(self):
        from orpheus_ui.api.diagnostics import get_bird_history
        from orpheus_ui.auth.models import User

        detections = [
            self._bird_detection("2026-03-15T03:00:00+00:00"),  # night (UTC)
            self._bird_detection("2026-03-15T10:00:00+00:00"),  # day
            self._bird_detection("2026-03-15T22:00:00+00:00"),  # night
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_bird_history(
                start_date="2026-03-15",
                end_date="2026-03-15",
                start_time="08:00",
                end_time="18:00",
                tz="UTC",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 1
        assert result["detections"][0]["timestamp"].startswith("2026-03-15T10:00")

    def test_birds_time_window_wraps_midnight(self):
        from orpheus_ui.api.diagnostics import get_bird_history
        from orpheus_ui.auth.models import User

        detections = [
            self._bird_detection("2026-03-15T03:00:00+00:00"),  # early morning
            self._bird_detection("2026-03-15T12:00:00+00:00"),  # daytime (excluded)
            self._bird_detection("2026-03-15T22:00:00+00:00"),  # evening
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_bird_history(
                start_date="2026-03-15",
                end_date="2026-03-15",
                start_time="20:00",
                end_time="06:00",  # wraps midnight
                tz="UTC",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 2
        times = {d["timestamp"][11:16] for d in result["detections"]}
        assert times == {"03:00", "22:00"}

    def test_birds_full_day_window_is_noop(self):
        from orpheus_ui.api.diagnostics import get_bird_history
        from orpheus_ui.auth.models import User

        detections = [
            self._bird_detection("2026-03-15T03:00:00+00:00"),
            self._bird_detection("2026-03-15T22:00:00+00:00"),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_bird_history(
                start_date="2026-03-15",
                end_date="2026-03-15",
                start_time="00:00",
                end_time="23:59",
                tz="UTC",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 2

    def test_crows_time_window_keeps_evening(self):
        from orpheus_ui.api.diagnostics import get_crow_stats
        from orpheus_ui.auth.models import User

        detections = [
            self._crow_detection("2026-03-15T10:00:00+00:00"),
            self._crow_detection("2026-03-15T21:00:00+00:00"),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_crow_stats(
                start_date="2026-03-15",
                end_date="2026-03-15",
                start_time="18:00",
                end_time="23:59",
                tz="UTC",
                user=mock_user,
            )

        assert result["total_detections"] == 1
        assert result["detections"][0]["timestamp"].startswith("2026-03-15T21:00")

    def test_audio_events_time_window_keeps_daytime_only(self):
        """The AudioEvents history endpoint must honour ``start_time``
        / ``end_time`` / ``tz`` the same way Birds and Crows do — this
        wasn't tested when the page shipped and a user reported the
        filter looked like it did nothing. With a real audio.classified
        fixture, the filter should keep only the row in the window."""
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._audio_event_detection("2026-03-15T03:00:00+00:00"),  # night
            self._audio_event_detection("2026-03-15T10:00:00+00:00"),  # day
            self._audio_event_detection("2026-03-15T22:00:00+00:00"),  # night
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_audio_events_history(
                start_date="2026-03-15",
                end_date="2026-03-15",
                start_time="08:00",
                end_time="18:00",
                tz="UTC",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 1
        assert result["detections"][0]["timestamp"].startswith("2026-03-15T10:00")

    def test_audio_events_time_window_wraps_midnight(self):
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._audio_event_detection("2026-03-15T03:00:00+00:00"),  # early morning
            self._audio_event_detection("2026-03-15T12:00:00+00:00"),  # daytime (excluded)
            self._audio_event_detection("2026-03-15T22:00:00+00:00"),  # evening
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_audio_events_history(
                start_date="2026-03-15",
                end_date="2026-03-15",
                start_time="20:00",
                end_time="06:00",  # wraps midnight
                tz="UTC",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 2
        times = {d["timestamp"][11:16] for d in result["detections"]}
        assert times == {"03:00", "22:00"}

    def test_audio_events_full_day_window_is_noop(self):
        from orpheus_ui.api.diagnostics import get_audio_events_history
        from orpheus_ui.auth.models import User

        detections = [
            self._audio_event_detection("2026-03-15T03:00:00+00:00"),
            self._audio_event_detection("2026-03-15T22:00:00+00:00"),
        ]
        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._fake_db(detections),
        ):
            result = get_audio_events_history(
                start_date="2026-03-15",
                end_date="2026-03-15",
                start_time="00:00",
                end_time="23:59",
                tz="UTC",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 2


class TestAudioEventsBirdCorrelationChain:
    """Regression for the cross-classifier chain join (ADR 0012).

    The Bird-Correlation-vs-BirdNET parity dashboard matches each
    audio.motion event to its bird / audio-events children via
    ``root_event_id`` (falling back to ``source_event_id``). If the
    audio.motion row isn't persisted with the SAME event_id its children
    reference, every motion event falls into "neither" — exactly what
    happened when the UI backend minted a fresh event_id on save instead
    of the audio-motion agent owning its stream. These tests pin the join
    so it can't silently regress again.
    """

    def _motion(self, event_id, ts, clip="/data/orpheus/audio/m.flac", channel=1):
        from datetime import datetime

        from orpheus_common.detection.models import Detection

        return Detection(
            event_id=event_id,
            timestamp=datetime.fromisoformat(ts),
            detection_type="audio.motion",
            channel=channel,
            audio_clip_path=clip,
            root_event_id=event_id,  # audio.motion is its own root
        )

    def _bird(self, root_event_id, ts, common="American Crow", code="corvus"):
        from datetime import datetime

        from orpheus_common.detection.models import Detection

        # species.detected is two hops down: source_event_id is the bird
        # event itself; the audio.motion is reachable via root_event_id.
        return Detection(
            event_id="bird-evt",
            timestamp=datetime.fromisoformat(ts),
            detection_type="species.detected",
            species_common=common,
            species_code=code,
            confidence=0.8,
            source_event_id="bird-evt",
            root_event_id=root_event_id,
        )

    def _audio(self, src, ts, mid="/m/015p6"):  # /m/015p6 = "Bird" (bird-like)
        from datetime import datetime

        from orpheus_common.detection.models import Detection, TaxonomyRef

        return Detection(
            event_id="audio-evt",
            timestamp=datetime.fromisoformat(ts),
            detection_type="audio.classified",
            species_code=f"audioset_{mid}",
            confidence=0.6,
            source_event_id=src,
            taxonomy=TaxonomyRef(namespace="audioset", id=mid),
        )

    def _dispatch_db(self, by_type):
        mock_db = MagicMock()
        mock_db.query_rows.side_effect = lambda *a, **k: [
            _det_to_row(d) for d in by_type.get(k.get("detection_type"), [])
        ]
        return mock_db

    def test_matching_ids_count_as_both(self):
        """A motion event with a bird child (root=M) and an audio child
        (source=M) is counted as 'both' — the fixed, joinable chain."""
        from orpheus_ui.api.diagnostics import get_audio_events_bird_correlation
        from orpheus_ui.auth.models import User

        m, ts = "motion-123", "2026-01-01T12:00:00+00:00"
        by_type = {
            "audio.motion": [self._motion(m, ts)],
            "species.detected": [self._bird(m, ts)],
            "audio.classified": [self._audio(m, ts)],
        }
        user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._dispatch_db(by_type),
        ):
            result = get_audio_events_bird_correlation(
                start_date="2026-01-01", end_date="2026-01-02", user=user
            )
        s = result["summary"]
        assert s["both_count"] == 1
        assert s["birdnet_caught_count"] == 1
        assert s["audio_events_caught_count"] == 1
        assert s["neither_count"] == 0
        assert s["parity_ratio"] == 1.0

    def test_mismatched_motion_id_is_neither(self):
        """Reproduces the pre-ADR-0012 bug: when the persisted audio.motion
        carries a different id than its children reference, the event is
        'neither' and parity collapses."""
        from orpheus_ui.api.diagnostics import get_audio_events_bird_correlation
        from orpheus_ui.auth.models import User

        ts = "2026-01-01T12:00:00+00:00"
        by_type = {
            # Persisted with a freshly-minted id (the old UI-backend bug)...
            "audio.motion": [self._motion("minted-wrong-id", ts)],
            # ...but the children reference the REAL published id.
            "species.detected": [self._bird("real-motion-id", ts)],
            "audio.classified": [self._audio("real-motion-id", ts)],
        }
        user = MagicMock(spec=User)
        with patch(
            "orpheus_ui.api.diagnostics.get_detection_db",
            return_value=self._dispatch_db(by_type),
        ):
            result = get_audio_events_bird_correlation(
                start_date="2026-01-01", end_date="2026-01-02", user=user
            )
        s = result["summary"]
        assert s["neither_count"] == 1
        assert s["both_count"] == 0
        assert s["parity_ratio"] is None


class TestEvidenceClipAvailability:
    """clip_available — preemptive "has this evidence's audio clip rolled
    off retention?" flag, computed at serialization time so the UI can show
    "Clip expired" without firing a doomed request. Computed, not stored —
    no schema change.
    """

    @staticmethod
    def _make_clip(data_root, sensor_dir, filename):
        from pathlib import Path

        clip_dir = Path(data_root) / "audio" / "audio_motion" / sensor_dir
        clip_dir.mkdir(parents=True, exist_ok=True)
        clip = clip_dir / filename
        clip.write_bytes(b"\x00")
        return clip

    def test_available_when_file_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        from orpheus_ui.api.entities import _evidence_clip_available

        self._make_clip(tmp_path, "2", "present.flac")
        # sensor_id is normalized (mic-2 -> 2); only the basename is used.
        assert (
            _evidence_clip_available(
                "mic-2", "/data/orpheus/audio/audio_motion/2/present.flac"
            )
            is True
        )

    def test_unavailable_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        from orpheus_ui.api.entities import _evidence_clip_available

        assert _evidence_clip_available("2", "gone.flac") is False

    def test_available_when_no_clip_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        from orpheus_ui.api.entities import _evidence_clip_available

        # No clip recorded → not "expired"; ClipActions shows "No clip".
        assert _evidence_clip_available("2", None) is True

    def test_empty_sensor_mirrors_channel_one_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        from orpheus_ui.api.entities import _evidence_clip_available

        # Evidence with an empty sensor_id (the model default when a Detection
        # had no context) is fetched by the frontend from channel "1"
        # (getClipUrl: channelId || '1'). The flag must mirror that fallback —
        # otherwise it checks a channel-less path that never exists and would
        # wrongly hide a clip that channel 1 can serve.
        self._make_clip(tmp_path, "1", "ch1.flac")
        assert _evidence_clip_available("", "x/ch1.flac") is True

    def test_fails_open_on_resolution_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        from orpheus_ui.api import entities

        # If path resolution blows up, never wrongly hide a playable clip.
        monkeypatch.setattr(
            entities,
            "get_audio_clip_path",
            MagicMock(side_effect=RuntimeError("boom")),
        )
        assert entities._evidence_clip_available("2", "anything.flac") is True

    def test_serialize_evidence_annotates_flag(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        from orpheus_common.detection import EntityEvidence

        from orpheus_ui.api.entities import _serialize_evidence

        self._make_clip(tmp_path, "1", "here.flac")
        evidence = [
            EntityEvidence(event_id="e1", sensor_id="1", clip_path="x/here.flac"),
            EntityEvidence(event_id="e2", sensor_id="1", clip_path="x/missing.flac"),
        ]
        out = _serialize_evidence(evidence)
        assert out[0]["clip_available"] is True
        assert out[1]["clip_available"] is False
        # model_dump still round-trips the existing fields.
        assert out[0]["event_id"] == "e1"
        assert out[1]["clip_path"] == "x/missing.flac"

    def test_serialize_evidence_skips_availability_when_not_requested(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        from orpheus_common.detection import EntityEvidence

        from orpheus_ui.api.entities import _serialize_evidence

        # The unbounded non-paginated species path (CrowEntitySection's poll)
        # never renders ClipActions, so it must NOT pay a stat() per row.
        evidence = [EntityEvidence(event_id="e1", sensor_id="1", clip_path="x/a.flac")]
        out = _serialize_evidence(evidence, with_availability=False)
        assert "clip_available" not in out[0]
        # Existing fields are still serialised.
        assert out[0]["event_id"] == "e1"


class TestEquivalenceStoreDegrade:
    """GET endpoints that consult the taxonomy-equivalence store must DEGRADE,
    not 500, when the store can't be opened (real CI incident: an unwritable
    data root made the store constructor raise ``PermissionError`` and the
    Birds page rendered blank). Writes (accept/reject/scan) still fail loud."""

    # Patched everywhere the class is bound: the UI's imported symbol (used by
    # list_equivalences + _equivalence_db_or_none), the defining module (used
    # by expand_species_filter's internal fallback), and the package re-export
    # (used by diagnostics' lazy imports).
    _STORE_BINDINGS = (
        "orpheus_ui.api.entities.TaxonomyEquivalenceDB",
        "orpheus_common.detection.equivalence.TaxonomyEquivalenceDB",
        "orpheus_common.detection.TaxonomyEquivalenceDB",
    )

    def _broken_store(self):
        import contextlib

        stack = contextlib.ExitStack()
        for binding in self._STORE_BINDINGS:
            stack.enter_context(
                patch(binding, side_effect=PermissionError(13, "Permission denied"))
            )
        return stack

    def test_list_equivalences_degrades_to_empty_not_500(self):
        from orpheus_ui.api.entities import list_equivalences
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        with self._broken_store():
            result = list_equivalences(user=mock_user)

        assert result["accepted"] == []
        assert result["pending_review"] == []
        assert result["non_equivalences"] == []
        assert result["counts"] == {
            "accepted": 0,
            "pending_review": 0,
            "non_equivalences": 0,
        }
        assert result["degraded"] is True

    @patch("orpheus_ui.api.entities._get_db")
    def test_entities_species_filter_falls_back_to_unexpanded(
        self, mock_get_db, monkeypatch
    ):
        """/api/entities?species=... with an unopenable store: 200, and the
        literal (unexpanded) species filter still applies."""
        from datetime import datetime, timezone

        from orpheus_common.detection import Entity

        from orpheus_ui.api import entities as entities_mod
        from orpheus_ui.api.entities import get_entities
        from orpheus_ui.auth.models import User

        monkeypatch.setattr(entities_mod, "_EQ_STORE_WARNED", False)

        def _ent(entity_id, species):
            return Entity(
                entity_id=entity_id,
                timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                species=species,
                common_name=species,
                confidence=0.9,
                evidence=[],
            )

        mock_get_db.return_value.get_entities.return_value = [
            _ent("e-1", "amcr"),
            _ent("e-2", "rowi"),
        ]

        mock_user = MagicMock(spec=User)
        with self._broken_store():
            result = get_entities(
                species="amcr",
                exclude_species=None,
                start_date=None,
                end_date=None,
                start_time=None,
                end_time=None,
                tz=None,
                user=mock_user,
            )

        assert result["count"] == 1  # the literal filter matched, unexpanded
        assert result["entities"][0]["entity_id"] == "e-1"

    @patch("orpheus_ui.api.diagnostics.get_detection_db")
    def test_bird_history_unaffected_by_unopenable_store(self, mock_get_db):
        """/api/data/birds/history never opens the equivalence store (species
        filtering there is literal string matching) — pinned here so a future
        equivalence integration inherits the degrade requirement: with the
        store constructor raising everywhere, the endpoint must still 200."""
        from orpheus_ui.api.diagnostics import get_bird_history
        from orpheus_ui.auth.models import User

        mock_get_db.return_value.query.return_value = []
        mock_user = MagicMock(spec=User)
        with self._broken_store():
            result = get_bird_history(
                days=None,
                start_date=None,
                end_date=None,
                species="amcr",
                start_time=None,
                end_time=None,
                tz=None,
                page=None,
                page_size=None,
                response=MagicMock(),
                user=mock_user,
            )

        assert result["count"] == 0
        assert result["detections"] == []


class TestEntityStatsScatterSampling:
    """Server-side scatter sampling must match even_sample() pick-for-pick."""

    def _make_db(self, tmp_path, n):
        import sqlite3
        from datetime import datetime, timedelta, timezone

        from orpheus_common.detection import DetectionDB

        db = DetectionDB(db_path=tmp_path / "entities.db")
        base = datetime(2026, 8, 1, tzinfo=timezone.utc)
        rows = [
            (
                f"ent_{i:05d}",
                (base + timedelta(minutes=i)).isoformat(),
                f"species_{i % 7}",
                f"Common {i % 7}",
                0.5,
            )
            for i in range(n)
        ]
        conn = sqlite3.connect(db.db_path)
        try:
            conn.executemany(
                "INSERT INTO entities "
                "(entity_id, timestamp, species, common_name, confidence) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
        return db

    def test_sampled_path_matches_even_sample_positions(self, tmp_path):
        from datetime import datetime, timedelta, timezone

        from orpheus_ui.api.entities import _compute_entity_stats

        n = 1234
        db = self._make_db(tmp_path, n)
        result = _compute_entity_stats(
            db,
            start_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        assert result["total_count"] == n
        sample = result["scatter_sample"]
        assert len(sample) == 500
        # Pick-for-pick parity with even_sample's stride (rows[int(i * step)],
        # including its documented off-by-one) over the ascending set.
        base = datetime(2026, 8, 1, tzinfo=timezone.utc)
        expected_ts = [
            (base + timedelta(minutes=int(i * (n / 500)))).isoformat()
            for i in range(500)
        ]
        assert [s["timestamp"] for s in sample] == expected_ts

    def test_small_result_returns_every_row(self, tmp_path):
        from datetime import datetime, timezone

        from orpheus_ui.api.entities import _compute_entity_stats

        db = self._make_db(tmp_path, 42)
        result = _compute_entity_stats(
            db,
            start_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        assert result["total_count"] == 42
        assert len(result["scatter_sample"]) == 42
