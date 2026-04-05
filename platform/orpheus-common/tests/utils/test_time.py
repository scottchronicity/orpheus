"""Tests for orpheus_common.utils.time module."""

import time as time_module
from datetime import datetime, timedelta, timezone

import pytest

from orpheus_common.utils.time import (
    parse_duration_string,
    parse_iso_timestamp,
    timestamp_age_seconds,
    utc_now,
    utc_now_iso,
)


class TestUtcNow:
    """Tests for utc_now function."""

    def test_returns_datetime(self) -> None:
        """utc_now should return a datetime object."""
        result = utc_now()
        assert isinstance(result, datetime)

    def test_has_timezone_info(self) -> None:
        """utc_now should return timezone-aware datetime."""
        result = utc_now()
        assert result.tzinfo is not None
        assert result.tzinfo == timezone.utc

    def test_is_current_time(self) -> None:
        """utc_now should return approximately the current time."""
        before = datetime.now(timezone.utc)
        result = utc_now()
        after = datetime.now(timezone.utc)

        assert before <= result <= after


class TestUtcNowIso:
    """Tests for utc_now_iso function."""

    def test_returns_string(self) -> None:
        """utc_now_iso should return a string."""
        result = utc_now_iso()
        assert isinstance(result, str)

    def test_ends_with_z(self) -> None:
        """utc_now_iso should return timestamp ending with Z."""
        result = utc_now_iso()
        assert result.endswith("Z")

    def test_is_valid_iso_format(self) -> None:
        """utc_now_iso should return valid ISO 8601 format."""
        result = utc_now_iso()
        # Should be parseable
        parsed = parse_iso_timestamp(result)
        assert parsed is not None


class TestParseIsoTimestamp:
    """Tests for parse_iso_timestamp function."""

    def test_parses_z_suffix(self) -> None:
        """parse_iso_timestamp should handle 'Z' suffix."""
        result = parse_iso_timestamp("2025-11-25T12:34:56.789Z")
        assert result is not None
        assert result.year == 2025
        assert result.month == 11
        assert result.day == 25
        assert result.hour == 12
        assert result.minute == 34

    def test_parses_plus_00_00_suffix(self) -> None:
        """parse_iso_timestamp should handle '+00:00' suffix."""
        result = parse_iso_timestamp("2025-11-25T12:34:56.789+00:00")
        assert result is not None
        assert result.year == 2025

    def test_parses_without_microseconds(self) -> None:
        """parse_iso_timestamp should handle timestamps without microseconds."""
        result = parse_iso_timestamp("2025-11-25T12:34:56Z")
        assert result is not None
        assert result.second == 56

    def test_returns_none_for_invalid_string(self) -> None:
        """parse_iso_timestamp should return None for invalid input."""
        result = parse_iso_timestamp("not a timestamp")
        assert result is None

    def test_returns_none_for_empty_string(self) -> None:
        """parse_iso_timestamp should return None for empty string."""
        result = parse_iso_timestamp("")
        assert result is None

    def test_result_is_timezone_aware(self) -> None:
        """parse_iso_timestamp should return timezone-aware datetime."""
        result = parse_iso_timestamp("2025-11-25T12:34:56Z")
        assert result is not None
        assert result.tzinfo is not None


class TestTimestampAgeSeconds:
    """Tests for timestamp_age_seconds function."""

    def test_returns_positive_for_past_timestamp(self) -> None:
        """timestamp_age_seconds should return positive value for past timestamps."""
        # Create a timestamp from 1 hour ago
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        past_str = past.isoformat().replace("+00:00", "Z")

        result = timestamp_age_seconds(past_str)
        assert result is not None
        # Should be approximately 3600 seconds (1 hour) - use generous tolerance for CI
        assert 3500 < result < 3700

    def test_returns_negative_for_future_timestamp(self) -> None:
        """timestamp_age_seconds should return negative value for future timestamps."""
        # Create a timestamp 1 hour in the future
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        future_str = future.isoformat().replace("+00:00", "Z")

        result = timestamp_age_seconds(future_str)
        assert result is not None
        # Should be approximately -3600 seconds - use generous tolerance for CI
        assert -3700 < result < -3500

    def test_returns_none_for_invalid_timestamp(self) -> None:
        """timestamp_age_seconds should return None for invalid timestamps."""
        result = timestamp_age_seconds("invalid")
        assert result is None

    def test_very_recent_timestamp(self) -> None:
        """timestamp_age_seconds should handle very recent timestamps."""
        now_str = utc_now_iso()
        time_module.sleep(0.1)  # Small delay

        result = timestamp_age_seconds(now_str)
        assert result is not None
        # Should be small but use generous upper bound for slow CI
        assert result > 0.05
        assert result < 10.0


class TestParseDurationString:
    """Tests for parse_duration_string function."""

    def test_parses_seconds_with_suffix(self) -> None:
        """parse_duration_string should parse seconds with 's' suffix."""
        assert parse_duration_string("30s") == 30
        assert parse_duration_string("10s") == 10

    def test_parses_minutes_with_suffix(self) -> None:
        """parse_duration_string should parse minutes with 'm' suffix."""
        assert parse_duration_string("5m") == 300
        assert parse_duration_string("1m") == 60

    def test_parses_hours_with_suffix(self) -> None:
        """parse_duration_string should parse hours with 'h' suffix."""
        assert parse_duration_string("1h") == 3600
        assert parse_duration_string("2h") == 7200

    def test_parses_days_with_suffix(self) -> None:
        """parse_duration_string should parse days with 'd' suffix."""
        assert parse_duration_string("1d") == 86400
        assert parse_duration_string("2d") == 172800

    def test_parses_plain_number_as_seconds(self) -> None:
        """parse_duration_string should parse plain numbers as seconds."""
        assert parse_duration_string("30") == 30
        assert parse_duration_string("120") == 120

    def test_parses_zero(self) -> None:
        """parse_duration_string should handle zero."""
        assert parse_duration_string("0") == 0
        assert parse_duration_string("0s") == 0

    def test_parses_fractional_values(self) -> None:
        """parse_duration_string should handle fractional values."""
        assert parse_duration_string("1.5h") == 5400
        assert parse_duration_string("0.5m") == 30

    def test_case_insensitive(self) -> None:
        """parse_duration_string should be case insensitive."""
        assert parse_duration_string("1H") == 3600
        assert parse_duration_string("5M") == 300
        assert parse_duration_string("30S") == 30

    def test_handles_whitespace(self) -> None:
        """parse_duration_string should strip whitespace."""
        assert parse_duration_string(" 1h ") == 3600
        assert parse_duration_string("  5m  ") == 300

    def test_raises_on_invalid_suffix(self) -> None:
        """parse_duration_string should raise ValueError for invalid suffix."""
        with pytest.raises(ValueError, match="Invalid duration suffix"):
            parse_duration_string("10x")

    def test_raises_on_invalid_format(self) -> None:
        """parse_duration_string should raise ValueError for invalid format."""
        with pytest.raises(ValueError, match="Invalid duration format"):
            parse_duration_string("abc")
        with pytest.raises(ValueError, match="Invalid duration format"):
            parse_duration_string("10.5.3h")
