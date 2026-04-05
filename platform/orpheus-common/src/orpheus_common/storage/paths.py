"""
Path utilities for Orpheus T7 external storage.

All file operations should use these utilities to ensure consistent
directory structure across agents and services.
"""

import os
from datetime import date
from pathlib import Path
from typing import Optional, Union

# Default data root (can be overridden by environment variable)
DEFAULT_DATA_ROOT = Path("/data/orpheus")


def get_data_root() -> Path:
    """
    Get the root data directory for Orpheus storage.

    Resolution order:
      1. ORPHEUS_DATA_ROOT environment variable (Docker/CI override)
      2. OrpheusConfig storage.base_path (from YAML)
      3. Default /data/orpheus

    Returns:
        Path to data root

    Example:
        >>> get_data_root()
        PosixPath('/data/orpheus')
    """
    # Env var wins (Docker, CI, manual override)
    env_root = os.environ.get("ORPHEUS_DATA_ROOT")
    if env_root:
        return Path(os.path.expanduser(env_root))

    # Fall back to OrpheusConfig (YAML)
    try:
        from orpheus_common.config import OrpheusConfig

        config = OrpheusConfig.get_instance()
        base = config.storage.base_path
        if base:
            expanded = os.path.expanduser(os.path.expandvars(base))
            return Path(expanded)
    except Exception:
        pass

    return DEFAULT_DATA_ROOT


def get_data_path(*parts: str) -> Path:
    """
    Construct path under data root.

    Args:
        *parts: Path components to join

    Returns:
        Complete path under data root

    Example:
        >>> get_data_path("audio", "raw")
        PosixPath('/data/orpheus/audio/raw')
        >>> get_data_path("models", "birdnet", "v2.4")
        PosixPath('/data/orpheus/models/birdnet/v2.4')
    """
    return get_data_root().joinpath(*parts)


def get_audio_path(
    category: str = "raw", recording_date: Optional[date] = None, channel: Optional[int] = None
) -> Path:
    """
    Get standardized audio storage path.

    Structure: /data/orpheus/audio/<category>/<date>/<channel>/

    Args:
        category: Audio category (raw, processed, clips, etc.)
        recording_date: Date of recording (defaults to today)
        channel: Microphone channel number (1-4)

    Returns:
        Audio storage path

    Example:
        >>> get_audio_path("raw", date(2025, 11, 25), channel=1)
        PosixPath('/data/orpheus/audio/raw/2025-11-25/channel_1')
        >>> get_audio_path("clips")
        PosixPath('/data/orpheus/audio/clips/2025-11-25')
    """
    parts = ["audio", category]

    if recording_date:
        parts.append(recording_date.isoformat())
    elif recording_date is None and (category in ["raw", "clips"]):
        # Default to today for timestamped categories
        parts.append(date.today().isoformat())

    if channel is not None:
        parts.append(f"channel_{channel}")

    return get_data_path(*parts)


def get_video_path(
    category: str = "raw", recording_date: Optional[date] = None, camera: Optional[str] = None
) -> Path:
    """
    Get standardized video storage path.

    Structure: /data/orpheus/video/<category>/<date>/<camera>/

    Args:
        category: Video category (raw, processed, clips, snapshots, etc.)
        recording_date: Date of recording (defaults to today)
        camera: Camera identifier (north, south, east, west)

    Returns:
        Video storage path

    Example:
        >>> get_video_path("raw", date(2025, 11, 25), camera="north")
        PosixPath('/data/orpheus/video/raw/2025-11-25/north')
        >>> get_video_path("snapshots")
        PosixPath('/data/orpheus/video/snapshots/2025-11-25')
    """
    parts = ["video", category]

    if recording_date:
        parts.append(recording_date.isoformat())
    elif recording_date is None and (category in ["raw", "clips", "snapshots"]):
        parts.append(date.today().isoformat())

    if camera is not None:
        parts.append(camera)

    return get_data_path(*parts)


def get_detections_path(filename: str = "orpheus.db") -> Path:
    """
    Get path to detections database or related files.

    Args:
        filename: Database or file name

    Returns:
        Path to detections file

    Example:
        >>> get_detections_path()
        PosixPath('/data/orpheus/detections/orpheus.db')
        >>> get_detections_path("backup.db")
        PosixPath('/data/orpheus/detections/backup.db')
    """
    return get_data_path("detections", filename)


def ensure_directory(path: Union[str, Path], mode: int = 0o755) -> Path:
    """
    Ensure directory exists with proper permissions.

    Creates parent directories as needed. Safe to call multiple times.

    Args:
        path: Directory path to create
        mode: Directory permissions (default: 0o755)

    Returns:
        Path object for created directory

    Example:
        >>> audio_dir = get_audio_path("raw", date.today(), channel=1)
        >>> ensure_directory(audio_dir)
        PosixPath('/data/orpheus/audio/raw/2025-11-25/channel_1')
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    return path


def normalize_sensor_id(sensor_id: str) -> str:
    """
    Normalize sensor ID to its numeric component.

    Strips common prefixes like "mic-" or "channel_" to get the raw numeric ID.
    This provides compatibility between legacy numeric IDs and new string-based IDs
    from the Entity Correlator.

    Args:
        sensor_id: Sensor identifier (e.g., "1", "mic-1", "channel_1")

    Returns:
        Normalized numeric ID (e.g., "1")

    Example:
        >>> normalize_sensor_id("1")
        '1'
        >>> normalize_sensor_id("mic-1")
        '1'
        >>> normalize_sensor_id("channel_1")
        '1'
    """
    sensor_id = str(sensor_id)

    # Strip common prefixes
    if sensor_id.startswith("mic-"):
        return sensor_id[4:]
    elif sensor_id.startswith("channel_"):
        return sensor_id[8:]

    return sensor_id


def get_audio_clip_path(category: str, sensor_id: str, filename: str) -> Path:
    """
    Get path to an audio clip file with automatic sensor ID normalization.

    Constructs the full path to an audio clip, normalizing the sensor ID
    to handle both legacy numeric formats and new string-based formats.

    Structure: /data/orpheus/audio/<category>/<normalized_sensor_id>/<filename>

    Args:
        category: Audio category (e.g., "audio_motion")
        sensor_id: Sensor identifier (e.g., "1", "mic-1", "channel_1")
        filename: Name of the audio file

    Returns:
        Full path to the audio clip file

    Example:
        >>> get_audio_clip_path("audio_motion", "mic-1", "20260217T151656.flac")
        PosixPath('/data/orpheus/audio/audio_motion/1/20260217T151656.flac')
        >>> get_audio_clip_path("audio_motion", "1", "20260217T151656.flac")
        PosixPath('/data/orpheus/audio/audio_motion/1/20260217T151656.flac')
    """
    normalized_id = normalize_sensor_id(sensor_id)
    base_path = get_audio_path(category=category)
    return base_path / normalized_id / filename


def get_file_path(category: str, filename: str, **kwargs) -> Path:
    """
    Construct full file path with automatic directory structure.

    Args:
        category: Storage category (audio, video, models, etc.)
        filename: Name of file
        **kwargs: Additional path components (date, channel, camera, etc.)

    Returns:
        Complete file path

    Example:
        >>> get_file_path("audio", "clip_001.wav",
        ...               recording_date=date.today(), channel=1)
        PosixPath('/data/orpheus/audio/raw/2025-11-25/channel_1/clip_001.wav')
    """
    if category == "audio":
        base_path = get_audio_path(**kwargs)
    elif category == "video":
        base_path = get_video_path(**kwargs)
    elif category == "detections":
        return get_detections_path(filename)
    else:
        base_path = get_data_path(category)

    return base_path / filename
