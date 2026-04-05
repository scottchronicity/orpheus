"""Unified configuration management for the Orpheus platform."""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Optional, Union

import yaml

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


class ConfigError(Exception):
    """Raised when the unified configuration cannot be loaded or validated."""


class Config:
    """
    Legacy configuration loader that reads YAML files with ENV overrides.

    Still used by a few components that expect per-service config files.
    Prefer :class:`OrpheusConfig` for new code.
    """

    def __init__(self, data: dict[str, Any], source: Optional[str] = None):
        self._data = data
        self._source = source or "<unknown>"

    @classmethod
    def load(cls, filename: str, service: Optional[str] = None, required: bool = True) -> Config:
        env_config_path = os.environ.get("ORPHEUS_CONFIG_PATH")
        if env_config_path:
            explicit_path = Path(env_config_path)
            if explicit_path.is_file():
                logger.info(
                    "Loading config from explicit path", filename=filename, path=explicit_path
                )
                with open(explicit_path) as f:
                    data = yaml.safe_load(f) or {}
                return cls(data, source=str(explicit_path))
            logger.warning(
                "Explicit ORPHEUS_CONFIG_PATH configured but file not found",
                path=explicit_path,
                filename=filename,
            )

        paths: list[Path] = []
        env_config_dir = os.environ.get("ORPHEUS_CONFIG_DIR")
        if env_config_dir:
            env_dir_path = Path(env_config_dir) / filename
            logger.debug("Adding ORPHEUS_CONFIG_DIR fallback", filename=filename, path=env_dir_path)
            paths.append(env_dir_path)

        if service:
            paths.append(Path(f"/etc/orpheus/{service}/{filename}"))
        else:
            paths.append(Path(f"/etc/orpheus/{filename}"))

        paths.append(Path(f"./config/{filename}"))
        paths.append(Path(f"./{filename}"))

        module_dir = Path(__file__).resolve().parent
        shared_config_dir = module_dir.parent.parent / "config"
        shared_path = shared_config_dir / filename
        logger.debug("Adding shared config fallback", filename=filename, path=shared_path)
        paths.append(shared_path)

        for path in paths:
            if path.is_file():
                logger.info("Loading config", filename=filename, path=path)
                with open(path) as f:
                    data = yaml.safe_load(f) or {}
                return cls(data, source=str(path))
            logger.debug("Config not found at path", filename=filename, path=path)

        if required:
            search_paths = [str(p) for p in paths]
            logger.error(
                "Config file not found", filename=filename, searched_paths=", ".join(search_paths)
            )
            raise FileNotFoundError(
                f"Config file '{filename}' not found in any of: {[str(p) for p in paths]}"
            )

        logger.info("No config file found; using empty configuration", filename=filename)
        return cls({}, source="<empty>")

    def get(self, key: str, default: Any = None, env_override: bool = True) -> Any:
        if env_override:
            env_value = self._get_env_override(key)
            if env_value is not None:
                return self._coerce_type(env_value, default)

        keys = key.split(".")
        value: Any = self._data

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def _get_env_override(self, key: str) -> Optional[str]:
        env_key = "ORPHEUS_" + key.replace(".", "_").upper()
        return os.environ.get(env_key)

    def _coerce_type(self, value: str, reference: Any) -> Any:
        if reference is None:
            return value

        target_type = type(reference)

        if target_type in (list, dict):
            try:
                parsed = yaml.safe_load(value)
            except yaml.YAMLError as exc:
                logger.warning(
                    "Failed to parse environment override",
                    value=value,
                    target_type=target_type.__name__,
                    error=str(exc),
                )
                return reference

            if isinstance(parsed, target_type):
                return parsed

            logger.warning(
                "Environment override produced unexpected type; using value as-is",
                produced_type=type(parsed).__name__ if parsed is not None else "None",
                expected_type=target_type.__name__,
            )
            return reference

        if target_type is bool:
            return value.lower() in ("true", "1", "yes", "on")
        if target_type is int:
            return int(value)
        if target_type is float:
            return float(value)
        return value

    def get_all(self) -> dict[str, Any]:
        return self._data.copy()

    def source(self) -> str:
        return self._source

    def as_flat_dict(self, include_lists: bool = False) -> dict[str, Any]:
        def _flatten(prefix: str, value: Any, result: dict[str, Any]) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    dotted = f"{prefix}.{key}" if prefix else key
                    _flatten(dotted, nested, result)
            elif include_lists and isinstance(value, list):
                for index, item in enumerate(value):
                    dotted = f"{prefix}[{index}]"
                    _flatten(dotted, item, result)
            else:
                result[prefix] = value

        flattened: dict[str, Any] = {}
        _flatten("", self._data, flattened)
        return flattened

    def __repr__(self) -> str:
        return f"Config(source={self._source}, keys={list(self._data.keys())})"


def load_config(filename: str = "config.yaml", service: Optional[str] = None) -> Config:
    return Config.load(filename, service=service)


_ENV_SUB_PATTERN = re.compile(r"\$\{([^}:]+)(?::-(.*?))?\}")

_DEFAULT_MQTT_SECTION = {
    "broker_host": "localhost",
    "broker_port": 1883,
    "keepalive": 60,
    "topics": {},
    "username": None,
    "password": None,
}

_DOTENV_DEFAULT_PATHS = [
    Path("config/.env.orpheus"),
]


@dataclass
class MQTTConfig:
    broker_host: str
    broker_port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    keepalive: int = 60
    topics: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MQTTConfig:
        broker_host = data.get("broker_host")
        if not broker_host:
            raise ConfigError("mqtt.broker_host is required")

        broker_port = data.get("broker_port", 1883)
        if not isinstance(broker_port, int):
            raise ConfigError("mqtt.broker_port must be an integer")

        keepalive = data.get("keepalive", 60)
        if not isinstance(keepalive, int):
            raise ConfigError("mqtt.keepalive must be an integer")

        topics = data.get("topics") or {}
        if not isinstance(topics, dict):
            raise ConfigError("mqtt.topics must be a mapping")

        return cls(
            broker_host=str(broker_host),
            broker_port=broker_port,
            username=data.get("username"),
            password=data.get("password"),
            keepalive=keepalive,
            topics={str(k): str(v) for k, v in topics.items()},
        )


@dataclass
class AudioDetectionConfig:
    """Per-channel audio motion detection configuration."""

    algorithm: str = "adaptive_threshold"
    threshold_db: float = -30.0
    margin_db: float = 10.0
    release_threshold_db: float = -35.0
    holdoff_seconds: float = 2.0
    min_duration_seconds: float = 0.3
    max_duration_seconds: float = 30.0
    prebuffer_seconds: float = 0.5
    window_seconds: float = 30.0
    update_interval_seconds: float = 5.0
    pre_roll_seconds: int = 5

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioDetectionConfig:
        return cls(
            algorithm=str(data.get("algorithm", "adaptive_threshold")),
            threshold_db=float(data.get("threshold_db", -30.0)),
            margin_db=float(data.get("margin_db", 10.0)),
            release_threshold_db=float(data.get("release_threshold_db", -35.0)),
            holdoff_seconds=float(data.get("holdoff_seconds", 2.0)),
            min_duration_seconds=float(data.get("min_duration_seconds", 0.3)),
            max_duration_seconds=float(data.get("max_duration_seconds", 30.0)),
            prebuffer_seconds=float(data.get("prebuffer_seconds", 0.5)),
            window_seconds=float(data.get("window_seconds", 30.0)),
            update_interval_seconds=float(data.get("update_interval_seconds", 5.0)),
            pre_roll_seconds=int(data.get("pre_roll_seconds", 5)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert AudioDetectionConfig to dictionary for serialization.

        Returns:
            Dictionary representation with all fields
        """
        return {
            "algorithm": self.algorithm,
            "threshold_db": self.threshold_db,
            "margin_db": self.margin_db,
            "release_threshold_db": self.release_threshold_db,
            "holdoff_seconds": self.holdoff_seconds,
            "min_duration_seconds": self.min_duration_seconds,
            "max_duration_seconds": self.max_duration_seconds,
            "prebuffer_seconds": self.prebuffer_seconds,
            "window_seconds": self.window_seconds,
            "update_interval_seconds": self.update_interval_seconds,
            "pre_roll_seconds": self.pre_roll_seconds,
        }


@dataclass
class AudioChannel:
    id: int
    name: str
    enabled: bool = True
    device: Optional[str] = None
    sample_rate: Optional[int] = None
    chunk_size: Optional[int] = None
    format: Optional[str] = None
    detection: Optional[AudioDetectionConfig] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioChannel:
        if "id" not in data:
            raise ConfigError("audio.channels[].id is required")
        if "name" not in data:
            raise ConfigError("audio.channels[].name is required")

        channel_id = data["id"]
        if not isinstance(channel_id, int):
            raise ConfigError("audio.channels[].id must be an integer")

        name = str(data["name"])
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError("audio.channels[].enabled must be a boolean")

        device = data.get("device")
        if device is not None:
            device = str(device)

        sample_rate = data.get("sample_rate")
        if sample_rate is not None and not isinstance(sample_rate, int):
            raise ConfigError("audio.channels[].sample_rate must be an integer if provided")

        chunk_size = data.get("chunk_size")
        if chunk_size is not None and not isinstance(chunk_size, int):
            raise ConfigError("audio.channels[].chunk_size must be an integer if provided")

        fmt = data.get("format")
        if fmt is not None:
            fmt = str(fmt)

        detection = None
        if "detection" in data:
            detection = AudioDetectionConfig.from_dict(data["detection"])

        return cls(
            id=channel_id,
            name=name,
            enabled=enabled,
            device=device,
            sample_rate=sample_rate,
            chunk_size=chunk_size,
            format=fmt,
            detection=detection,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert AudioChannel to dictionary for serialization.

        Returns:
            Dictionary representation with all fields
        """
        result: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
        }
        if self.device is not None:
            result["device"] = self.device
        if self.sample_rate is not None:
            result["sample_rate"] = self.sample_rate
        if self.chunk_size is not None:
            result["chunk_size"] = self.chunk_size
        if self.format is not None:
            result["format"] = self.format
        if self.detection is not None:
            result["detection"] = self.detection.to_dict()
        return result


@dataclass
class AudioConfig:
    sample_rate: int = 48000
    chunk_size: int = 1024
    format: str = "float32"
    channels: list[AudioChannel] = field(default_factory=list)
    playback_command: str = "ffplay"  # Default to Jetson standard
    buffer_duration_ms: int = 200  # ALSA buffer size in milliseconds

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioConfig:
        sample_rate = data.get("sample_rate", 48000)
        chunk_size = data.get("chunk_size", 1024)

        if not isinstance(sample_rate, int):
            raise ConfigError("audio.sample_rate must be an integer")
        if not isinstance(chunk_size, int):
            raise ConfigError("audio.chunk_size must be an integer")

        buffer_duration_ms = data.get("buffer_duration_ms", 200)
        if not isinstance(buffer_duration_ms, int):
            raise ConfigError("audio.buffer_duration_ms must be an integer")

        fmt = data.get("format", "float32")
        playback_command = data.get("playback_command", "aplay")
        channels_data = data.get("channels", [])

        # Handle string JSON input (from environment variables)
        if isinstance(channels_data, str):
            try:
                # Strip outer quotes that may come from Make's include directive
                # Shell sourcing (. .env) strips quotes, but Make's include preserves them
                channels_data = json.loads(_strip_outer_quotes(channels_data))
            except json.JSONDecodeError as e:
                raise ConfigError(f"audio.channels string is not valid JSON: {e}")

        if not isinstance(channels_data, list):
            raise ConfigError("audio.channels must be a list")

        channels = [AudioChannel.from_dict(item) for item in channels_data]
        return cls(
            sample_rate=sample_rate,
            chunk_size=chunk_size,
            format=str(fmt),
            playback_command=str(playback_command),
            channels=channels,
            buffer_duration_ms=buffer_duration_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert AudioConfig to dictionary for serialization.

        Returns:
            Dictionary representation with all fields
        """
        return {
            "sample_rate": self.sample_rate,
            "chunk_size": self.chunk_size,
            "format": self.format,
            "playback_command": self.playback_command,
            "buffer_duration_ms": self.buffer_duration_ms,
            "channels": [channel.to_dict() for channel in self.channels],
        }


@dataclass
class VideoMotionDetectionConfig:
    """Video motion detection configuration."""

    algorithm: str = "background_subtraction"
    motion_threshold: float = 25.0
    release_threshold: float = 12.5
    holdoff_seconds: float = 2.0
    min_duration_seconds: float = 0.5
    max_duration_seconds: float = 30.0
    prebuffer_seconds: float = 1.0
    pre_roll_seconds: int = 3

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VideoMotionDetectionConfig:
        return cls(
            algorithm=str(data.get("algorithm", "background_subtraction")),
            motion_threshold=float(data.get("motion_threshold", 25.0)),
            release_threshold=float(data.get("release_threshold", 12.5)),
            holdoff_seconds=float(data.get("holdoff_seconds", 2.0)),
            min_duration_seconds=float(data.get("min_duration_seconds", 0.5)),
            max_duration_seconds=float(data.get("max_duration_seconds", 30.0)),
            prebuffer_seconds=float(data.get("prebuffer_seconds", 1.0)),
            pre_roll_seconds=int(data.get("pre_roll_seconds", 3)),
        )


@dataclass
class VideoMotionConfig:
    fps: int = 10
    width: int = 640
    height: int = 480
    detection: Optional[VideoMotionDetectionConfig] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VideoMotionConfig:
        fps = data.get("fps", 10)
        width = data.get("width", 640)
        height = data.get("height", 480)

        if not isinstance(fps, int):
            raise ConfigError("video.fps must be an integer")
        if not isinstance(width, int):
            raise ConfigError("video.width must be an integer")
        if not isinstance(height, int):
            raise ConfigError("video.height must be an integer")

        # Handle nested detection object or flat structure
        detection = None
        if "detection" in data:
            # Nested structure: { detection: { algorithm: ..., motion_threshold: ... } }
            detection = VideoMotionDetectionConfig.from_dict(data["detection"])
        elif any(
            key in data
            for key in [
                "algorithm",
                "motion_threshold",
                "release_threshold",
                "holdoff_seconds",
                "min_duration_seconds",
                "max_duration_seconds",
                "prebuffer_seconds",
            ]
        ):
            # Flat structure: { fps: 10, algorithm: ..., motion_threshold: ... }
            # Extract detection-specific fields
            detection_data = {
                k: v
                for k, v in data.items()
                if k
                in [
                    "algorithm",
                    "motion_threshold",
                    "release_threshold",
                    "holdoff_seconds",
                    "min_duration_seconds",
                    "max_duration_seconds",
                    "prebuffer_seconds",
                ]
            }
            if detection_data:
                detection = VideoMotionDetectionConfig.from_dict(detection_data)

        return cls(fps=fps, width=width, height=height, detection=detection)


@dataclass
class CameraAuth:
    username: str
    password: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CameraAuth:
        if not data:
            raise ConfigError("cameras.auth section is required when cameras are configured")

        username = data.get("username")
        password = data.get("password")

        if not username:
            raise ConfigError("cameras.auth.username is required")
        if not password:
            raise ConfigError("cameras.auth.password is required")

        return cls(username=str(username), password=str(password))


@dataclass
class SnapshotConfig:
    """Configuration for camera snapshot capture."""

    interval: str = "0"  # Interval string (e.g., "1h", "30m") or "0" to disable

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SnapshotConfig:
        interval = data.get("interval", "0")
        if interval is None:
            interval = "0"
        return cls(interval=str(interval))


@dataclass
class TimelapseConfig:
    """Configuration for timelapse generation using time-window based bucket sampling.

    The start_time specifies when timelapse generation should trigger each day.
    The timezone field determines how start_time is interpreted.

    Bucket sampling parameters:
    - lookback_window: Time window to look back for snapshots (e.g., "24h" for 24 hours)
    - sampling_interval: Time interval between sampled snapshots (e.g., "15m" for 15 minutes)
    - retention_days: Number of days to retain timelapse videos

    Attributes:
        label: Human-readable label for this timelapse (e.g., "daily", "hourly", "quick").
            Used in filename generation for disambiguation. Auto-generated from lookback_window
            if not provided.
        start_time: Time in HH:MM format (24-hour) when timelapse should be generated.
        lookback_window: Time window to sample from (e.g., "24h", "12h", "7d"). Default "24h".
        sampling_interval: Interval between sampled snapshots (e.g., "15m", "30m", "1h").
            Default "15m".
        retention_days: Number of days to retain timelapse videos. Default 90.
        clip_duration: Duration in seconds each snapshot is displayed in the video.
        timezone: Timezone for interpreting start_time. Common values:
            - "UTC" (default): Coordinated Universal Time
            - "local": System's local timezone
            - IANA timezone names like "America/Los_Angeles", "Europe/London"
    """

    label: str = ""  # Human-readable label for this timelapse
    start_time: str = "00:00"  # HH:MM format (24-hour)
    lookback_window: str = "24h"  # Time window to sample from
    sampling_interval: str = "15m"  # Interval between sampled snapshots
    retention_days: int = 90  # Days to retain timelapse videos
    clip_duration: float = 2.0  # Duration of each clip in seconds
    timezone: str = "UTC"  # Timezone for start_time interpretation

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimelapseConfig:
        lookback_window = str(data.get("lookback_window", "24h"))

        # Label is REQUIRED — every timelapse must have an explicit,
        # human-readable label in the config.  The label appears in
        # filenames alongside lookback_window so both are always visible
        # for traceability (see ADR-0007).
        label = str(data.get("label", "")).strip()
        if not label:
            raise ConfigError(
                f"Timelapse config is missing required 'label' field. "
                f"Every timelapse must have an explicit label "
                f"(lookback_window={lookback_window}) "
                f"data={data}"
            )

        start_time = str(data.get("start_time", "00:00"))
        sampling_interval = str(data.get("sampling_interval", "15m"))
        retention_days = int(data.get("retention_days", 90))
        clip_duration = float(data.get("clip_duration", 2.0))
        tz = str(data.get("timezone", "UTC"))

        # Validate start_time format
        if not _is_valid_time_format(start_time):
            raise ConfigError(f"Invalid start_time format: {start_time}. Expected HH:MM")

        # Validate lookback_window format
        if not _is_valid_duration(lookback_window):
            raise ConfigError(
                f"Invalid lookback_window format: {lookback_window}. "
                f"Expected format like '24h', '7d', '30m'"
            )

        # Validate sampling_interval format
        if not _is_valid_duration(sampling_interval):
            raise ConfigError(
                f"Invalid sampling_interval format: {sampling_interval}. "
                f"Expected format like '15m', '30m', '1h'"
            )

        if retention_days < 1:
            raise ConfigError(f"retention_days must be >= 1, got {retention_days}")

        if clip_duration <= 0:
            raise ConfigError(f"clip_duration must be > 0, got {clip_duration}")

        # Validate timezone
        if not _is_valid_timezone(tz):
            raise ConfigError(
                f"Invalid timezone: {tz}. Use 'UTC', 'local', or IANA timezone names "
                f"like 'America/Los_Angeles'"
            )

        return cls(
            label=label,
            start_time=start_time,
            lookback_window=lookback_window,
            sampling_interval=sampling_interval,
            retention_days=retention_days,
            clip_duration=clip_duration,
            timezone=tz,
        )


def _is_valid_time_format(time_str: str) -> bool:
    """Validate HH:MM format (24-hour)."""
    if not re.match(r"^\d{2}:\d{2}$", time_str):
        return False
    try:
        hour, minute = map(int, time_str.split(":"))
        return 0 <= hour <= 23 and 0 <= minute <= 59
    except (ValueError, AttributeError):
        return False


def _is_valid_duration(duration_str: str) -> bool:
    """Validate duration format (e.g., '24h', '15m', '7d').

    Args:
        duration_str: Duration string to validate

    Returns:
        True if format is valid, False otherwise
    """
    pattern = r"^\d+[smhd]$"  # seconds, minutes, hours, or days
    return bool(re.match(pattern, duration_str))


def _is_valid_timezone(tz_str: str) -> bool:
    """
    Validate timezone string.

    Accepts:
        - "UTC" for Coordinated Universal Time
        - "local" for system local timezone
        - IANA timezone names like "America/Los_Angeles"

    Args:
        tz_str: Timezone string to validate

    Returns:
        True if timezone is valid, False otherwise
    """
    if tz_str in ("UTC", "local"):
        return True

    # Try to create a timezone with zoneinfo (Python 3.9+)
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz_str)
        return True
    except (KeyError, ValueError):
        return False
    except ImportError:
        # zoneinfo not available, try pytz as fallback
        try:
            import pytz

            pytz.timezone(tz_str)
            return True
        except Exception:
            pass

        # If no timezone library available, accept common patterns
        # This is a fallback for minimal environments
        if "/" in tz_str and len(tz_str) > 3:
            return True
        return False


@dataclass
class Camera:
    name: str
    type: str
    host: str
    model: str = "Unknown"
    enabled: bool = True
    rtsp_port: int = 554
    http_port: int = 80
    snapshots: Optional[SnapshotConfig] = None
    timelapses: Optional[list[TimelapseConfig]] = None

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> Camera:
        cam_type = data.get("type")
        host = data.get("host")
        if not cam_type:
            raise ConfigError(f"cameras.{name}.type is required")
        if not host:
            raise ConfigError(f"cameras.{name}.host is required")

        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"cameras.{name}.enabled must be a boolean")

        rtsp_port = data.get("rtsp_port", 554)
        http_port = data.get("http_port", 80)
        if not isinstance(rtsp_port, int) or not isinstance(http_port, int):
            raise ConfigError(f"cameras.{name}.rtsp_port/http_port must be integers")

        model = str(data.get("model", "Unknown"))

        # Parse snapshots configuration
        snapshots = None
        if "snapshots" in data:
            snapshots_data = data["snapshots"]
            if isinstance(snapshots_data, dict):
                snapshots = SnapshotConfig.from_dict(snapshots_data)

        # Parse timelapses configuration
        timelapses = None
        if "timelapses" in data:
            timelapses_data = data["timelapses"]
            if isinstance(timelapses_data, list):
                timelapses = [TimelapseConfig.from_dict(tl) for tl in timelapses_data]

        return cls(
            name=name,
            type=str(cam_type),
            host=str(host),
            model=model,
            enabled=enabled,
            rtsp_port=rtsp_port,
            http_port=http_port,
            snapshots=snapshots,
            timelapses=timelapses,
        )


@dataclass
class VideoConfig:
    auth: Optional[CameraAuth] = None
    cameras: dict[str, Camera] = field(default_factory=dict)
    motion_detection: Optional[VideoMotionConfig] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VideoConfig:
        if not data:
            return cls()

        auth_data = data.get("auth")
        auth = CameraAuth.from_dict(auth_data) if auth_data else None

        # Parse motion_detection settings if present
        motion_detection = None
        if "motion_detection" in data:
            motion_detection = VideoMotionConfig.from_dict(data["motion_detection"])

        camera_entries: dict[str, Camera] = {}
        for name, cam_data in data.items():
            if name in ("auth", "motion_detection"):
                continue
            if not isinstance(cam_data, dict):
                continue
            camera_entries[name] = Camera.from_dict(name, cam_data)

        if camera_entries and auth is None:
            raise ConfigError("cameras.auth must be provided when cameras are defined")

        return cls(auth=auth, cameras=camera_entries, motion_detection=motion_detection)

    def enabled_cameras(self) -> list[Camera]:
        return [camera for camera in self.cameras.values() if camera.enabled]


@dataclass
class StorageFormat:
    audio: str = "flac"
    video: str = "mp4"
    detections: str = "sqlite"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StorageFormat:
        return cls(
            audio=str(data.get("audio", "flac")),
            video=str(data.get("video", "mp4")),
            detections=str(data.get("detections", "sqlite")),
        )


@dataclass
class StorageRetention:
    raw_audio_days: int = 30
    raw_video_days: int = 30
    detections_days: int = 365
    max_size_gb: float = 50.0
    cleanup_trigger_percent: float = 90.0
    cleanup_amount_percent: float = 25.0
    cleanup_strategy: str = "oldest"
    check_interval_hours: float = 6.0
    min_file_age_hours: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StorageRetention:
        raw_audio = data.get("raw_audio_days", 30)
        raw_video = data.get("raw_video_days", 30)
        detections = data.get("detections_days", 365)

        for key, value in (
            ("storage.retention.raw_audio_days", raw_audio),
            ("storage.retention.raw_video_days", raw_video),
            ("storage.retention.detections_days", detections),
        ):
            if not isinstance(value, int):
                raise ConfigError(f"{key} must be an integer")

        # New cleanup policy fields with defaults
        max_size_gb = float(data.get("max_size_gb", 50.0))
        cleanup_trigger_percent = float(data.get("cleanup_trigger_percent", 90.0))
        cleanup_amount_percent = float(data.get("cleanup_amount_percent", 25.0))
        cleanup_strategy = str(data.get("cleanup_strategy", "oldest"))
        check_interval_hours = float(data.get("check_interval_hours", 6.0))
        min_file_age_hours = float(data.get("min_file_age_hours", 1.0))

        return cls(
            raw_audio_days=raw_audio,
            raw_video_days=raw_video,
            detections_days=detections,
            max_size_gb=max_size_gb,
            cleanup_trigger_percent=cleanup_trigger_percent,
            cleanup_amount_percent=cleanup_amount_percent,
            cleanup_strategy=cleanup_strategy,
            check_interval_hours=check_interval_hours,
            min_file_age_hours=min_file_age_hours,
        )


@dataclass
class StorageConfig:
    base_path: str = "/data/orpheus"
    format: StorageFormat = field(default_factory=StorageFormat)
    retention: StorageRetention = field(default_factory=StorageRetention)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StorageConfig:
        base_path = str(data.get("base_path", "/data/orpheus"))
        fmt = StorageFormat.from_dict(data.get("format", {}))
        retention = StorageRetention.from_dict(data.get("retention", {}))
        return cls(base_path=base_path, format=fmt, retention=retention)


@dataclass
class DetectionConfig:
    min_confidence: float = 0.8
    species_of_interest: list[str] = field(default_factory=list)
    audio_model: str = "birdnet"
    video_model: str = "yolo"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DetectionConfig:
        min_conf = data.get("min_confidence", 0.8)
        if not isinstance(min_conf, (int, float)):
            raise ConfigError("detection.min_confidence must be numeric")

        species = data.get("species_of_interest", [])
        if not isinstance(species, list):
            raise ConfigError("detection.species_of_interest must be a list")

        return cls(
            min_confidence=float(min_conf),
            species_of_interest=[str(item) for item in species],
            audio_model=str(data.get("audio_model", "birdnet")),
            video_model=str(data.get("video_model", "yolo")),
        )


DEFAULT_DASHBOARD_SERVICES = [
    "orpheus-dashboard",
    "orpheus-mqtt",
    "orpheus-agent-audio-motion",
    "orpheus-agent-audio-playback",
    "orpheus-agent-video-motion",
    "orpheus-agent-bird-detection",
    "orpheus-agent-crow-detection",
]


@dataclass
class DashboardConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    poll_interval: int = 5000
    services: list[str] = field(default_factory=lambda: DEFAULT_DASHBOARD_SERVICES.copy())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DashboardConfig:
        host = str(data.get("host", "0.0.0.0"))
        port = data.get("port", 8080)
        poll_interval = data.get("poll_interval", 5000)

        if not isinstance(port, int):
            raise ConfigError("dashboard.port must be an integer")
        if not isinstance(poll_interval, int):
            raise ConfigError("dashboard.poll_interval must be an integer")

        services_value = data.get("services")
        if services_value is None:
            services = DEFAULT_DASHBOARD_SERVICES.copy()
        elif isinstance(services_value, list):
            services = [str(item) for item in services_value]
        elif isinstance(services_value, str):
            services = [item.strip() for item in services_value.split(",") if item.strip()]
        else:
            raise ConfigError("dashboard.services must be a list or comma-separated string")

        return cls(host=host, port=port, poll_interval=poll_interval, services=services)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoggingConfig:
        level = str(data.get("level", "INFO"))
        fmt = str(data.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        return cls(level=level, format=fmt)


@dataclass
class HardwareConfig:
    platform: str = "auto"
    thermal_zone_path: str = "/sys/class/thermal/thermal_zone0/temp"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HardwareConfig:
        platform = str(data.get("platform", "auto"))
        thermal_zone_path = str(
            data.get("thermal_zone_path", "/sys/class/thermal/thermal_zone0/temp")
        )
        return cls(platform=platform, thermal_zone_path=thermal_zone_path)


@dataclass
class EventCorrelationConfig:
    """Configuration for the event correlator agent."""

    input_topics: list[str] = field(
        default_factory=lambda: [
            "orpheus/detection/bird/events",
            "orpheus/detection/crow/events",
        ]
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventCorrelationConfig:
        topics = data.get("input_topics")
        if topics is not None:
            if not isinstance(topics, list):
                raise ConfigError("correlation.input_topics must be a list")
            return cls(input_topics=[str(t) for t in topics])
        return cls()


@dataclass
class SiteConfig:
    """Site-level location configuration (lat, lon, elevation, name)."""

    lat: Optional[float] = None
    lon: Optional[float] = None
    elevation: Optional[float] = None
    name: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SiteConfig:
        lat = data.get("lat")
        lon = data.get("lon")
        elevation = data.get("elevation")
        name = str(data.get("name", ""))

        if lat is not None:
            lat = float(lat)
        if lon is not None:
            lon = float(lon)
        if elevation is not None:
            elevation = float(elevation)

        return cls(lat=lat, lon=lon, elevation=elevation, name=name)


def _flatten_dict(value: Any, prefix: str = "", include_lists: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, nested in value.items():
            new_prefix = f"{prefix}.{key}" if prefix else key
            result.update(_flatten_dict(nested, new_prefix, include_lists))
    elif include_lists and isinstance(value, list):
        for index, item in enumerate(value):
            new_prefix = f"{prefix}[{index}]"
            result.update(_flatten_dict(item, new_prefix, include_lists))
    else:
        result[prefix] = value
    return result


def _substitute_env_vars(value: Any) -> Any:
    if isinstance(value, str):

        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            default_value = match.group(2)
            env_value = os.environ.get(var_name)
            if env_value is not None:
                return env_value
            if default_value is not None:
                return default_value
            raise ConfigError(
                f"Environment variable ${{{var_name}}} referenced in config but not set"
            )

        return _ENV_SUB_PATTERN.sub(_replace, value)

    if isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]

    return value


def _strip_outer_quotes(value: str) -> str:
    """
    Strip matching outer quotes from a string value.

    Handles both single and double quotes. This is necessary because
    different methods of loading .env files handle quotes differently:
    - Shell sourcing (`. .env`) strips quotes before exporting
    - Make inclusion (`include .env`) preserves quotes in variables

    Args:
        value: String that may be wrapped in quotes

    Returns:
        String with outer quotes removed if they match, otherwise original

    Examples:
        >>> _strip_outer_quotes("'[1,2,3]'")
        '[1,2,3]'
        >>> _strip_outer_quotes('"hello"')
        'hello'
        >>> _strip_outer_quotes("[1,2,3]")
        '[1,2,3]'
    """
    stripped = value.strip()
    if len(stripped) >= 2:
        if (stripped.startswith("'") and stripped.endswith("'")) or (
            stripped.startswith('"') and stripped.endswith('"')
        ):
            return stripped[1:-1]
    return stripped


def _parse_env_value(value: str) -> Any:
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered in {"true", "yes", "1", "on"}:
        return True
    if lowered in {"false", "no", "0", "off"}:
        return False

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        pass

    if stripped.startswith(("[", "{")) or stripped.startswith("- ") or "\n" in stripped:
        try:
            parsed = yaml.safe_load(value)
        except yaml.YAMLError:
            return value

        if parsed is None and stripped:
            return value

        return parsed

    return value


# Backward compatibility alias for tests
_smart_cast = _parse_env_value


def _assign_nested_value(container: dict[str, Any], parts: list[str], value: Any) -> None:
    current = container
    for index, part in enumerate(parts):
        key = part.lower()
        is_last = index == len(parts) - 1
        if is_last:
            current[key] = value
            return

        next_value = current.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value


def _apply_env_overrides(
    data: dict[str, Any], *, special_keys: Optional[set] = None
) -> dict[str, Any]:
    special_keys = special_keys or set()
    for key, value in os.environ.items():
        if not key.startswith("ORPHEUS_") or key in special_keys:
            continue

        suffix = key[len("ORPHEUS_") :]
        if not suffix:
            continue

        if "__" in suffix:
            parts = [part for part in suffix.split("__") if part]
        elif "_" in suffix:
            first, rest = suffix.split("_", 1)
            parts = [first, rest]
        else:
            parts = [suffix]

        _assign_nested_value(data, parts, _parse_env_value(value))

    return data


def _load_dotenv_file(path: Path) -> None:
    try:
        with path.open() as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]
                if key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        logger.warning("Failed to read dotenv file", path=path, error=str(exc))


class OrpheusConfig:
    """Unified, typed configuration for all Orpheus components."""

    DEFAULT_CONFIG_PATHS: ClassVar[list[Path]] = [
        Path("/opt/orpheus/config/orpheus.yaml"),  # Production: centralized config
        Path("/etc/orpheus/orpheus.yaml"),  # Alternative system location
        Path("config/orpheus.yaml"),  # Development: repo config
        Path("orpheus.yaml"),  # Current directory
    ]
    _SPECIAL_ENV_KEYS: ClassVar[set] = {"ORPHEUS_CONFIG_PATH", "ORPHEUS_CONFIG_DIR"}
    _instance: ClassVar[Optional[OrpheusConfig]] = None
    _DOTENV_LOADED: ClassVar[bool] = False

    def __init__(
        self,
        *,
        config: Optional[Config] = None,
        data: Optional[dict[str, Any]] = None,
        config_source: Optional[str] = None,
        config_path: Optional[Union[str, Path]] = None,
        allow_missing: bool = False,
    ) -> None:
        self._ensure_dotenv_loaded()
        if config is not None and data is not None:
            raise ValueError("Provide either 'config' or 'data', not both.")

        strict = config is None and data is None and not allow_missing

        if data is None:
            if config is not None:
                raw_data = config.get_all()
                source = config.source()
            else:
                raw_data, source = self._load_raw_config(
                    config_path=config_path, allow_missing=allow_missing
                )
        else:
            raw_data = data
            source = config_source or "<memory>"

        normalized = self._normalize(raw_data)
        self._raw = normalized
        self._config_source = source
        mqtt_section = normalized.get("mqtt") or {}
        if not mqtt_section:
            if strict:
                raise ConfigError("mqtt section is required in orpheus.yaml")
            mqtt_section = copy.deepcopy(_DEFAULT_MQTT_SECTION)
        elif not strict:
            merged = copy.deepcopy(_DEFAULT_MQTT_SECTION)
            merged.update(mqtt_section)
            mqtt_section = merged

        self.mqtt = MQTTConfig.from_dict(mqtt_section)
        self.audio = AudioConfig.from_dict(normalized.get("audio", {}))
        self.video = VideoConfig.from_dict(normalized.get("cameras", {}))
        self.storage = StorageConfig.from_dict(normalized.get("storage", {}))
        self.detection = DetectionConfig.from_dict(normalized.get("detection", {}))
        self.dashboard = DashboardConfig.from_dict(normalized.get("dashboard", {}))
        self.logging = LoggingConfig.from_dict(normalized.get("logging", {}))
        self.hardware = HardwareConfig.from_dict(normalized.get("hardware", {}))
        self.site = SiteConfig.from_dict(normalized.get("site", {}))
        self.correlation = EventCorrelationConfig.from_dict(normalized.get("correlation", {}))

        self._camera_registry: Optional[Any] = None
        self._camera_registry_source = "uninitialized"

    @classmethod
    def load(
        cls,
        config_path: Optional[Union[str, Path]] = None,
        *,
        allow_missing: bool = False,
    ) -> OrpheusConfig:
        instance = cls(config_path=config_path, allow_missing=allow_missing)
        cls._instance = instance
        return instance

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source: str = "<dict>") -> OrpheusConfig:
        return cls(data=data, config_source=source)

    @classmethod
    def get_instance(cls, reload: bool = False, **load_kwargs: Any) -> OrpheusConfig:
        if cls._instance is None or reload:
            cls._instance = cls.load(**load_kwargs)
            logger.info("Initialized OrpheusConfig", config_source=cls._instance.config_source())
        return cls._instance

    @classmethod
    def _resolve_path(cls, candidate: Union[str, Path]) -> Path:
        path = Path(candidate).expanduser()
        if path.is_absolute():
            return path
        return (Path.cwd() / path).resolve()

    @classmethod
    def _ensure_dotenv_loaded(cls) -> None:
        if cls._DOTENV_LOADED:
            return

        dotenv_candidates: list[Path] = []
        override = os.environ.get("ORPHEUS_DOTENV_PATH")
        if override:
            dotenv_candidates.append(Path(override))
        dotenv_candidates.extend(_DOTENV_DEFAULT_PATHS)

        # Also try resolving relative paths from the config file's parent
        # directory.  When agents are launched with cwd set to their own
        # directory (e.g. agents/orpheus-agent-audio-motion), the default
        # relative candidate "config/.env.orpheus" won't resolve against
        # cwd.  Deriving the repo root from ORPHEUS_CONFIG_PATH lets us
        # find the file regardless of cwd.
        config_path_env = os.environ.get("ORPHEUS_CONFIG_PATH")
        if config_path_env:
            config_root = Path(config_path_env).resolve().parent.parent
            for default in _DOTENV_DEFAULT_PATHS:
                if not default.is_absolute():
                    alt = config_root / default
                    if alt not in dotenv_candidates:
                        dotenv_candidates.append(alt)

        for candidate in dotenv_candidates:
            resolved = cls._resolve_path(candidate)
            if resolved.is_file():
                logger.info("Loading Orpheus dotenv overrides", path=resolved)
                _load_dotenv_file(resolved)
                break

        cls._DOTENV_LOADED = True

    @classmethod
    def _load_raw_config(
        cls,
        *,
        config_path: Optional[Union[str, Path]] = None,
        allow_missing: bool = False,
    ) -> tuple[dict[str, Any], str]:
        search_paths: list[Path] = []

        if config_path:
            search_paths.append(Path(config_path))

        env_path = os.environ.get("ORPHEUS_CONFIG_PATH")
        if env_path:
            search_paths.append(Path(env_path))

        env_dir = os.environ.get("ORPHEUS_CONFIG_DIR")
        if env_dir:
            search_paths.append(Path(env_dir) / "orpheus.yaml")

        search_paths.extend(cls.DEFAULT_CONFIG_PATHS)

        module_dir = Path(__file__).resolve().parent
        shared_config = module_dir.parent.parent / "config" / "orpheus.yaml"
        search_paths.append(shared_config)

        tried: list[str] = []
        for candidate in search_paths:
            resolved = cls._resolve_path(candidate)
            tried.append(str(resolved))
            if resolved.is_file():
                logger.info("Loading Orpheus config", path=resolved)
                data = cls._read_yaml(resolved)
                return data, str(resolved)

        message = "Could not find orpheus.yaml. Checked: " + ", ".join(tried)
        if allow_missing:
            logger.warning(message)
            return {}, "<missing>"
        raise ConfigError(message)

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        try:
            with path.open() as handle:
                data = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Failed to parse YAML from {path}: {exc}")
        except OSError as exc:
            raise ConfigError(f"Failed to read configuration from {path}: {exc}")

        if not isinstance(data, dict):
            raise ConfigError(f"Configuration root in {path} must be a mapping")
        return data

    @classmethod
    def _normalize(cls, raw_data: dict[str, Any]) -> dict[str, Any]:
        copied = copy.deepcopy(raw_data)
        substituted = _substitute_env_vars(copied)
        return _apply_env_overrides(substituted, special_keys=cls._SPECIAL_ENV_KEYS)

    # ------------------------------------------------------------------
    # Typed helpers
    # ------------------------------------------------------------------
    def config_source(self) -> str:
        return self._config_source

    def get_enabled_audio_channels(self) -> list[AudioChannel]:
        return [channel for channel in self.audio.channels if channel.enabled]

    def get_enabled_cameras(self) -> list[Camera]:
        return self.video.enabled_cameras()

    def get_camera(self, name: str) -> Optional[Camera]:
        return self.video.cameras.get(name)

    # Backward compatible helpers --------------------------------------
    def mqtt_broker_host(self) -> str:
        return self.mqtt.broker_host

    def mqtt_broker_port(self) -> int:
        return self.mqtt.broker_port

    def mqtt_keepalive(self) -> int:
        return self.mqtt.keepalive

    def mqtt_username(self) -> Optional[str]:
        return self.mqtt.username

    def mqtt_password(self) -> Optional[str]:
        return self.mqtt.password

    def camera_credentials(self) -> tuple[Optional[str], Optional[str]]:
        if self.video.auth:
            return self.video.auth.username, self.video.auth.password
        return None, None

    def camera_configs(self) -> dict[str, dict[str, Any]]:
        cameras: dict[str, dict[str, Any]] = {}
        for name, cam in self.video.cameras.items():
            cam_dict: dict[str, Any] = {
                "type": cam.type,
                "host": cam.host,
                "model": cam.model,
                "enabled": cam.enabled,
                "rtsp_port": cam.rtsp_port,
                "http_port": cam.http_port,
            }
            # Include snapshots config if present
            if cam.snapshots:
                cam_dict["snapshots"] = {"interval": cam.snapshots.interval}
            # Include timelapses config if present
            if cam.timelapses:
                cam_dict["timelapses"] = [
                    {
                        "label": tl.label,
                        "start_time": tl.start_time,
                        "lookback_window": tl.lookback_window,
                        "sampling_interval": tl.sampling_interval,
                        "retention_days": tl.retention_days,
                        "clip_duration": tl.clip_duration,
                        "timezone": tl.timezone,
                    }
                    for tl in cam.timelapses
                ]
            cameras[name] = cam_dict
        return cameras

    def dashboard_host(self) -> str:
        return self.dashboard.host

    def dashboard_port(self) -> int:
        return self.dashboard.port

    def dashboard_poll_interval(self) -> int:
        return self.dashboard.poll_interval

    def dashboard_services(self) -> list[str]:
        return self.dashboard.services

    def storage_data_path(self) -> str:
        return self.storage.base_path

    def logging_level(self) -> str:
        return self.logging.level

    def logging_format(self) -> str:
        return self.logging.format

    def hardware_platform(self) -> str:
        return self.hardware.platform

    # ------------------------------------------------------------------
    def camera_registry(self, reload: bool = False):
        if self._camera_registry is None or reload:
            from orpheus_common.hardware.registry import CameraRegistry

            username, password = self.camera_credentials()
            cameras_config = self.camera_configs()
            has_yaml_config = bool(cameras_config) and bool(username) and bool(password)

            if has_yaml_config:
                logger.info("Initializing camera registry", config_source=self.config_source())
                self._camera_registry = CameraRegistry.from_config()
                self._camera_registry_source = f"config:{self.config_source()}"
            else:
                logger.warning(
                    "Camera configuration incomplete in YAML; falling back to environment"
                )
                self._camera_registry = CameraRegistry.from_env()
                self._camera_registry_source = "environment"
        return self._camera_registry

    def camera_registry_source(self) -> str:
        return self._camera_registry_source

    def to_dict(self) -> dict:
        """
        Convert config to dictionary for serialization/display.

        This shows the actual runtime config including all defaults,
        exactly as agents see it.

        Returns:
            Dictionary representation of the complete configuration
        """
        import dataclasses

        def _asdict_recursive(obj):
            if dataclasses.is_dataclass(obj):
                return {k: _asdict_recursive(v) for k, v in dataclasses.asdict(obj).items()}
            elif isinstance(obj, list):
                return [_asdict_recursive(item) for item in obj]
            elif isinstance(obj, dict):
                return {k: _asdict_recursive(v) for k, v in obj.items()}
            else:
                return obj

        # Build config dict, excluding camera registry to avoid circular refs
        result = {
            "mqtt": _asdict_recursive(self.mqtt),
            "audio": _asdict_recursive(self.audio),
            "video": _asdict_recursive(self.video),
            "storage": _asdict_recursive(self.storage),
            "detection": _asdict_recursive(self.detection),
            "dashboard": _asdict_recursive(self.dashboard),
            "logging": _asdict_recursive(self.logging),
            "hardware": _asdict_recursive(self.hardware),
        }
        return result

    def get_debug_safe_values(self) -> dict[str, dict[str, str]]:
        def sanitize_value(key: str, value: Any) -> str:
            if value is None:
                return ""
            value_str = str(value)
            lower = key.lower()
            if any(token in lower for token in ("password", "secret", "token")):
                return self._mask_value(value_str)
            return value_str

        # Use to_dict() to get runtime config with all defaults, then flatten it
        runtime_config = self.to_dict()
        orpheus_config: dict[str, str] = {"config.source": self.config_source()}
        for key, value in _flatten_dict(runtime_config, include_lists=True).items():
            display_key = key if key else "root"
            orpheus_config[display_key] = sanitize_value(display_key, value)

        effective_settings: dict[str, str] = {
            "mqtt.broker": sanitize_value("mqtt.broker", self.mqtt_broker_host()),
            "mqtt.port": sanitize_value("mqtt.port", self.mqtt_broker_port()),
            "dashboard.host": sanitize_value("dashboard.host", self.dashboard_host()),
            "dashboard.port": sanitize_value("dashboard.port", self.dashboard_port()),
            "dashboard.poll_interval": sanitize_value(
                "dashboard.poll_interval", self.dashboard_poll_interval()
            ),
            "storage.base_path": sanitize_value("storage.base_path", self.storage_data_path()),
            "hardware.platform": sanitize_value("hardware.platform", self.hardware_platform()),
        }

        username, password = self.camera_credentials()
        if username:
            effective_settings["cameras.auth.username"] = sanitize_value(
                "cameras.auth.username", username
            )
        if password:
            effective_settings["cameras.auth.password"] = self._mask_value(password)

        mqtt_username = self.mqtt_username()
        if mqtt_username:
            effective_settings["mqtt.username"] = sanitize_value("mqtt.username", mqtt_username)

        mqtt_password = self.mqtt_password()
        if mqtt_password:
            effective_settings["mqtt.password"] = self._mask_value(str(mqtt_password))

        environment_overrides: dict[str, str] = {}
        for key in sorted(k for k in os.environ if k.startswith("ORPHEUS_")):
            environment_overrides[key] = sanitize_value(key, os.environ[key])

        camera_environment: dict[str, str] = {}
        for key in sorted(k for k in os.environ if k.startswith("CAMERA_")):
            value = os.environ[key]
            if "PASS" in key.upper():
                camera_environment[key] = self._mask_value(value)
            else:
                camera_environment[key] = sanitize_value(key, value)

        camera_registry_info: dict[str, str] = {}
        try:
            registry = self.camera_registry()
            camera_registry_info["source"] = self.camera_registry_source()
            camera_registry_info["count"] = str(len(registry or []))
            if registry:
                names = sorted(
                    getattr(cam, "name", "") for cam in registry if getattr(cam, "name", "")
                )
                if names:
                    camera_registry_info["names"] = ", ".join(names)
        except Exception as exc:  # pragma: no cover - defensive logging
            camera_registry_info["error"] = str(exc)

        return {
            "orpheus_config": orpheus_config,
            "effective_settings": effective_settings,
            "environment_overrides": environment_overrides,
            "camera_environment": camera_environment,
            "camera_registry": camera_registry_info,
        }

    @staticmethod
    def _mask_value(value: str) -> str:
        return "***" + value[-4:] if len(value) > 4 else "***"
