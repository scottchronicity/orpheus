"""
Timelapse filename utilities for Orpheus.

Provides standardized filename generation and parsing for timelapse videos.
Filename format: {camera_id}.{label}.{tier}.{lookback}.{YYYYMMDD-HHMMSS}.mp4

Example: orpheus-eye-1.daily.tl0.24h.20260125-230000.mp4

Tier mapping (based on lookback window):
- tl0: 24h (daily timelapse)
- tl1: 12h (half-day timelapse)
- tl2: 6h (quarter-day timelapse)
- tl3: 1h (hourly timelapse)
- tl4: 30m (half-hour timelapse)
- tl5: 10m (10-minute timelapse)
- tl6: 1m (1-minute timelapse, for testing)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Tier to lookback window mapping
TIER_LOOKBACK_MAP: dict[str, str] = {
    "tl0": "24h",
    "tl1": "12h",
    "tl2": "6h",
    "tl3": "1h",
    "tl4": "30m",
    "tl5": "10m",
    "tl6": "1m",
}

# Reverse mapping: lookback window to tier
LOOKBACK_TIER_MAP: dict[str, str] = {v: k for k, v in TIER_LOOKBACK_MAP.items()}


def get_tier_from_lookback(lookback_window: str) -> str:
    """
    Get the tier identifier from a lookback window duration string.

    Args:
        lookback_window: Duration string like "24h", "1h", "30m", "10m", "1m"

    Returns:
        Tier identifier like "tl0", "tl1", "tl2", "tl3", "tl4"
        Falls back to "tlX" if unknown lookback window.
    """
    return LOOKBACK_TIER_MAP.get(lookback_window, "tlX")


def get_lookback_from_tier(tier: str) -> Optional[str]:
    """
    Get the lookback window duration from a tier identifier.

    Args:
        tier: Tier identifier like "tl0", "tl1", etc.

    Returns:
        Duration string like "24h", "1h", etc. or None if unknown.
    """
    return TIER_LOOKBACK_MAP.get(tier)


def get_tier_display_name(tier: str) -> str:
    """
    Get a human-readable display name for a tier.

    Args:
        tier: Tier identifier like "tl0", "tl1", etc.

    Returns:
        Human-readable string like "24 Hour", "1 Hour", etc.
    """
    display_names = {
        "tl0": "24h",
        "tl1": "12h",
        "tl2": "6h",
        "tl3": "1h",
        "tl4": "30m",
        "tl5": "10m",
        "tl6": "1m",
    }
    return display_names.get(tier, tier)


@dataclass
class TimelapseFilename:
    """Parsed timelapse filename components."""

    camera_id: str
    label: str
    tier: str
    lookback: str
    timestamp: datetime
    extension: str = "mp4"

    @property
    def filename(self) -> str:
        """Generate the filename string."""
        timestamp_str = self.timestamp.strftime("%Y%m%d-%H%M%S")
        return (
            f"{self.camera_id}.{self.label}.{self.tier}.{self.lookback}."
            f"{timestamp_str}.{self.extension}"
        )

    @property
    def tier_display(self) -> str:
        """Get human-readable tier name."""
        return get_tier_display_name(self.tier)


def generate_timelapse_filename(
    camera_id: str,
    label: str,
    lookback_window: str,
    timestamp: Optional[datetime] = None,
    extension: str = "mp4",
) -> str:
    """
    Generate a timelapse filename from components.

    Format: {camera_id}.{label}.{tier}.{lookback}.{YYYYMMDD-HHMMSS}.mp4

    Args:
        camera_id: Camera identifier (e.g., "orpheus-eye-1")
        label: Human-readable label (e.g., "daily", "hourly", "quick")
        lookback_window: Lookback duration (e.g., "24h", "1h", "30m")
        timestamp: Creation timestamp (defaults to now UTC)
        extension: File extension (default "mp4")

    Returns:
        Filename string like "orpheus-eye-1.daily.tl0.24h.20260125-230000.mp4"
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    tier = get_tier_from_lookback(lookback_window)
    timestamp_str = timestamp.strftime("%Y%m%d-%H%M%S")

    # Sanitize label to remove problematic characters
    safe_label = re.sub(r"[^a-zA-Z0-9_-]", "", label)
    if not safe_label:
        safe_label = "timelapse"

    return f"{camera_id}.{safe_label}.{tier}.{lookback_window}.{timestamp_str}.{extension}"


def parse_timelapse_filename(filename: str) -> Optional[TimelapseFilename]:
    """
    Parse a timelapse filename into its components.

    Supports new format: {camera_id}.{label}.{tier}.{lookback}.{YYYYMMDD-HHMMSS}.mp4
    Also supports legacy format: {HH-MM}.{camera_id}.mp4

    Args:
        filename: The filename to parse (with or without path)

    Returns:
        TimelapseFilename dataclass or None if parsing fails
    """
    # Get just the filename if a path was provided
    if "/" in filename or "\\" in filename:
        filename = Path(filename).name

    # Remove extension
    base_name, ext = filename.rsplit(".", 1) if "." in filename else (filename, "mp4")

    # Try new format: camera_id.label.tier.lookback.timestamp.ext
    # Pattern: camera-name.label.tlN.duration.YYYYMMDD-HHMMSS
    new_format_pattern = r"^(.+?)\.([a-zA-Z0-9_-]+)\.(tl\d+)\.(\d+[hms])\.(\d{8}-\d{6})$"
    match = re.match(new_format_pattern, base_name)
    if match:
        camera_id = match.group(1)
        label = match.group(2)
        tier = match.group(3)
        lookback = match.group(4)
        timestamp_str = match.group(5)

        try:
            timestamp = datetime.strptime(timestamp_str, "%Y%m%d-%H%M%S")
            timestamp = timestamp.replace(tzinfo=timezone.utc)
            return TimelapseFilename(
                camera_id=camera_id,
                label=label,
                tier=tier,
                lookback=lookback,
                timestamp=timestamp,
                extension=ext,
            )
        except ValueError:
            pass

    # Try legacy format: HH-MM.camera_id.ext
    legacy_pattern = r"^(\d{2})-(\d{2})\.(.+)$"
    match = re.match(legacy_pattern, base_name)
    if match:
        hour = match.group(1)
        minute = match.group(2)
        camera_id = match.group(3)

        # For legacy format, we can't determine the date from filename
        # Use a placeholder timestamp
        try:
            timestamp = datetime.now(timezone.utc).replace(
                hour=int(hour), minute=int(minute), second=0, microsecond=0
            )
            return TimelapseFilename(
                camera_id=camera_id,
                label="legacy",
                tier="tl0",  # Assume daily for legacy
                lookback="24h",
                timestamp=timestamp,
                extension=ext,
            )
        except ValueError:
            pass

    return None


def get_timelapse_path(
    storage_base: Path,
    camera_id: str,
    label: str,
    lookback_window: str,
    date_str: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> Path:
    """
    Generate the full filesystem path for a timelapse video.

    Directory structure: {storage_base}/video/timelapses/{YYYY.MM.DD}/{filename}

    Args:
        storage_base: Base storage path (e.g., /data/orpheus)
        camera_id: Camera identifier
        label: Human-readable label
        lookback_window: Lookback duration
        date_str: Date string in YYYY.MM.DD format (optional, derived from timestamp)
        timestamp: Creation timestamp (defaults to now UTC)

    Returns:
        Full Path object for the timelapse file
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    if date_str is None:
        date_str = timestamp.strftime("%Y.%m.%d")

    filename = generate_timelapse_filename(
        camera_id=camera_id,
        label=label,
        lookback_window=lookback_window,
        timestamp=timestamp,
    )

    return storage_base / "video" / "timelapses" / date_str / filename


def tier_sort_key(tier: str) -> tuple[int, str]:
    """
    Get a sort key for tier ordering.

    Orders from longest lookback (tl0 = 24h) to shortest (tl4 = 1m).

    Args:
        tier: Tier identifier like "tl0", "tl1", etc.

    Returns:
        Tuple for sorting (tier_number, tier_string)
    """
    try:
        tier_num = int(tier.replace("tl", ""))
        return (tier_num, tier)
    except (ValueError, AttributeError):
        return (999, tier)  # Unknown tiers sort last
