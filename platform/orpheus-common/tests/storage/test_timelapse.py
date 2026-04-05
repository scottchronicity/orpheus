"""Tests for timelapse filename utilities."""

from datetime import datetime, timezone
from pathlib import Path

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


class TestTierMappings:
    """Tests for tier/lookback mapping functions."""

    def test_tier_lookback_map_has_expected_tiers(self):
        """Test that TIER_LOOKBACK_MAP has all expected tiers."""
        assert "tl0" in TIER_LOOKBACK_MAP
        assert "tl1" in TIER_LOOKBACK_MAP
        assert "tl2" in TIER_LOOKBACK_MAP
        assert "tl3" in TIER_LOOKBACK_MAP
        assert "tl4" in TIER_LOOKBACK_MAP
        assert "tl5" in TIER_LOOKBACK_MAP
        assert "tl6" in TIER_LOOKBACK_MAP

    def test_lookback_tier_map_has_expected_lookbacks(self):
        """Test that LOOKBACK_TIER_MAP has all expected lookbacks."""
        assert "24h" in LOOKBACK_TIER_MAP
        assert "12h" in LOOKBACK_TIER_MAP
        assert "6h" in LOOKBACK_TIER_MAP
        assert "1h" in LOOKBACK_TIER_MAP
        assert "30m" in LOOKBACK_TIER_MAP
        assert "10m" in LOOKBACK_TIER_MAP
        assert "1m" in LOOKBACK_TIER_MAP

    def test_get_tier_from_lookback_known_values(self):
        """Test tier lookup for known lookback windows."""
        assert get_tier_from_lookback("24h") == "tl0"
        assert get_tier_from_lookback("12h") == "tl1"
        assert get_tier_from_lookback("6h") == "tl2"
        assert get_tier_from_lookback("1h") == "tl3"
        assert get_tier_from_lookback("30m") == "tl4"
        assert get_tier_from_lookback("10m") == "tl5"
        assert get_tier_from_lookback("1m") == "tl6"

    def test_get_tier_from_lookback_unknown_value(self):
        """Test tier lookup for unknown lookback windows."""
        assert get_tier_from_lookback("5m") == "tlX"
        assert get_tier_from_lookback("2h") == "tlX"

    def test_get_lookback_from_tier_known_values(self):
        """Test lookback lookup for known tiers."""
        assert get_lookback_from_tier("tl0") == "24h"
        assert get_lookback_from_tier("tl1") == "12h"
        assert get_lookback_from_tier("tl2") == "6h"
        assert get_lookback_from_tier("tl3") == "1h"
        assert get_lookback_from_tier("tl4") == "30m"
        assert get_lookback_from_tier("tl5") == "10m"
        assert get_lookback_from_tier("tl6") == "1m"

    def test_get_lookback_from_tier_unknown_value(self):
        """Test lookback lookup for unknown tiers."""
        assert get_lookback_from_tier("tl99") is None
        assert get_lookback_from_tier("invalid") is None


class TestGetTierDisplayName:
    """Tests for get_tier_display_name function."""

    def test_display_names_for_known_tiers(self):
        """Test display names for all known tiers."""
        assert get_tier_display_name("tl0") == "24h"
        assert get_tier_display_name("tl1") == "12h"
        assert get_tier_display_name("tl2") == "6h"
        assert get_tier_display_name("tl3") == "1h"
        assert get_tier_display_name("tl4") == "30m"
        assert get_tier_display_name("tl5") == "10m"
        assert get_tier_display_name("tl6") == "1m"

    def test_display_name_for_unknown_tier(self):
        """Test that unknown tiers return the tier string itself."""
        assert get_tier_display_name("tl99") == "tl99"
        assert get_tier_display_name("unknown") == "unknown"


class TestGenerateTimelapseFilename:
    """Tests for generate_timelapse_filename function."""

    def test_generates_correct_format(self):
        """Test that filename is generated in correct format."""
        timestamp = datetime(2026, 1, 25, 23, 0, 0, tzinfo=timezone.utc)
        filename = generate_timelapse_filename(
            camera_id="orpheus-eye-1",
            label="daily",
            lookback_window="24h",
            timestamp=timestamp,
        )
        assert filename == "orpheus-eye-1.daily.tl0.24h.20260125-230000.mp4"

    def test_generates_hourly_timelapse(self):
        """Test hourly timelapse filename generation."""
        timestamp = datetime(2026, 1, 25, 14, 30, 0, tzinfo=timezone.utc)
        filename = generate_timelapse_filename(
            camera_id="orpheus-eye-2",
            label="hourly",
            lookback_window="1h",
            timestamp=timestamp,
        )
        assert filename == "orpheus-eye-2.hourly.tl3.1h.20260125-143000.mp4"

    def test_generates_30min_timelapse(self):
        """Test 30-minute timelapse filename generation."""
        timestamp = datetime(2026, 1, 25, 8, 30, 0, tzinfo=timezone.utc)
        filename = generate_timelapse_filename(
            camera_id="orpheus-eye-3",
            label="quick",
            lookback_window="30m",
            timestamp=timestamp,
        )
        assert filename == "orpheus-eye-3.quick.tl4.30m.20260125-083000.mp4"

    def test_sanitizes_label_with_special_chars(self):
        """Test that special characters in labels are sanitized."""
        timestamp = datetime(2026, 1, 25, 12, 0, 0, tzinfo=timezone.utc)
        filename = generate_timelapse_filename(
            camera_id="cam-1",
            label="my label!@#$",
            lookback_window="24h",
            timestamp=timestamp,
        )
        assert "mylabel" in filename
        assert "!" not in filename
        assert "@" not in filename

    def test_uses_default_label_for_empty_after_sanitize(self):
        """Test that empty labels after sanitization use default."""
        timestamp = datetime(2026, 1, 25, 12, 0, 0, tzinfo=timezone.utc)
        filename = generate_timelapse_filename(
            camera_id="cam-1",
            label="!@#$%",  # All special chars
            lookback_window="24h",
            timestamp=timestamp,
        )
        assert "timelapse" in filename

    def test_uses_current_time_when_no_timestamp(self):
        """Test that current time is used when no timestamp provided."""
        filename = generate_timelapse_filename(
            camera_id="cam-1",
            label="test",
            lookback_window="24h",
        )
        # Should contain current date in format YYYYMMDD
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        assert today in filename


class TestParseTimelapseFilename:
    """Tests for parse_timelapse_filename function."""

    def test_parses_new_format(self):
        """Test parsing of new format filenames."""
        result = parse_timelapse_filename("orpheus-eye-1.daily.tl0.24h.20260125-230000.mp4")
        assert result is not None
        assert result.camera_id == "orpheus-eye-1"
        assert result.label == "daily"
        assert result.tier == "tl0"
        assert result.lookback == "24h"
        assert result.timestamp.year == 2026
        assert result.timestamp.month == 1
        assert result.timestamp.day == 25
        assert result.timestamp.hour == 23
        assert result.timestamp.minute == 0
        assert result.extension == "mp4"

    def test_parses_hourly_format(self):
        """Test parsing of hourly timelapse filenames."""
        result = parse_timelapse_filename("orpheus-eye-2.hourly.tl3.1h.20260125-143000.mp4")
        assert result is not None
        assert result.camera_id == "orpheus-eye-2"
        assert result.label == "hourly"
        assert result.tier == "tl3"
        assert result.lookback == "1h"

    def test_parses_with_path(self):
        """Test parsing when filename includes path."""
        result = parse_timelapse_filename(
            "/data/orpheus/video/timelapses/2026.01.25/orpheus-eye-1.daily.tl0.24h.20260125-230000.mp4"
        )
        assert result is not None
        assert result.camera_id == "orpheus-eye-1"

    def test_parses_legacy_format(self):
        """Test parsing of legacy format filenames."""
        result = parse_timelapse_filename("23-00.orpheus-eye-1.mp4")
        assert result is not None
        assert result.camera_id == "orpheus-eye-1"
        assert result.label == "legacy"
        assert result.tier == "tl0"  # Assumes daily for legacy
        assert result.timestamp.hour == 23
        assert result.timestamp.minute == 0

    def test_returns_none_for_invalid_format(self):
        """Test that invalid formats return None."""
        assert parse_timelapse_filename("invalid.mp4") is None
        assert parse_timelapse_filename("just-a-name") is None

    def test_filename_property_roundtrips(self):
        """Test that TimelapseFilename.filename produces parseable output."""
        original = TimelapseFilename(
            camera_id="cam-1",
            label="test",
            tier="tl3",
            lookback="1h",
            timestamp=datetime(2026, 1, 25, 14, 0, 0, tzinfo=timezone.utc),
            extension="mp4",
        )
        generated = original.filename
        parsed = parse_timelapse_filename(generated)

        assert parsed is not None
        assert parsed.camera_id == original.camera_id
        assert parsed.label == original.label
        assert parsed.tier == original.tier
        assert parsed.lookback == original.lookback


class TestGetTimelapsePath:
    """Tests for get_timelapse_path function."""

    def test_generates_correct_path(self):
        """Test that correct path is generated."""
        timestamp = datetime(2026, 1, 25, 23, 0, 0, tzinfo=timezone.utc)
        path = get_timelapse_path(
            storage_base=Path("/data/orpheus"),
            camera_id="orpheus-eye-1",
            label="daily",
            lookback_window="24h",
            timestamp=timestamp,
        )

        assert path.parent == Path("/data/orpheus/video/timelapses/2026.01.25")
        assert path.name == "orpheus-eye-1.daily.tl0.24h.20260125-230000.mp4"

    def test_uses_provided_date_str(self):
        """Test that provided date_str is used for directory."""
        timestamp = datetime(2026, 1, 25, 23, 0, 0, tzinfo=timezone.utc)
        path = get_timelapse_path(
            storage_base=Path("/data/orpheus"),
            camera_id="cam-1",
            label="test",
            lookback_window="1h",
            date_str="2026.01.24",  # Different from timestamp
            timestamp=timestamp,
        )

        assert "2026.01.24" in str(path)


class TestTierSortKey:
    """Tests for tier_sort_key function."""

    def test_sorts_tiers_correctly(self):
        """Test that tiers are sorted from longest to shortest lookback."""
        tiers = ["tl4", "tl0", "tl6", "tl2", "tl1", "tl5", "tl3"]
        sorted_tiers = sorted(tiers, key=tier_sort_key)
        assert sorted_tiers == ["tl0", "tl1", "tl2", "tl3", "tl4", "tl5", "tl6"]

    def test_unknown_tiers_sort_last(self):
        """Test that unknown tiers sort after known ones."""
        tiers = ["tl1", "unknown", "tl0"]
        sorted_tiers = sorted(tiers, key=tier_sort_key)
        assert sorted_tiers[-1] == "unknown"


class TestTimelapseFilenameDataclass:
    """Tests for TimelapseFilename dataclass."""

    def test_tier_display_property(self):
        """Test tier_display property returns human-readable name."""
        tl = TimelapseFilename(
            camera_id="cam-1",
            label="test",
            tier="tl0",
            lookback="24h",
            timestamp=datetime.now(timezone.utc),
        )
        assert tl.tier_display == "24h"

    def test_filename_property(self):
        """Test filename property generates correct string."""
        timestamp = datetime(2026, 1, 25, 12, 30, 45, tzinfo=timezone.utc)
        tl = TimelapseFilename(
            camera_id="cam-1",
            label="test",
            tier="tl3",
            lookback="1h",
            timestamp=timestamp,
        )
        assert tl.filename == "cam-1.test.tl3.1h.20260125-123045.mp4"
