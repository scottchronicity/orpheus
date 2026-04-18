"""Tests for API endpoints."""

from unittest.mock import MagicMock, patch

import pytest


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
            name="orpheus-mqtt",
            status="running",
            reason="",
        )
        assert status.name == "orpheus-mqtt"
        assert status.status == "running"

    def test_services_response_model(self):
        """Test ServicesResponse model structure."""
        from orpheus_ui.api.system import ServicesResponse, ServiceStatus

        services = [
            ServiceStatus(name="orpheus-mqtt", status="running", reason=""),
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
        mock_config.dashboard_services.return_value = ["orpheus-ui", "orpheus-mqtt"]

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
            result = get_service_logs(service_name="orpheus-mqtt", user=mock_user)

        assert result["service_name"] == "orpheus-mqtt"
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
                get_service_logs(service_name="orpheus-mqtt", user=mock_user)

        assert exc_info.value.status_code == 504

    def test_get_service_logs_empty_output(self):
        """Test service logs endpoint handles empty journalctl output."""
        from orpheus_ui.api.diagnostics import get_service_logs
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        mock_result = MagicMock()
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = get_service_logs(service_name="orpheus-mqtt", user=mock_user)

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

    @patch("orpheus_ui.api.diagnostics.DetectionDB")
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
            m = MagicMock()
            m.timestamp = datetime.fromisoformat(ts_iso).replace(tzinfo=timezone.utc)
            m.confidence = 0.8
            m.channel = 1
            m.metadata = {}
            m.context = None
            m.audio_clip_path = None
            return m

        # 1500 old detections + 1000 recent = 2500 total.
        # After truncation the table slice keeps the 1000 recent + 500 old,
        # but scatter must still span BOTH days.
        old = [make_det("2026-03-08T10:00:00+00:00") for _ in range(1500)]
        recent = [make_det("2026-03-15T10:00:00+00:00") for _ in range(1000)]
        mock_db_class.return_value.query.return_value = old + recent

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
        mock_get_db.return_value.get_entities.return_value = [target]

        mock_user = MagicMock(spec=User)
        result = get_entity_by_id(entity_id="lookup-entity", user=mock_user)

        assert result["entity_id"] == "lookup-entity"
        assert result["common_name"] == "American Crow"

    @patch("orpheus_ui.api.entities._get_db")
    def test_get_entity_by_id_not_found(self, mock_get_db):
        """Test GET /api/entities/{entity_id} returns 404 for missing entity."""
        from orpheus_ui.api.entities import get_entity_by_id
        from orpheus_ui.auth.models import User

        mock_get_db.return_value.get_entities.return_value = []

        mock_user = MagicMock(spec=User)
        with pytest.raises(Exception) as exc_info:
            get_entity_by_id(entity_id="nonexistent", user=mock_user)

        assert "404" in str(exc_info.value.status_code)

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
        mock_get_db.return_value.get_entities.return_value = [target]

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

    @patch("orpheus_ui.api.entities.sqlite3")
    def test_fetch_detection_metadata_handles_null_metadata(self, mock_sqlite3):
        """Test _fetch_detection_metadata handles NULL metadata in database."""
        from orpheus_ui.api.entities import _fetch_detection_metadata

        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Simulate row with NULL metadata
        mock_row = {"event_id": "det-1", "metadata": None}
        mock_cursor.fetchall.return_value = [mock_row]
        mock_conn.cursor.return_value = mock_cursor
        mock_sqlite3.connect.return_value = mock_conn
        mock_sqlite3.Row = dict  # For row_factory

        mock_db = MagicMock()
        mock_db.db_path = "/fake/path.db"

        result = _fetch_detection_metadata(mock_db, ["det-1"])

        # Should return empty dict for event with NULL metadata
        assert result == {"det-1": {}}

    @patch("orpheus_ui.api.entities.sqlite3")
    def test_fetch_detection_metadata_handles_malformed_json(self, mock_sqlite3):
        """Test _fetch_detection_metadata handles malformed JSON gracefully."""
        from orpheus_ui.api.entities import _fetch_detection_metadata

        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Simulate row with malformed JSON
        mock_row = {"event_id": "det-1", "metadata": "{bad json}"}
        mock_cursor.fetchall.return_value = [mock_row]
        mock_conn.cursor.return_value = mock_cursor
        mock_sqlite3.connect.return_value = mock_conn
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
        mock_db.query.return_value = detections
        return mock_db

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
            "orpheus_ui.api.diagnostics.DetectionDB",
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
            "orpheus_ui.api.diagnostics.DetectionDB",
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
            "orpheus_ui.api.diagnostics.DetectionDB",
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
            "orpheus_ui.api.diagnostics.DetectionDB",
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
            "orpheus_ui.api.diagnostics.DetectionDB",
            return_value=self._fake_db(detections),
        ):
            result = get_bird_history(
                start_date="2026-01-01",
                end_date="2026-01-31",
                user=mock_user,
            )

        assert result["stats"]["total_count"] == 1
        assert result["filtered_count"] == 1


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
        mock_db.query.return_value = detections
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
            "orpheus_ui.api.diagnostics.DetectionDB",
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
            "orpheus_ui.api.diagnostics.DetectionDB",
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
            "orpheus_ui.api.diagnostics.DetectionDB",
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

    def _fake_db(self, detections):
        mock_db = MagicMock()
        mock_db.query.return_value = detections
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
            "orpheus_ui.api.diagnostics.DetectionDB",
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
            "orpheus_ui.api.diagnostics.DetectionDB",
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
            "orpheus_ui.api.diagnostics.DetectionDB",
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
            "orpheus_ui.api.diagnostics.DetectionDB",
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
