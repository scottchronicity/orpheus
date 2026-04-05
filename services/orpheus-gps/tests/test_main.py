"""Tests for GPS service main module."""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pynmea2
import pytest
import serial

from orpheus_gps.main import GPSService


@pytest.fixture
def mock_mqtt_client():
    """Create a mock MQTT client."""
    client = MagicMock()
    client.publish = MagicMock()
    client.connect = MagicMock()
    client.disconnect = MagicMock()
    return client


@pytest.fixture
def gps_service(mock_mqtt_client):
    """Create GPS service with mock MQTT client."""
    return GPSService(
        device="/dev/ttyACM0",
        mqtt_client=mock_mqtt_client,
        static_lat=47.6062,
        static_lon=-122.3321,
        static_elevation=50.0,
    )


class TestHaversineDistance:
    """Tests for haversine distance calculation."""

    def test_same_location(self, gps_service):
        """Test distance between same coordinates is zero."""
        distance = gps_service._haversine_distance(47.6062, -122.3321, 47.6062, -122.3321)
        assert distance < 0.1  # Less than 10cm

    def test_known_distance(self, gps_service):
        """Test known distance between coordinates."""
        # Seattle to San Francisco is approximately 1094 km
        seattle_lat, seattle_lon = 47.6062, -122.3321
        sf_lat, sf_lon = 37.7749, -122.4194

        distance = gps_service._haversine_distance(seattle_lat, seattle_lon, sf_lat, sf_lon)

        # Should be within 10km of expected distance
        expected = 1094000  # meters
        assert abs(distance - expected) < 10000

    def test_short_distance(self, gps_service):
        """Test short distance calculation (meters)."""
        # Two points approximately 100 meters apart
        lat1, lon1 = 47.6062, -122.3321
        lat2, lon2 = 47.6071, -122.3321  # ~100m north

        distance = gps_service._haversine_distance(lat1, lon1, lat2, lon2)

        # Should be approximately 100 meters
        assert 90 < distance < 110


class TestShouldPublish:
    """Tests for rate limiting logic."""

    def test_publish_first_location(self, gps_service):
        """Test that first location is always published."""
        assert gps_service._should_publish(47.6062, -122.3321)

    def test_no_publish_within_distance_and_time(self, gps_service):
        """Test no publish when within distance and time limits."""
        # Set initial location
        gps_service.last_location = {"lat": 47.6062, "lon": -122.3321}
        gps_service.last_publish_time = time.time()

        # Try to publish same location immediately
        assert not gps_service._should_publish(47.6062, -122.3321)

    def test_publish_on_distance_change(self, gps_service):
        """Test publish when distance exceeds threshold."""
        # Set initial location
        gps_service.last_location = {"lat": 47.6062, "lon": -122.3321}
        gps_service.last_publish_time = time.time()

        # Move > 5m (0.00005 degrees ~= 5.5m at this latitude)
        assert gps_service._should_publish(47.6063, -122.3321)

    def test_publish_on_heartbeat_timeout(self, gps_service):
        """Test publish when heartbeat timeout is reached."""
        # Set initial location in the past
        gps_service.last_location = {"lat": 47.6062, "lon": -122.3321}
        gps_service.last_publish_time = time.time() - 61  # 61 seconds ago

        # Should publish even with same location
        assert gps_service._should_publish(47.6062, -122.3321)


class TestParseGPRMC:
    """Tests for GPRMC sentence parsing."""

    def test_valid_gprmc(self, gps_service):
        """Test parsing valid GPRMC sentence."""
        # $GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A
        sentence = pynmea2.parse(
            "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
        )

        result = gps_service._parse_gprmc(sentence)

        assert result is not None
        lat, lon, timestamp = result
        assert abs(lat - 48.1173) < 0.001
        assert abs(lon - 11.5167) < 0.001
        assert isinstance(timestamp, datetime)

    def test_gprmc_no_fix(self, gps_service):
        """Test GPRMC with no fix returns None."""
        # Status 'V' = void/invalid - use check=False to skip checksum
        sentence = pynmea2.parse("$GPRMC,123519,V,,,,,,,230394,003.1,W", check=False)

        result = gps_service._parse_gprmc(sentence)

        assert result is None

    def test_gprmc_empty_coordinates(self, gps_service):
        """Test GPRMC with empty coordinates returns None."""
        sentence = pynmea2.parse("$GPRMC,123519,A,,,,,022.4,084.4,230394,003.1,W", check=False)

        result = gps_service._parse_gprmc(sentence)

        assert result is None


class TestParseGPGGA:
    """Tests for GPGGA sentence parsing."""

    def test_valid_gpgga_3d_fix(self, gps_service):
        """Test parsing valid GPGGA sentence with 3D fix."""
        # $GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47
        sentence = pynmea2.parse(
            "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
        )

        result = gps_service._parse_gpgga(sentence)

        assert result is not None
        lat, lon, elevation, fix = result
        assert abs(lat - 48.1173) < 0.001
        assert abs(lon - 11.5167) < 0.001
        assert abs(elevation - 545.4) < 0.1
        assert fix == "3d"

    def test_valid_gpgga_2d_fix(self, gps_service):
        """Test parsing GPGGA with 2D fix (fewer satellites)."""
        # Only 3 satellites - 2D fix
        sentence = pynmea2.parse(
            "$GPGGA,123519,4807.038,N,01131.000,E,1,03,0.9,545.4,M,46.9,M,,*4C"
        )

        result = gps_service._parse_gpgga(sentence)

        assert result is not None
        lat, lon, elevation, fix = result
        assert fix == "2d"

    def test_gpgga_no_fix(self, gps_service):
        """Test GPGGA with no fix returns None."""
        # gps_qual = 0
        sentence = pynmea2.parse(
            "$GPGGA,123519,4807.038,N,01131.000,E,0,00,0.9,545.4,M,46.9,M,,*4E"
        )

        result = gps_service._parse_gpgga(sentence)

        assert result is None

    def test_gpgga_empty_coordinates(self, gps_service):
        """Test GPGGA with empty coordinates returns None."""
        sentence = pynmea2.parse("$GPGGA,123519,,,,,1,08,0.9,545.4,M,46.9,M,,", check=False)

        result = gps_service._parse_gpgga(sentence)

        assert result is None


class TestPublishLocation:
    """Tests for location publishing."""

    def test_publish_location_basic(self, gps_service, mock_mqtt_client):
        """Test basic location publishing."""
        gps_service._publish_location(
            lat=47.6062,
            lon=-122.3321,
            elevation=50.0,
            fix="3d",
        )

        mock_mqtt_client.publish.assert_called_once()

        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][0] == "orpheus/state/location"

        payload = call_args[0][1]
        assert payload["lat"] == 47.6062
        assert payload["lon"] == -122.3321
        assert payload["elevation"] == 50.0
        assert payload["fix"] == "3d"
        assert "timestamp" in payload

        # Check retain flag
        assert call_args[1]["retain"] is True

    def test_publish_location_updates_state(self, gps_service):
        """Test that publishing updates internal state."""
        before_time = time.time()

        gps_service._publish_location(
            lat=47.6062,
            lon=-122.3321,
            elevation=50.0,
            fix="3d",
        )

        assert gps_service.last_location is not None
        assert gps_service.last_location["lat"] == 47.6062
        assert gps_service.last_publish_time >= before_time

    def test_publish_static_location(self, gps_service, mock_mqtt_client):
        """Test publishing static fallback location."""
        gps_service._publish_static_location()

        mock_mqtt_client.publish.assert_called_once()

        payload = mock_mqtt_client.publish.call_args[0][1]
        assert payload["lat"] == 47.6062
        assert payload["lon"] == -122.3321
        assert payload["elevation"] == 50.0
        assert payload["fix"] == "static"

    def test_publish_static_location_no_coords(self, gps_service, mock_mqtt_client):
        """Test that static publish without coords logs warning."""
        gps_service.static_lat = None
        gps_service.static_lon = None

        gps_service._publish_static_location()

        # Should not publish
        mock_mqtt_client.publish.assert_not_called()


class TestTimeDrift:
    """Tests for time drift detection."""

    def test_no_drift_warning(self, gps_service):
        """Test no warning when time is synchronized."""
        gps_time = datetime.now(timezone.utc)

        # Should not raise any exception
        gps_service._check_time_drift(gps_time)

    def test_drift_warning(self, gps_service):
        """Test warning when time drifts significantly."""
        # GPS time is 10 seconds in the past
        gps_time = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - 10, tz=timezone.utc
        )

        # Should not raise exception, just log warning
        # We can't easily test structlog output, so just verify it doesn't crash
        gps_service._check_time_drift(gps_time)


class TestSerialConnection:
    """Tests for serial connection handling."""

    @patch("orpheus_gps.main.serial.Serial")
    def test_open_serial_success(self, mock_serial_class, gps_service):
        """Test successful serial connection."""
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial_class.return_value = mock_serial

        result = gps_service._try_open_serial()

        assert result is True
        assert gps_service.serial_conn is not None
        mock_serial_class.assert_called_once_with(
            "/dev/ttyACM0",
            baudrate=9600,
            timeout=1.0,
        )

    @patch("orpheus_gps.main.serial.Serial")
    def test_open_serial_failure(self, mock_serial_class, gps_service):
        """Test failed serial connection."""
        mock_serial_class.side_effect = serial.SerialException("Device not found")

        result = gps_service._try_open_serial()

        assert result is False
        assert gps_service.serial_conn is None

    @patch("orpheus_gps.main.serial.Serial")
    def test_open_serial_permission_error(self, mock_serial_class, gps_service):
        """Test serial connection with permission error."""
        mock_serial_class.side_effect = PermissionError("Access denied")

        result = gps_service._try_open_serial()

        assert result is False


class TestProcessNMEALine:
    """Tests for NMEA line processing."""

    def test_process_valid_gprmc(self, gps_service, mock_mqtt_client):
        """Test processing valid GPRMC sentence."""
        line = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"

        gps_service._process_nmea_line(line)

        # Should publish location
        mock_mqtt_client.publish.assert_called_once()
        payload = mock_mqtt_client.publish.call_args[0][1]
        assert abs(payload["lat"] - 48.1173) < 0.001

    def test_process_valid_gpgga(self, gps_service, mock_mqtt_client):
        """Test processing valid GPGGA sentence."""
        line = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"

        gps_service._process_nmea_line(line)

        # Should publish location
        mock_mqtt_client.publish.assert_called_once()
        payload = mock_mqtt_client.publish.call_args[0][1]
        assert abs(payload["lat"] - 48.1173) < 0.001
        assert abs(payload["elevation"] - 545.4) < 0.1

    def test_process_invalid_sentence(self, gps_service, mock_mqtt_client):
        """Test processing invalid NMEA sentence."""
        line = "$GPXYZ,invalid,sentence*00"

        gps_service._process_nmea_line(line)

        # Should not publish
        mock_mqtt_client.publish.assert_not_called()

    def test_process_sentence_no_fix(self, gps_service, mock_mqtt_client):
        """Test processing sentence with no fix."""
        line = "$GPRMC,123519,V,,,,,,,230394,003.1,W*75"

        gps_service._process_nmea_line(line)

        # Should not publish
        mock_mqtt_client.publish.assert_not_called()


class TestMainFunction:
    """Tests for main entry point."""

    @patch("orpheus_gps.main.GPSService")
    @patch("orpheus_gps.main.OrpheusConfig.get_instance")
    @patch.dict(
        "os.environ",
        {
            "ORPHEUS_GPS_DEVICE": "/dev/ttyUSB0",
            "ORPHEUS_STATIC_LAT": "47.6062",
            "ORPHEUS_STATIC_LON": "-122.3321",
            "ORPHEUS_STATIC_ELEVATION": "50.0",
        },
    )
    def test_main_with_env_vars(self, mock_config, mock_service_class):
        """Test main function with environment variables."""
        from orpheus_gps.main import main

        mock_config_instance = MagicMock()
        mock_config_instance.mqtt.broker_host = "localhost"
        mock_config_instance.mqtt.broker_port = 1883
        mock_config.return_value = mock_config_instance

        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        main()

        # Verify service was created with correct parameters
        mock_service_class.assert_called_once()
        call_kwargs = mock_service_class.call_args[1]
        assert call_kwargs["device"] == "/dev/ttyUSB0"
        assert call_kwargs["static_lat"] == 47.6062
        assert call_kwargs["static_lon"] == -122.3321
        assert call_kwargs["static_elevation"] == 50.0

        # Verify service was run
        mock_service.run.assert_called_once()

    @patch("orpheus_gps.main.GPSService")
    @patch("orpheus_gps.main.OrpheusConfig.get_instance")
    def test_main_with_defaults(self, mock_config, mock_service_class):
        """Test main function with default values."""
        from orpheus_gps.main import main

        mock_config_instance = MagicMock()
        mock_config_instance.mqtt.broker_host = "localhost"
        mock_config_instance.mqtt.broker_port = 1883
        mock_config_instance.site.lat = None
        mock_config_instance.site.lon = None
        mock_config_instance.site.elevation = None
        mock_config.return_value = mock_config_instance

        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        main()

        # Verify service was created with defaults
        mock_service_class.assert_called_once()
        call_kwargs = mock_service_class.call_args[1]
        assert call_kwargs["device"] == "/dev/ttyACM0"
        assert call_kwargs["static_lat"] is None
        assert call_kwargs["static_lon"] is None

    @patch("orpheus_gps.main.GPSService")
    @patch("orpheus_gps.main.OrpheusConfig.get_instance")
    def test_main_falls_back_to_site_config(self, mock_config, mock_service_class):
        """Test that main falls back to OrpheusConfig.site when env vars are not set."""
        from orpheus_gps.main import main

        mock_config_instance = MagicMock()
        mock_config_instance.mqtt.broker_host = "localhost"
        mock_config_instance.mqtt.broker_port = 1883
        mock_config_instance.site.lat = 40.7128
        mock_config_instance.site.lon = -74.0060
        mock_config_instance.site.elevation = 10.0
        mock_config.return_value = mock_config_instance

        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        main()

        # Verify service received site config values as fallback
        mock_service_class.assert_called_once()
        call_kwargs = mock_service_class.call_args[1]
        assert call_kwargs["static_lat"] == 40.7128
        assert call_kwargs["static_lon"] == -74.0060
        assert call_kwargs["static_elevation"] == 10.0
