"""
Storage utilities for Orpheus T7 external drive.

Provides standardized path construction, directory management,
cleanup, and retention policies for /data/orpheus storage.
"""

from orpheus_common.storage.cleanup import (
    CleanupPolicy,
    CleanupResult,
    FileInfo,
    StorageCleanup,
    cleanup_old_files_by_age,
)
from orpheus_common.storage.paths import (
    ensure_directory,
    get_audio_clip_path,
    get_audio_path,
    get_data_path,
    get_data_root,
    get_detections_path,
    get_video_path,
    normalize_sensor_id,
)
from orpheus_common.storage.timelapse import (
    LOOKBACK_TIER_MAP,
    TIER_LOOKBACK_MAP,
    TimelapseFilename,
    generate_timelapse_filename,
    get_lookback_from_tier,
    get_tier_display_name,
    get_tier_from_lookback,
    get_timelapse_path,
    parse_timelapse_filename,
    tier_sort_key,
)

__all__ = [
    # Path utilities
    "get_data_root",
    "get_data_path",
    "get_audio_path",
    "get_video_path",
    "get_detections_path",
    "get_audio_clip_path",
    "normalize_sensor_id",
    "ensure_directory",
    # Cleanup utilities
    "CleanupPolicy",
    "CleanupResult",
    "FileInfo",
    "StorageCleanup",
    "cleanup_old_files_by_age",
    # Timelapse utilities
    "TIER_LOOKBACK_MAP",
    "LOOKBACK_TIER_MAP",
    "TimelapseFilename",
    "generate_timelapse_filename",
    "parse_timelapse_filename",
    "get_timelapse_path",
    "get_tier_from_lookback",
    "get_lookback_from_tier",
    "get_tier_display_name",
    "tier_sort_key",
]
