"""
Storage utilities for Orpheus T7 external drive.

Provides standardized path construction, directory management,
cleanup, and retention policies for /data/orpheus storage.
"""

from orpheus_common.storage.cleanup import (
    CleanupPolicy,
    CleanupResult,
    DiskSpace,
    FileInfo,
    StorageCleanup,
    cleanup_old_files_by_age,
    read_disk_space,
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
from orpheus_common.storage.sweep import (
    STATE_FILENAME,
    CategoryOutcome,
    StorageSweep,
    SweepResult,
    read_state,
    write_state,
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
from orpheus_common.storage.usage import (
    DATA_ROOT_CATEGORIES,
    StorageCategory,
    measure_directory,
    survey_data_root,
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
    "DiskSpace",
    "FileInfo",
    "StorageCleanup",
    "cleanup_old_files_by_age",
    "read_disk_space",
    # Usage survey
    "DATA_ROOT_CATEGORIES",
    "StorageCategory",
    "measure_directory",
    "survey_data_root",
    # Retention sweep — the one component that deletes recordings
    "STATE_FILENAME",
    "CategoryOutcome",
    "StorageSweep",
    "SweepResult",
    "read_state",
    "write_state",
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
