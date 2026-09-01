"""
Storage cleanup and retention policy management.

Provides automatic cleanup of old files based on configurable retention policies.
Supports multiple cleanup strategies and safety mechanisms.
"""

from __future__ import annotations

import csv
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Optional

from orpheus_common.logging import get_logger

logger = get_logger(__name__)

# How far past the low-space threshold a backstop sweep recovers. Stopping
# exactly at the threshold means the next few writes cross it again and the
# guard fires every check interval; a proportional margin buys headroom that
# scales with the disk instead of a fixed number that is huge on a small one
# and meaningless on a large one.
FREE_SPACE_RECOVERY_FACTOR = 1.2


@dataclass
class DiskSpace:
    """A filesystem's capacity, as seen from one directory on it."""

    total_bytes: int
    free_bytes: int

    @property
    def free_percent(self) -> float:
        if self.total_bytes <= 0:
            return 100.0
        return self.free_bytes / self.total_bytes * 100


def read_disk_space(path: Path) -> Optional[DiskSpace]:
    """Capacity of the filesystem holding ``path``, or ``None`` if unreadable."""
    try:
        usage = shutil.disk_usage(path)
    except OSError as e:
        logger.warning("Could not read free space", path=path, error=str(e))
        return None
    return DiskSpace(total_bytes=usage.total, free_bytes=usage.free)


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
    # Last-resort guard on the FILESYSTEM rather than this directory's budget.
    # Every directory can sit under its own size budget while the shared disk
    # fills anyway — the budgets are per-directory and the disk is not. 0
    # disables the guard and restores purely budget-driven cleanup.
    min_free_space_percent: float = 10.0

    @classmethod
    def from_storage_retention(
        cls, retention: Any, *, max_age_days: int, file_pattern: str = "*"
    ) -> CleanupPolicy:
        """Build a policy from an ``OrpheusConfig.storage.retention`` (``StorageRetention``).

        The consolidation point so an agent honors the operator's ``storage.retention.*``
        knobs instead of hand-rolling ``getattr(..., default)`` reads (which silently fell
        back to hardcoded defaults because the agent-local config never carried the fields).
        ``retention`` is duck-typed to avoid a config→storage import cycle. ``max_age_days``
        is supplied by the caller (audio agents pass ``raw_audio_days``, video agents
        ``raw_video_days``); ``file_pattern`` scopes the sweep (e.g. ``"*.flac"``)."""
        return cls(
            max_size_gb=retention.max_size_gb,
            max_age_days=max_age_days,
            cleanup_strategy=retention.cleanup_strategy,
            cleanup_trigger_percent=retention.cleanup_trigger_percent,
            cleanup_amount_percent=retention.cleanup_amount_percent,
            min_file_age_hours=retention.min_file_age_hours,
            file_pattern=file_pattern,
            min_free_space_percent=getattr(retention, "min_free_space_percent", 10.0),
        )

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
        if self.min_free_space_percent < 0 or self.min_free_space_percent >= 100:
            raise ValueError("min_free_space_percent must be between 0 and 100")
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
    # The window of recording that disappeared, ISO-8601. Carried on the
    # result — not only in the log line — so whatever reports the sweep can
    # say WHAT was removed, not just how much.
    oldest_removed: Optional[str] = None
    newest_removed: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "files_removed": self.files_removed,
            "bytes_freed": self.bytes_freed,
            "bytes_freed_mb": round(self.bytes_freed / (1024**2), 2),
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "duration_seconds": round(self.duration_seconds, 2),
            "errors": self.errors,
            "oldest_removed": self.oldest_removed,
            "newest_removed": self.newest_removed,
        }


class StorageCleanup:
    """Manage storage cleanup with configurable retention policies."""

    def __init__(
        self,
        policy: CleanupPolicy,
        *,
        disk_space: Optional[Callable[[Path], Optional[DiskSpace]]] = None,
    ):
        """
        Initialize storage cleanup manager.

        Args:
            policy: Cleanup policy configuration
            disk_space: Reads the capacity of the filesystem holding a path.
                Injectable so the free-space guard can be exercised without
                filling a real disk.
        """
        self.policy = policy
        self.policy.validate()
        self._disk_space = disk_space or read_disk_space

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
        if self.free_space_shortfall(path) is not None:
            return True
        _, used_percent = self.calculate_usage(path)
        return used_percent >= self.policy.cleanup_trigger_percent

    def free_space_shortfall(self, path: Path) -> Optional[tuple[DiskSpace, int]]:
        """How far the filesystem is below its low-space threshold.

        Returns ``(space, bytes_to_free)`` when the disk holding ``path`` has
        less than ``min_free_space_percent`` left, otherwise ``None``. The
        target clears the threshold by ``FREE_SPACE_RECOVERY_FACTOR`` so the
        guard does not re-fire on the next handful of writes.

        This is deliberately independent of the directory's own size budget:
        several directories share one disk, so each can be well inside its
        budget while the disk itself runs out.
        """
        if self.policy.min_free_space_percent <= 0:
            return None

        space = self._disk_space(path)
        if space is None or space.total_bytes <= 0:
            return None
        if space.free_percent >= self.policy.min_free_space_percent:
            return None

        target_percent = min(
            self.policy.min_free_space_percent * FREE_SPACE_RECOVERY_FACTOR, 100.0
        )
        target_free_bytes = space.total_bytes * target_percent / 100
        return space, int(target_free_bytes - space.free_bytes)

    def select_files_for_free_space(
        self, files: list[FileInfo], bytes_needed: int
    ) -> list[FileInfo]:
        """Oldest files first, until ``bytes_needed`` is covered.

        Always oldest-first regardless of ``cleanup_strategy``: this runs when
        the disk is nearly full, and the predictable thing to lose is the
        oldest recording, not the largest or a random one.
        """
        eligible = [f for f in files if f.age_hours >= self.policy.min_file_age_hours]
        eligible.sort(key=lambda f: f.mtime)

        selected: list[FileInfo] = []
        freed_bytes = 0
        for file_info in eligible:
            if freed_bytes >= bytes_needed:
                break
            selected.append(file_info)
            freed_bytes += file_info.size_bytes

        return selected

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

    def report(
        self, path: Path, last_result: Optional[CleanupResult] = None
    ) -> dict[str, Any]:
        """What this pass knows about ``path``, as a publishable dict.

        The component that sweeps is the one that already walks the directory
        and already holds the policy, so it is the honest source for "how
        close is this to being deleted". Anything else asking the same
        question — a dashboard, an operator — would be duplicating the walk
        and inventing a second source of truth for the policy.

        ``last_result`` folds in the sweep that just ran, so a reader can see
        not only the pressure but whether anything acted on it.

        This is the *policy* view only. How much space each directory is
        using — including the ones no policy covers — comes from
        :func:`orpheus_common.storage.usage.survey_data_root`, and the disk
        reading comes with it. Reporting the disk from both places would put
        two timestamps on one number for no gain.
        """
        used_bytes, percent_of_limit = self.calculate_usage(path)
        guard_enabled = self.policy.min_free_space_percent > 0

        report: dict[str, Any] = {
            "path": str(path),
            "measured_at": datetime.now().astimezone().isoformat(),
            "file_pattern": self.policy.file_pattern,
            "bytes": used_bytes,
            "limit_bytes": int(self.policy.max_size_gb * (1024**3)),
            "percent_of_limit": round(percent_of_limit, 1),
            "trigger_percent": self.policy.cleanup_trigger_percent,
            "min_free_space_percent": self.policy.min_free_space_percent,
            "guard_enabled": guard_enabled,
            # True when the low-disk guard would fire right now — the
            # condition that overrides the directory's own budget.
            "guard_tripped": self.free_space_shortfall(path) is not None,
            "last_sweep": None,
        }

        if last_result is not None and last_result.files_removed > 0:
            report["last_sweep"] = {
                "at": report["measured_at"],
                "files_removed": last_result.files_removed,
                "bytes_freed": last_result.bytes_freed,
                "oldest_removed": last_result.oldest_removed,
                "newest_removed": last_result.newest_removed,
            }

        return report

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
            # The free-space guard is checked first: it overrides the
            # directory's own budget, because a directory can sit comfortably
            # inside its budget while the shared disk runs out underneath it.
            shortfall = self.free_space_shortfall(path)

            if shortfall is None and not self.needs_cleanup(path):
                logger.info("Cleanup not needed (usage below trigger threshold)")
                result.duration_seconds = time.time() - start_time
                return result

            all_files = self.scan_directory(path)

            if shortfall is not None:
                space, bytes_needed = shortfall
                logger.warning(
                    "Low disk space — running last-resort cleanup, oldest first. "
                    "This directory is not over its own size budget; the "
                    "filesystem it lives on is nearly full.",
                    path=str(path),
                    free_percent=round(space.free_percent, 2),
                    min_free_space_percent=self.policy.min_free_space_percent,
                    free_gb=round(space.free_bytes / (1024**3), 2),
                    total_gb=round(space.total_bytes / (1024**3), 2),
                    bytes_needed=bytes_needed,
                    bytes_needed_gb=round(bytes_needed / (1024**3), 2),
                )
                files_to_delete = self.select_files_for_free_space(all_files, bytes_needed)
            else:
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

            if result.files_removed > 0:
                removed_window = [f.mtime for f in files_to_delete]
                result.oldest_removed = min(removed_window).isoformat()
                result.newest_removed = max(removed_window).isoformat()

            if shortfall is not None and files_to_delete:
                # The operator must be able to reconstruct what disappeared and
                # why without guessing: the window removed, how much it bought,
                # and where free space ended up.
                removed_mtimes = [f.mtime for f in files_to_delete]
                space_after = self._disk_space(path)
                logger.warning(
                    "Low-disk cleanup complete",
                    path=str(path),
                    files_removed=result.files_removed,
                    bytes_freed=result.bytes_freed,
                    gb_freed=round(result.bytes_freed / (1024**3), 2),
                    oldest_removed=min(removed_mtimes).isoformat(),
                    newest_removed=max(removed_mtimes).isoformat(),
                    free_percent_after=(
                        round(space_after.free_percent, 2) if space_after else None
                    ),
                    min_free_space_percent=self.policy.min_free_space_percent,
                    dry_run=dry_run,
                    manifest_path=str(result.manifest_path) if result.manifest_path else None,
                )
            else:
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
