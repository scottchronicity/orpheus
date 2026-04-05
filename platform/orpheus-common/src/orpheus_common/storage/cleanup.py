"""
Storage cleanup and retention policy management.

Provides automatic cleanup of old files based on configurable retention policies.
Supports multiple cleanup strategies and safety mechanisms.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


@dataclass
class FileInfo:
    """Information about a file for cleanup decisions."""

    path: Path
    size_bytes: int
    mtime: datetime
    age_hours: float

    @classmethod
    def from_path(cls, path: Path) -> FileInfo:
        """Create FileInfo from a file path."""
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime)
        age = (datetime.now() - mtime).total_seconds() / 3600
        return cls(path=path, size_bytes=stat.st_size, mtime=mtime, age_hours=age)


@dataclass
class CleanupPolicy:
    """Configuration for storage cleanup behavior."""

    max_size_gb: float = 50.0
    max_age_days: int = 90
    cleanup_strategy: Literal["oldest", "largest", "random"] = "oldest"
    cleanup_trigger_percent: float = 90.0  # Trigger cleanup at 90% full
    cleanup_amount_percent: float = 25.0  # Remove 25% when triggered
    min_file_age_hours: float = 1.0  # Never delete files younger than this
    file_pattern: str = "*"  # Pattern to match (e.g., "*.flac")

    def validate(self) -> None:
        """Validate policy configuration."""
        if self.max_size_gb <= 0:
            raise ValueError("max_size_gb must be positive")
        if self.max_age_days <= 0:
            raise ValueError("max_age_days must be positive")
        if self.cleanup_trigger_percent <= 0 or self.cleanup_trigger_percent > 100:
            raise ValueError("cleanup_trigger_percent must be between 0 and 100")
        if self.cleanup_amount_percent <= 0 or self.cleanup_amount_percent > 100:
            raise ValueError("cleanup_amount_percent must be between 0 and 100")
        if self.min_file_age_hours < 0:
            raise ValueError("min_file_age_hours must be non-negative")
        if self.cleanup_strategy not in ("oldest", "largest", "random"):
            raise ValueError("cleanup_strategy must be 'oldest', 'largest', or 'random'")


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""

    files_removed: int = 0
    bytes_freed: int = 0
    manifest_path: Optional[Path] = None
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "files_removed": self.files_removed,
            "bytes_freed": self.bytes_freed,
            "bytes_freed_mb": round(self.bytes_freed / (1024**2), 2),
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "duration_seconds": round(self.duration_seconds, 2),
            "errors": self.errors,
        }


class StorageCleanup:
    """Manage storage cleanup with configurable retention policies."""

    def __init__(self, policy: CleanupPolicy):
        """
        Initialize storage cleanup manager.

        Args:
            policy: Cleanup policy configuration
        """
        self.policy = policy
        self.policy.validate()

    def scan_directory(self, path: Path) -> list[FileInfo]:
        """
        Scan directory and collect file information.

        Args:
            path: Directory to scan

        Returns:
            List of FileInfo objects for all matching files

        Example:
            >>> cleanup = StorageCleanup(CleanupPolicy())
            >>> files = cleanup.scan_directory(Path("/data/orpheus/audio/clips"))
            >>> print(f"Found {len(files)} files")
        """
        if not path.exists():
            logger.warning("Path does not exist", path=path)
            return []

        if not path.is_dir():
            logger.warning("Path is not a directory", path=path)
            return []

        files = []
        for file_path in path.rglob(self.policy.file_pattern):
            if file_path.is_file():
                try:
                    files.append(FileInfo.from_path(file_path))
                except Exception as e:
                    logger.warning("Could not read file", file_path=file_path, error=str(e))

        logger.debug("Scanned path for files", path=path, file_count=len(files))
        return files

    def calculate_usage(self, path: Path) -> tuple[int, float]:
        """
        Calculate storage usage for a directory.

        Args:
            path: Directory to check

        Returns:
            Tuple of (used_bytes, used_percent_of_limit)

        Example:
            >>> cleanup = StorageCleanup(CleanupPolicy(max_size_gb=50))
            >>> used_bytes, used_percent = cleanup.calculate_usage(Path("/data/orpheus/audio"))
            >>> print(f"Using {used_percent:.1f}% of storage limit")
        """
        files = self.scan_directory(path)
        total_bytes = sum(f.size_bytes for f in files)
        limit_bytes = self.policy.max_size_gb * (1024**3)
        used_percent = (total_bytes / limit_bytes * 100) if limit_bytes > 0 else 0.0

        return total_bytes, used_percent

    def needs_cleanup(self, path: Path) -> bool:
        """
        Check if cleanup is needed based on policy.

        Args:
            path: Directory to check

        Returns:
            True if cleanup should be performed

        Example:
            >>> cleanup = StorageCleanup(CleanupPolicy(cleanup_trigger_percent=90))
            >>> if cleanup.needs_cleanup(Path("/data/orpheus/audio")):
            ...     print("Cleanup needed!")
        """
        _, used_percent = self.calculate_usage(path)
        return used_percent >= self.policy.cleanup_trigger_percent

    def select_files_to_delete(self, files: list[FileInfo]) -> list[FileInfo]:
        """
        Select files for deletion based on cleanup strategy.

        Args:
            files: List of candidate files

        Returns:
            List of files to delete

        Example:
            >>> policy = CleanupPolicy(cleanup_strategy="oldest", cleanup_amount_percent=25)
            >>> cleanup = StorageCleanup(policy)
            >>> files = cleanup.scan_directory(Path("/data/orpheus/audio"))
            >>> to_delete = cleanup.select_files_to_delete(files)
        """
        # Filter out files that are too young
        min_age_hours = self.policy.min_file_age_hours
        eligible = [f for f in files if f.age_hours >= min_age_hours]

        if not eligible:
            logger.info("No eligible files for deletion (all files too young)")
            return []

        # Calculate how many bytes to free
        total_bytes = sum(f.size_bytes for f in files)
        target_bytes = total_bytes * (self.policy.cleanup_amount_percent / 100)

        # Sort files based on strategy
        if self.policy.cleanup_strategy == "oldest":
            # Oldest files first (by mtime)
            eligible.sort(key=lambda f: f.mtime)
        elif self.policy.cleanup_strategy == "largest":
            # Largest files first
            eligible.sort(key=lambda f: f.size_bytes, reverse=True)
        elif self.policy.cleanup_strategy == "random":
            # Random selection (for unbiased dataset reduction)
            import random

            random.shuffle(eligible)

        # Select files until we reach target bytes
        selected = []
        freed_bytes = 0

        for file_info in eligible:
            selected.append(file_info)
            freed_bytes += file_info.size_bytes

            if freed_bytes >= target_bytes:
                break

        logger.info(
            f"Selected {len(selected)} files for deletion "
            f"({freed_bytes / (1024**2):.2f} MB) "
            f"using '{self.policy.cleanup_strategy}' strategy"
        )

        return selected

    def create_deletion_manifest(
        self, files: list[FileInfo], manifest_dir: Optional[Path] = None
    ) -> Path:
        """
        Create CSV manifest of files to be deleted.

        Args:
            files: Files that will be deleted
            manifest_dir: Directory to store manifest (defaults to /tmp)

        Returns:
            Path to manifest file

        Example:
            >>> cleanup = StorageCleanup(CleanupPolicy())
            >>> files_to_delete = [...]
            >>> manifest = cleanup.create_deletion_manifest(files_to_delete)
            >>> print(f"Manifest: {manifest}")
        """
        if manifest_dir is None:
            manifest_dir = Path("/tmp")

        manifest_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        manifest_path = manifest_dir / f"orpheus_cleanup_{timestamp}.csv"

        with open(manifest_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["path", "size_bytes", "mtime", "age_hours"])

            for file_info in files:
                writer.writerow(
                    [
                        str(file_info.path),
                        file_info.size_bytes,
                        file_info.mtime.isoformat(),
                        round(file_info.age_hours, 2),
                    ]
                )

        logger.info("Created deletion manifest", manifest_path=manifest_path)
        return manifest_path

    def cleanup(
        self,
        path: Path,
        dry_run: bool = True,
        manifest_dir: Optional[Path] = None,
    ) -> CleanupResult:
        """
        Perform cleanup operation.

        Args:
            path: Directory to clean
            dry_run: If True, don't actually delete files
            manifest_dir: Directory to store deletion manifest

        Returns:
            CleanupResult with operation details

        Example:
            >>> policy = CleanupPolicy(max_size_gb=50, cleanup_trigger_percent=90)
            >>> cleanup = StorageCleanup(policy)
            >>> result = cleanup.cleanup(Path("/data/orpheus/audio"), dry_run=False)
            >>> print(f"Freed {result.bytes_freed / (1024**2):.2f} MB")
        """
        start_time = time.time()
        result = CleanupResult()

        try:
            # Check if cleanup is needed
            if not self.needs_cleanup(path):
                logger.info("Cleanup not needed (usage below trigger threshold)")
                result.duration_seconds = time.time() - start_time
                return result

            # Scan and select files
            all_files = self.scan_directory(path)
            files_to_delete = self.select_files_to_delete(all_files)

            if not files_to_delete:
                logger.info("No files selected for deletion")
                result.duration_seconds = time.time() - start_time
                return result

            # Create manifest
            manifest_path = self.create_deletion_manifest(files_to_delete, manifest_dir)
            result.manifest_path = manifest_path

            # Delete files
            for file_info in files_to_delete:
                try:
                    if dry_run:
                        logger.info("[DRY RUN] Would delete file", path=file_info.path)
                    else:
                        file_info.path.unlink()
                        logger.info("Deleted file", path=file_info.path)

                    result.files_removed += 1
                    result.bytes_freed += file_info.size_bytes

                except Exception as e:
                    error_msg = f"Failed to delete {file_info.path}: {e}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)

            result.duration_seconds = time.time() - start_time

            logger.info(
                f"Cleanup complete: {result.files_removed} files, "
                f"{result.bytes_freed / (1024**2):.2f} MB freed, "
                f"{result.duration_seconds:.2f}s"
            )

        except Exception as e:
            error_msg = f"Cleanup failed: {e}"
            logger.exception(error_msg)
            result.errors.append(error_msg)
            result.duration_seconds = time.time() - start_time

        return result


def cleanup_old_files_by_age(
    path: Path, max_age_days: int, dry_run: bool = True, pattern: str = "*"
) -> int:
    """
    Simple age-based cleanup utility.

    This is a convenience function for the common case of removing files
    older than a certain age, regardless of storage usage.

    Args:
        path: Directory to clean
        max_age_days: Maximum file age in days
        dry_run: If True, don't actually delete files
        pattern: File pattern to match

    Returns:
        Number of files deleted (or that would be deleted)

    Example:
        >>> from orpheus_common.storage.cleanup import cleanup_old_files_by_age
        >>> deleted = cleanup_old_files_by_age(
        ...     Path("/data/orpheus/audio/clips"),
        ...     max_age_days=90,
        ...     dry_run=False
        ... )
    """
    if not path.exists():
        logger.warning("Path does not exist", path=path)
        return 0

    cutoff = datetime.now() - timedelta(days=max_age_days)
    deleted = 0

    for file_path in path.rglob(pattern):
        if file_path.is_file():
            try:
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

                if mtime < cutoff:
                    if dry_run:
                        logger.info("[DRY RUN] Would delete file", path=file_path)
                    else:
                        file_path.unlink()
                        logger.info("Deleted file", path=file_path)

                    deleted += 1

            except Exception as e:
                logger.error("Failed to process file", path=file_path, error=str(e))

    return deleted
