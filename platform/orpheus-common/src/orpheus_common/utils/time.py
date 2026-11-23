"""
Time and timestamp utilities for Orpheus.

Provides standardized timestamp formatting and parsing for use across
services and agents.
"""

from datetime import datetime, timedelta, timezone
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


def to_zone(ts: datetime, tz_name: Optional[str] = None) -> datetime:
    """``ts`` converted into ``tz_name``; unchanged if the zone is missing or bad.

    The companion to :func:`timestamp_in_window` for the aggregate side: a chart
    that groups by hour or day must bucket in the SAME zone the window filter
    used, or an evening-local selection lands on a different hour than the one
    the viewer asked for.
    """
    if not tz_name or ZoneInfo is None:
        return ts
    try:
        return ts.astimezone(ZoneInfo(tz_name))
    except Exception:
        return ts


# Earliest instant the DST search covers when a caller gives no range start.
_TZ_SEARCH_FROM = datetime(2015, 1, 1, tzinfo=timezone.utc)


def _as_utc(value: object) -> Optional[datetime]:
    """``value`` (datetime or ISO string, naive meaning UTC) in UTC, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _offset_minutes(zone: "ZoneInfo", instant: datetime) -> int:
    offset = instant.astimezone(zone).utcoffset()
    return int(offset.total_seconds() // 60) if offset is not None else 0


def sqlite_tz_modifier(
    column: str,
    tz_name: Optional[str] = None,
    range_start: object = None,
    range_end: object = None,
) -> Tuple[Optional[str], list]:
    """A SQLite ``strftime()`` modifier expression shifting UTC-stored ``column``
    into ``tz_name``, with its params; ``(None, [])`` for UTC or an unknown zone.

    The offset is the one in effect at each row's own instant: the expression is
    a ``CASE`` over the zone's UTC-offset changes (DST) between ``range_start``
    and ``range_end`` (datetimes or ISO strings; defaults 2015 and now), so a
    window or bucket over a range that crosses a DST change, or a past season
    viewed in another, matches :func:`timestamp_in_window` row for row.
    ``column`` is interpolated and must be a trusted identifier.
    """
    if not tz_name or tz_name.upper() == "UTC" or ZoneInfo is None:
        return None, []
    try:
        zone = ZoneInfo(tz_name)
    except Exception:
        return None, []
    lo = (_as_utc(range_start) or _TZ_SEARCH_FROM) - timedelta(days=1)
    hi = (_as_utc(range_end) or datetime.now(timezone.utc)) + timedelta(days=1)
    first = _offset_minutes(zone, lo)
    changes: list = []  # (first UTC instant of the new offset, new offset)
    current, t = first, lo
    while t < hi:
        nxt = min(t + timedelta(days=1), hi)
        after = _offset_minutes(zone, nxt)
        if after != current:
            a, b = t, nxt  # offset at a is `current`, at b is `after`
            while b - a > timedelta(seconds=1):
                mid = a + (b - a) / 2
                if _offset_minutes(zone, mid) == current:
                    a = mid
                else:
                    b = mid
            changes.append((b, after))
            current = after
        t = nxt
    if not changes:
        return "?", [f"{first} minutes"]
    sql, params, offset = "CASE", [], first
    for instant, after in changes:
        # Offsets change on whole seconds, so truncating to the second gives
        # the exact boundary; stored timestamps compare as ISO strings.
        sql += f" WHEN {column} < ? THEN ?"
        params += [instant.strftime("%Y-%m-%dT%H:%M:%S"), f"{offset} minutes"]
        offset = after
    params.append(f"{offset} minutes")
    return sql + " ELSE ? END", params


def sqlite_time_window_sql(
    column: str,
    start_hhmm: Tuple[int, int],
    end_hhmm: Tuple[int, int],
    tz_name: Optional[str] = None,
    range_start: object = None,
    range_end: object = None,
) -> Tuple[str, list]:
    """SQL predicate + params restricting ``column`` to an HH:MM window in ``tz_name``.

    The SQL counterpart of :func:`timestamp_in_window`, with the same semantics
    including the midnight wrap (``start > end`` keeps the evening of each day
    plus the early morning of the next). Returns ``("", [])`` for a full day, so
    a caller can append unconditionally.

    This exists because filtering in Python meant LOADING the range to filter it:
    a 30-day page with an hour-long window built every row in the range as an
    object and then threw almost all of them away (~45s). In SQL the window is
    just part of the WHERE, so the database returns the page directly.

    ``column`` is interpolated into the SQL and must be a trusted identifier
    supplied by the caller, never user input.
    """
    if is_full_day(start_hhmm, end_hhmm):
        return "", []
    modifier, mparams = sqlite_tz_modifier(column, tz_name, range_start, range_end)
    expr = (
        f"strftime('%H:%M', {column}, {modifier})" if modifier else f"strftime('%H:%M', {column})"
    )
    start_str = f"{start_hhmm[0]:02d}:{start_hhmm[1]:02d}"
    end_str = f"{end_hhmm[0]:02d}:{end_hhmm[1]:02d}"
    params: list = []
    if start_hhmm <= end_hhmm:
        # Params in placeholder order: the modifier sits inside the expression.
        params.extend(mparams)
        params.extend([start_str, end_str])
        return f"({expr} BETWEEN ? AND ?)", params
    # Wrapping window: the expression appears twice, so its modifier does too.
    if modifier:
        params.extend([*mparams, start_str, *mparams, end_str])
    else:
        params.extend([start_str, end_str])
    return f"({expr} >= ? OR {expr} <= ?)", params


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


def interruptible_sleep(
    total_seconds: float,
    sleep,
    should_stop,
    slice_seconds: float = 1.0,
) -> None:
    """Sleep ``total_seconds`` in short slices, polling ``should_stop`` between
    them. A single ``time.sleep(interval)`` is auto-resumed after a signal
    handler returns (PEP 475), so a flag-setting SIGINT/SIGTERM handler cannot
    interrupt it — Ctrl-C/systemd stop would appear dead for up to the full
    interval (and a unit stop would hit TimeoutStopSec -> SIGKILL). Slicing
    keeps the injectable ``sleep`` seam and bounds stop latency to
    ~``slice_seconds``.
    """
    remaining = float(total_seconds)
    while remaining > 0 and not should_stop():
        chunk = min(slice_seconds, remaining)
        sleep(chunk)
        remaining -= chunk
