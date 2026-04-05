"""
Storage management utilities for T7 drive.

Provides cleanup, retention policies, and space monitoring.
"""

from datetime import datetime, timedelta
from pathlib import Path

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


def cleanup_old_files(
    base_path: Path, max_age_days: int, dry_run: bool = True, pattern: str = "*"
) -> int:
    """
    Remove files older than specified age.

    Args:
        base_path: Directory to clean
        max_age_days: Maximum file age in days
        dry_run: If True, only log what would be deleted
        pattern: File pattern to match (e.g., "*.wav")

    Returns:
        Number of files deleted (or that would be deleted in dry_run)

    Example:
        >>> from orpheus_common.storage import get_audio_path, cleanup_old_files
        >>> audio_dir = get_audio_path("raw")
        >>> # Remove audio files older than 30 days
        >>> cleanup_old_files(audio_dir, max_age_days=30, dry_run=False)
    """
    if not base_path.exists():
        logger.warning("Path does not exist", base_path=base_path)
        return 0

    cutoff = datetime.now() - timedelta(days=max_age_days)
    deleted = 0

    for file_path in base_path.rglob(pattern):
        if file_path.is_file():
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

            if mtime < cutoff:
                if dry_run:
                    logger.info("Would delete file", path=file_path)
                else:
                    logger.info("Deleting file", path=file_path)
                    file_path.unlink()

                deleted += 1

    return deleted


def get_disk_usage(path: Path) -> dict:
    """
    Get disk usage statistics for path.

    Args:
        path: Path to check (typically data root)

    Returns:
        Dictionary with total, used, free, and percent

    Example:
        >>> from orpheus_common.storage import get_data_root, get_disk_usage
        >>> usage = get_disk_usage(get_data_root())
        >>> print(f"Disk {usage['percent']}% full")
    """
    import shutil

    stat = shutil.disk_usage(path)

    return {
        "total_gb": stat.total / (1024**3),
        "used_gb": stat.used / (1024**3),
        "free_gb": stat.free / (1024**3),
        "percent": (stat.used / stat.total) * 100,
    }


# Additional management functions can be added here:
# - Archive old data to network storage
# - Export datasets to HuggingFace
# - Compress old recordings
# - Generate storage reports
