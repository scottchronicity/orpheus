"""
GPS Service for Orpheus - Spatiotemporal Context Provider

Reads NMEA sentences from a USB GPS dongle (VK-162) via serial port,
parses location data, and publishes to MQTT for use by detection agents.

Features:
- Direct serial NMEA parsing (no gpsd dependency)
- Retained MQTT state publishing
- Rate limiting (5m delta or 1 min heartbeat)
- Fallback to static coordinates
- Time drift detection and warning
"""

import os
import time
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Optional

import pynmea2
import serial
from orpheus_common.config import OrpheusConfig
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.mqtt import MQTTClient

logger = get_logger(__name__)


class GPSService:
    """GPS service that reads NMEA sentences and publishes location state."""

    def __init__(
        self,
        device: str = "/dev/ttyACM0",
        baud_rate: int = 9600,
        mqtt_client: Optional[MQTTClient] = None,
        static_lat: Optional[float] = None,
        static_lon: Optional[float] = None,
        static_elevation: Optional[float] = None,
    ):
        """
        Initialize GPS service.

        Args:
            device: Serial device path (default: /dev/ttyACM0)
            baud_rate: Serial baud rate (default: 9600)
            mqtt_client: MQTT client instance (will create if None)
            static_lat: Static latitude fallback
            static_lon: Static longitude fallback
            static_elevation: Static elevation fallback (meters)
        """
        self.device = device
        self.baud_rate = baud_rate
        self.static_lat = static_lat
        self.static_lon = static_lon
        self.static_elevation = static_elevation or 0.0

        # MQTT client
        if mqtt_client:
            self.mqtt = mqtt_client
            self._owns_mqtt = False
        else:
            config = OrpheusConfig.get_instance()
            self.mqtt = MQTTClient(
                broker_host=config.mqtt.broker_host,
                broker_port=config.mqtt.broker_port,
                client_id="orpheus-gps",
            )
            self._owns_mqtt = True

        # State tracking
        self.last_location: Optional[dict] = None
        self.last_publish_time: float = 0.0
        self.serial_conn: Optional[serial.Serial] = None

        # Rate limiting constants
        self.MIN_DISTANCE_METERS = 5.0  # Publish if moved > 5m
        self.HEARTBEAT_SECONDS = 60.0  # Publish every 1 min regardless
        self.TIME_DRIFT_THRESHOLD = 5.0  # Warn if time drifts > 5 seconds

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate great-circle distance between two points using Haversine formula.

        Args:
            lat1, lon1: First point coordinates
            lat2, lon2: Second point coordinates

        Returns:
            Distance in meters
        """
        earth_radius_m = 6371000  # Earth radius in meters

        phi1 = radians(lat1)
        phi2 = radians(lat2)
        delta_phi = radians(lat2 - lat1)
        delta_lambda = radians(lon2 - lon1)

        a = sin(delta_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
        c = 2 * asin(sqrt(a))

        return earth_radius_m * c

    def _should_publish(self, lat: float, lon: float) -> bool:
        """
        Determine if location update should be published based on rate limiting.

        Args:
            lat: Current latitude
            lon: Current longitude

        Returns:
            True if should publish, False otherwise
        """
        now = time.time()

        # Always publish if no previous location
        if not self.last_location:
            return True

        # Heartbeat: publish if been too long since last publish
        if now - self.last_publish_time >= self.HEARTBEAT_SECONDS:
            logger.debug("Publishing due to heartbeat timeout")
            return True

        # Distance check: publish if moved significantly
        prev_lat = self.last_location.get("lat")
        prev_lon = self.last_location.get("lon")
        if prev_lat is not None and prev_lon is not None:
            distance = self._haversine_distance(prev_lat, prev_lon, lat, lon)
            if distance >= self.MIN_DISTANCE_METERS:
                logger.debug("Publishing due to distance change", distance_meters=distance)
                return True

        return False

    def _parse_gprmc(self, sentence: pynmea2.RMC) -> Optional[tuple[float, float, datetime]]:
        """
        Parse GPRMC sentence for location and time.

        Args:
            sentence: Parsed GPRMC sentence

        Returns:
            Tuple of (latitude, longitude, timestamp) or None if no fix
        """
        if not sentence.latitude or not sentence.longitude:
            return None

        if sentence.status != "A":  # 'A' = Active/Valid, 'V' = Void/Invalid
            return None

        lat = sentence.latitude
        lon = sentence.longitude

        # Combine date and time from GPRMC
        if sentence.datestamp and sentence.timestamp:
            dt = datetime.combine(sentence.datestamp, sentence.timestamp, tzinfo=timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        return (lat, lon, dt)

    def _parse_gpgga(self, sentence: pynmea2.GGA) -> Optional[tuple[float, float, float, str]]:
        """
        Parse GPGGA sentence for location, elevation, and fix quality.

        Args:
            sentence: Parsed GPGGA sentence

        Returns:
            Tuple of (latitude, longitude, elevation, fix_type) or None if no fix
        """
        if not sentence.latitude or not sentence.longitude:
            return None

        if sentence.gps_qual == 0:  # 0 = No fix
            return None

        lat = sentence.latitude
        lon = sentence.longitude
        elevation = sentence.altitude if sentence.altitude else 0.0

        # Determine fix type
        # gps_qual: 0=invalid, 1=GPS fix, 2=DGPS fix, 3-8=various enhanced fixes
        # num_sats: number of satellites used
        try:
            num_sats = int(sentence.num_sats) if sentence.num_sats else 0
        except (ValueError, TypeError):
            num_sats = 0

        if sentence.gps_qual > 0 and num_sats >= 4:
            fix_type = "3d"
        elif sentence.gps_qual > 0:
            fix_type = "2d"
        else:
            fix_type = "none"

        return (lat, lon, elevation, fix_type)

    def _check_time_drift(self, gps_time: datetime) -> None:
        """
        Check for significant drift between GPS time and system time.

        Logs a warning if drift exceeds threshold. Does not attempt to modify
        system time - that is an OS-level responsibility (chrony, ntpd, etc).

        Args:
            gps_time: GPS-provided UTC timestamp
        """
        system_time = datetime.now(timezone.utc)
        drift_seconds = abs((gps_time - system_time).total_seconds())

        if drift_seconds > self.TIME_DRIFT_THRESHOLD:
            logger.warning(
                "Significant time drift detected between GPS and system clock",
                gps_time=gps_time.isoformat(),
                system_time=system_time.isoformat(),
                drift_seconds=drift_seconds,
            )

    def _publish_location(
        self,
        lat: float,
        lon: float,
        elevation: float,
        fix: str,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Publish location to MQTT.

        Args:
            lat: Latitude
            lon: Longitude
            elevation: Elevation in meters
            fix: Fix type ("3d", "2d", "none", "static")
            timestamp: Optional timestamp (uses current time if None)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        location = {
            "lat": lat,
            "lon": lon,
            "elevation": elevation,
            "timestamp": timestamp.isoformat(),
            "fix": fix,
        }

        self.mqtt.publish("orpheus/state/location", location, retain=True)

        self.last_location = location
        self.last_publish_time = time.time()

        logger.info(
            "Published location",
            lat=lat,
            lon=lon,
            elevation=elevation,
            fix=fix,
        )

    def _publish_static_location(self) -> None:
        """Publish static fallback location."""
        if self.static_lat is None or self.static_lon is None:
            logger.warning("No static coordinates configured, cannot publish fallback")
            return

        logger.info(
            "Publishing static fallback location",
            lat=self.static_lat,
            lon=self.static_lon,
            elevation=self.static_elevation,
        )

        self._publish_location(
            lat=self.static_lat,
            lon=self.static_lon,
            elevation=self.static_elevation,
            fix="static",
        )

    def _try_open_serial(self) -> bool:
        """
        Attempt to open serial connection to GPS device.

        Returns:
            True if successful, False otherwise
        """
        if self.serial_conn and self.serial_conn.is_open:
            return True

        try:
            logger.info("Opening GPS serial device", device=self.device, baud_rate=self.baud_rate)
            self.serial_conn = serial.Serial(
                self.device,
                baudrate=self.baud_rate,
                timeout=1.0,
            )
            logger.info("GPS serial device opened successfully")
            return True
        except (serial.SerialException, FileNotFoundError, PermissionError) as e:
            logger.warning("Failed to open GPS serial device", device=self.device, error=str(e))
            return False

    def _process_nmea_line(self, line: str) -> None:
        """
        Process a single NMEA sentence line.

        Args:
            line: Raw NMEA sentence string
        """
        try:
            sentence = pynmea2.parse(line)

            # Process GPRMC for position and time
            if isinstance(sentence, pynmea2.RMC):
                result = self._parse_gprmc(sentence)
                if result:
                    lat, lon, gps_time = result
                    self._check_time_drift(gps_time)

                    # Use default elevation if we only have RMC
                    if self._should_publish(lat, lon):
                        self._publish_location(
                            lat=lat,
                            lon=lon,
                            elevation=self.last_location.get("elevation", 0.0)
                            if self.last_location
                            else 0.0,
                            fix="2d",  # RMC doesn't provide fix quality
                            timestamp=gps_time,
                        )

            # Process GPGGA for position, elevation, and fix quality
            elif isinstance(sentence, pynmea2.GGA):
                result = self._parse_gpgga(sentence)
                if result:
                    lat, lon, elevation, fix_type = result

                    if self._should_publish(lat, lon):
                        self._publish_location(
                            lat=lat,
                            lon=lon,
                            elevation=elevation,
                            fix=fix_type,
                        )

        except pynmea2.ParseError as e:
            logger.debug("Failed to parse NMEA sentence", line=line, error=str(e))
        except Exception as e:
            logger.error("Unexpected error processing NMEA sentence", line=line, error=str(e))

    def run(self) -> None:
        """Main service loop."""
        logger.info("Starting GPS service")

        # Connect MQTT
        if self._owns_mqtt:
            self.mqtt.connect()

        # Try to open serial device first
        if not self._try_open_serial():
            logger.warning("GPS device not available, using static coordinates")
            self._publish_static_location()

        try:
            while True:
                # If serial connection is not available, try to reopen periodically
                if not self.serial_conn or not self.serial_conn.is_open:
                    if not self._try_open_serial():
                        # Failed to open, check if we should publish heartbeat
                        if self.last_location and (
                            time.time() - self.last_publish_time >= self.HEARTBEAT_SECONDS
                        ):
                            # Re-publish last known location (or static) as heartbeat
                            if self.last_location.get("fix") == "static":
                                self._publish_static_location()
                            else:
                                self._publish_location(
                                    lat=self.last_location["lat"],
                                    lon=self.last_location["lon"],
                                    elevation=self.last_location["elevation"],
                                    fix=self.last_location.get("fix", "none"),
                                )
                        else:
                            # Publish static location if never published before
                            if not self.last_location:
                                self._publish_static_location()

                        # Wait before retrying
                        time.sleep(10)
                        continue

                # Read line from serial
                try:
                    line = self.serial_conn.readline().decode("ascii", errors="ignore").strip()
                    if line:
                        self._process_nmea_line(line)
                except serial.SerialException as e:
                    logger.warning("Serial read error", error=str(e))
                    # Close connection so we can try to reopen
                    if self.serial_conn:
                        try:
                            self.serial_conn.close()
                        except Exception:
                            pass
                        self.serial_conn = None
                except Exception as e:
                    logger.error("Unexpected error reading serial data", error=str(e))

        except KeyboardInterrupt:
            logger.info("GPS service stopped by user")
        finally:
            if self.serial_conn:
                try:
                    self.serial_conn.close()
                    logger.info("GPS serial connection closed")
                except Exception as e:
                    logger.warning("Error closing serial connection", error=str(e))

            if self._owns_mqtt:
                self.mqtt.disconnect()


def main() -> None:
    """Main entry point for GPS service."""
    # Setup logging
    setup_logging("orpheus-gps", level="INFO")

    # Load configuration
    try:
        OrpheusConfig.get_instance()
    except Exception as e:
        logger.error("Failed to load configuration", error=str(e))
        return

    # Get GPS device from environment or use default
    device = os.environ.get("ORPHEUS_GPS_DEVICE", "/dev/ttyACM0")

    # Get static coordinates from environment
    static_lat = os.environ.get("ORPHEUS_STATIC_LAT")
    static_lon = os.environ.get("ORPHEUS_STATIC_LON")
    static_elevation = os.environ.get("ORPHEUS_STATIC_ELEVATION")

    # Parse static coordinates
    try:
        static_lat = float(static_lat) if static_lat else None
        static_lon = float(static_lon) if static_lon else None
        static_elevation = float(static_elevation) if static_elevation else None
    except ValueError as e:
        logger.warning("Failed to parse static coordinates", error=str(e))
        static_lat = None
        static_lon = None
        static_elevation = None

    # Fall back to OrpheusConfig.site if env vars are not set
    if static_lat is None or static_lon is None:
        config = OrpheusConfig.get_instance()
        if config.site.lat is not None and config.site.lon is not None:
            static_lat = config.site.lat
            static_lon = config.site.lon
            if static_elevation is None and config.site.elevation is not None:
                static_elevation = config.site.elevation
            logger.info(
                "Using site config as static coordinate fallback",
                lat=static_lat,
                lon=static_lon,
                elevation=static_elevation,
            )

    logger.info(
        "GPS service configuration",
        device=device,
        has_static_coords=static_lat is not None and static_lon is not None,
    )

    # Create and run service
    service = GPSService(
        device=device,
        static_lat=static_lat,
        static_lon=static_lon,
        static_elevation=static_elevation,
    )

    service.run()


if __name__ == "__main__":
    main()
