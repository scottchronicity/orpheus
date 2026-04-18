"""
Time and timestamp utilities for Orpheus.

Provides standardized timestamp formatting and parsing for use across
services and agents.
"""

from datetime import datetime, timezone
from typing import Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python <3.9 fallback; should not hit on supported stacks
    ZoneInfo = None  # type: ignore[assignment]


def utc_now() -> datetime:
    """
    Get current UTC time with timezone info.

    Returns:
        Timezone-aware datetime in UTC

    Example:
        >>> from orpheus_common.utils.time import utc_now
        >>> now = utc_now()
        >>> print(now.isoformat())
        2025-11-25T12:34:56.789123+00:00
    """
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """
    Get current UTC time as ISO 8601 string with 'Z' suffix.

    Returns:
        ISO 8601 formatted timestamp string

    Example:
        >>> from orpheus_common.utils.time import utc_now_iso
        >>> timestamp = utc_now_iso()
        >>> print(timestamp)
        2025-11-25T12:34:56.789Z
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso_timestamp(timestamp: str) -> Optional[datetime]:
    """
    Parse ISO 8601 timestamp string to datetime.

    Handles both 'Z' suffix and '+00:00' timezone formats.

    Args:
        timestamp: ISO 8601 formatted timestamp

    Returns:
        Timezone-aware datetime or None if parsing fails

    Example:
        >>> from orpheus_common.utils.time import parse_iso_timestamp
        >>> dt = parse_iso_timestamp("2025-11-25T12:34:56.789Z")
        >>> print(dt.year, dt.hour)
        2025 12
    """
    try:
        # Replace 'Z' with '+00:00' for fromisoformat
        if timestamp.endswith("Z"):
            timestamp = timestamp[:-1] + "+00:00"
        return datetime.fromisoformat(timestamp)
    except (ValueError, AttributeError):
        return None


def timestamp_age_seconds(timestamp: str) -> Optional[float]:
    """
    Calculate age of timestamp in seconds from now.

    Args:
        timestamp: ISO 8601 formatted timestamp

    Returns:
        Age in seconds or None if parsing fails

    Example:
        >>> from orpheus_common.utils.time import timestamp_age_seconds
        >>> age = timestamp_age_seconds("2025-11-25T12:34:56.789Z")
        >>> print(f"Event was {age:.1f} seconds ago")
    """
    dt = parse_iso_timestamp(timestamp)
    if dt is None:
        return None

    now = datetime.now(timezone.utc)
    delta = now - dt
    return delta.total_seconds()


def parse_duration_string(duration_str: str) -> int:
    """
    Parse duration string with suffix to seconds.

    Supports suffixes: s (seconds), m (minutes), h (hours), d (days).
    If no suffix provided, assumes seconds.

    Args:
        duration_str: Duration string like "10s", "5m", "1h", "2d", or "30"

    Returns:
        Duration in seconds

    Raises:
        ValueError: If format is invalid or value cannot be parsed

    Examples:
        >>> from orpheus_common.utils.time import parse_duration_string
        >>> parse_duration_string("30s")
        30
        >>> parse_duration_string("5m")
        300
        >>> parse_duration_string("1h")
        3600
        >>> parse_duration_string("2d")
        172800
        >>> parse_duration_string("30")
        30
    """
    if duration_str is None:
        raise ValueError("duration_str cannot be None")

    if duration_str == "" or duration_str == "0":
        return 0

    duration_str = duration_str.strip().lower()

    # Check for suffix
    if duration_str[-1].isdigit():
        # No suffix, assume seconds
        try:
            return int(duration_str)
        except ValueError as e:
            raise ValueError(f"Invalid duration format: {duration_str}") from e

    # Extract number and suffix
    suffix = duration_str[-1]
    try:
        value = float(duration_str[:-1])
    except ValueError as e:
        raise ValueError(f"Invalid duration format: {duration_str}") from e

    # Convert to seconds based on suffix
    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }

    if suffix not in multipliers:
        raise ValueError(
            f"Invalid duration suffix '{suffix}'. "
            f"Valid suffixes are: s (seconds), m (minutes), h (hours), d (days)"
        )

    return int(value * multipliers[suffix])


def parse_hhmm(value: Optional[str]) -> Optional[Tuple[int, int]]:
    """Parse "HH:MM" into (hour, minute). Returns None on invalid input.

    Example:
        >>> parse_hhmm("08:30")
        (8, 30)
        >>> parse_hhmm("24:00") is None
        True
    """
    if not value:
        return None
    try:
        hour_str, minute_str = value.split(":")
        hour = int(hour_str)
        minute = int(minute_str)
    except (ValueError, AttributeError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def is_full_day(start_hhmm: Tuple[int, int], end_hhmm: Tuple[int, int]) -> bool:
    """True if the window covers the whole day (00:00..23:59 default).

    Used by callers to skip the filter entirely when the user has not
    narrowed the time window.
    """
    return start_hhmm == (0, 0) and end_hhmm == (23, 59)


def timestamp_in_window(
    ts: datetime,
    start_hhmm: Tuple[int, int],
    end_hhmm: Tuple[int, int],
    tz_name: Optional[str] = None,
) -> bool:
    """True if `ts` falls inside the HH:MM window interpreted in `tz_name`.

    Wraps midnight when start_hhmm > end_hhmm (e.g. 20:00 to 06:00 keeps
    evening of each day plus early morning of the next). If `tz_name` is
    None or invalid, the timestamp's own timezone is used.

    Example:
        >>> from datetime import datetime, timezone
        >>> ts = datetime(2026, 1, 1, 22, 30, tzinfo=timezone.utc)
        >>> timestamp_in_window(ts, (20, 0), (6, 0))  # 22:30 UTC, window 20:00-06:00 UTC
        True
    """
    local = ts
    if tz_name and ZoneInfo is not None:
        try:
            local = ts.astimezone(ZoneInfo(tz_name))
        except Exception:
            local = ts
    local_minutes = local.hour * 60 + local.minute
    start_minutes = start_hhmm[0] * 60 + start_hhmm[1]
    end_minutes = end_hhmm[0] * 60 + end_hhmm[1]
    if start_minutes <= end_minutes:
        return start_minutes <= local_minutes <= end_minutes
    return local_minutes >= start_minutes or local_minutes <= end_minutes
