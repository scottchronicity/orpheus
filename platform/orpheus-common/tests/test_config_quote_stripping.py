"""Tests for quote stripping in config.py to handle Make vs Shell .env loading."""

import pytest

from orpheus_common.config import AudioConfig, ConfigError, _strip_outer_quotes


class TestStripOuterQuotes:
    """Tests for _strip_outer_quotes helper function."""

    def test_strip_single_quotes(self):
        """Should strip matching single quotes."""
        result = _strip_outer_quotes("'[1,2,3]'")
        assert result == "[1,2,3]"

    def test_strip_double_quotes(self):
        """Should strip matching double quotes."""
        result = _strip_outer_quotes('"hello world"')
        assert result == "hello world"

    def test_no_quotes(self):
        """Should leave string unchanged if no quotes."""
        result = _strip_outer_quotes("[1,2,3]")
        assert result == "[1,2,3]"

    def test_mismatched_quotes(self):
        """Should not strip mismatched quotes."""
        result = _strip_outer_quotes("'hello\"")
        assert result == "'hello\""

    def test_single_quote(self):
        """Should not strip single character that is a quote."""
        result = _strip_outer_quotes("'")
        assert result == "'"

    def test_empty_string(self):
        """Should handle empty string."""
        result = _strip_outer_quotes("")
        assert result == ""

    def test_whitespace_handling(self):
        """Should strip outer whitespace then quotes."""
        result = _strip_outer_quotes("  '[1,2,3]'  ")
        assert result == "[1,2,3]"

    def test_quoted_json_object(self):
        """Should strip quotes from JSON objects."""
        result = _strip_outer_quotes('{"key": "value"}')
        assert result == '{"key": "value"}'

        result = _strip_outer_quotes('\'{"key": "value"}\'')
        assert result == '{"key": "value"}'


class TestAudioConfigChannelsQuoteStripping:
    """Tests for AudioConfig.from_dict with quoted channel strings."""

    def test_channels_with_single_quotes(self):
        """Should parse channels string with single quotes (Make include .env case)."""
        # This simulates what Make's 'include .env' produces:
        # ORPHEUS_AUDIO__CHANNELS='[{"id": 1, "name": "test"}]'
        data = {"channels": '\'[{"id": 1, "name": "test"}]\''}
        config = AudioConfig.from_dict(data)
        assert len(config.channels) == 1
        assert config.channels[0].id == 1
        assert config.channels[0].name == "test"

    def test_channels_with_double_quotes(self):
        """Should parse channels string with double quotes."""
        # In a real .env file with Make include, this would look like:
        # ORPHEUS_AUDIO__CHANNELS="[{\"id\": 2, \"name\": \"north\"}]"
        # Python sees this as a raw string with outer quotes
        import json

        inner_json = json.dumps([{"id": 2, "name": "north"}])
        quoted_json = f'"{inner_json}"'

        data = {"channels": quoted_json}
        config = AudioConfig.from_dict(data)
        assert len(config.channels) == 1
        assert config.channels[0].id == 2
        assert config.channels[0].name == "north"

    def test_channels_without_quotes(self):
        """Should parse channels string without quotes (Shell sourcing case)."""
        # This simulates what shell sourcing (. .env) produces:
        # The shell strips quotes before exporting
        data = {"channels": '[{"id": 3, "name": "south"}]'}
        config = AudioConfig.from_dict(data)
        assert len(config.channels) == 1
        assert config.channels[0].id == 3
        assert config.channels[0].name == "south"

    def test_channels_as_list(self):
        """Should handle channels as direct list (YAML case)."""
        data = {"channels": [{"id": 4, "name": "east"}]}
        config = AudioConfig.from_dict(data)
        assert len(config.channels) == 1
        assert config.channels[0].id == 4
        assert config.channels[0].name == "east"

    def test_channels_invalid_json_with_quotes(self):
        """Should raise ConfigError for invalid JSON even with quote stripping."""
        data = {"channels": "'[invalid json'"}
        with pytest.raises(ConfigError, match="not valid JSON"):
            AudioConfig.from_dict(data)

    def test_channels_complex_config(self):
        """Should handle complex channel configuration with quote stripping."""
        channels_json = (
            '[{"id": 1, "name": "north", "enabled": true, "detection": {"threshold_db": -30.0}}]'
        )

        # Test with single quotes
        data = {"channels": f"'{channels_json}'"}
        config = AudioConfig.from_dict(data)
        assert len(config.channels) == 1
        assert config.channels[0].id == 1
        assert config.channels[0].name == "north"
        assert config.channels[0].enabled is True
