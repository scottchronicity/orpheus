"""Tests for sound registry functionality."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orpheus_common.audio.sound_registry import (
    SoundRegistry,
    get_sound_registry,
)


@pytest.fixture
def test_sounds_dir(tmp_path: Path) -> Path:
    """Create a temporary sounds directory with test files."""
    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()

    # Create test audio files
    (sounds_dir / "test_tone.wav").write_text("fake audio")
    (sounds_dir / "test_beep.mp3").write_text("fake audio")
    (sounds_dir / "invalid-name!.wav").write_text("fake audio")

    # Create subdirectory
    subdir = sounds_dir / "subdirectory"
    subdir.mkdir()
    (subdir / "nested.flac").write_text("fake audio")

    return sounds_dir


class TestSoundRegistry:
    """Tests for SoundRegistry class."""

    def test_init_empty(self):
        """Test creating an empty registry."""
        registry = SoundRegistry()

        assert registry.list_sounds() == []
        assert not registry.has_sound("anything")

    def test_init_with_directory(self, test_sounds_dir):
        """Test creating registry with sounds directory."""
        registry = SoundRegistry(sounds_dir=test_sounds_dir, auto_discover=False)

        # Should be empty without auto_discover
        assert registry.list_sounds() == []

    def test_init_with_auto_discover(self, test_sounds_dir):
        """Test auto-discovery of sound files."""
        registry = SoundRegistry(sounds_dir=test_sounds_dir, auto_discover=True)

        # Should discover valid files (not invalid-name!)
        sounds = registry.list_sounds()
        assert "test_tone" in sounds
        assert "test_beep" in sounds
        # Invalid names should be skipped
        assert "invalid-name!" not in sounds

    def test_add_sound_absolute_path(self, test_sounds_dir):
        """Test adding sound with absolute path."""
        registry = SoundRegistry()
        audio_file = test_sounds_dir / "test_tone.wav"

        registry.add_sound("my_sound", audio_file)

        assert registry.has_sound("my_sound")
        assert registry.get_sound_path("my_sound") == audio_file

    def test_add_sound_relative_path(self, test_sounds_dir):
        """Test adding sound with relative path."""
        registry = SoundRegistry(sounds_dir=test_sounds_dir)

        registry.add_sound("my_sound", Path("test_tone.wav"))

        assert registry.has_sound("my_sound")
        expected_path = test_sounds_dir / "test_tone.wav"
        assert registry.get_sound_path("my_sound") == expected_path

    def test_add_sound_invalid_name(self, test_sounds_dir):
        """Test that invalid sound names are rejected."""
        registry = SoundRegistry()
        audio_file = test_sounds_dir / "test_tone.wav"

        invalid_names = [
            "invalid name",  # Space
            "invalid!name",  # Special char
            "invalid@name",  # Special char
            "",  # Empty
        ]

        for name in invalid_names:
            with pytest.raises(ValueError, match="Invalid sound name"):
                registry.add_sound(name, audio_file)

    def test_add_sound_nonexistent_file(self, tmp_path):
        """Test that adding nonexistent file raises error."""
        registry = SoundRegistry()
        nonexistent = tmp_path / "does_not_exist.wav"

        with pytest.raises(FileNotFoundError):
            registry.add_sound("test", nonexistent)

    def test_add_sound_unsupported_extension(self, tmp_path):
        """Test warning for unsupported file extension."""
        registry = SoundRegistry()
        text_file = tmp_path / "test.txt"
        text_file.write_text("not audio")

        # Should log warning but still add
        with patch("orpheus_common.audio.sound_registry.logger") as mock_logger:
            registry.add_sound("test", text_file)
            mock_logger.warning.assert_called()

        # Should still be registered
        assert registry.has_sound("test")

    def test_get_sound_path_existing(self, test_sounds_dir):
        """Test getting path for existing sound."""
        registry = SoundRegistry(sounds_dir=test_sounds_dir)
        audio_file = test_sounds_dir / "test_tone.wav"

        registry.add_sound("test_tone", audio_file)

        path = registry.get_sound_path("test_tone")
        assert path == audio_file

    def test_get_sound_path_nonexistent(self):
        """Test that getting nonexistent sound raises KeyError."""
        registry = SoundRegistry()

        with pytest.raises(KeyError, match="Unknown sound"):
            registry.get_sound_path("nonexistent")

    def test_has_sound(self, test_sounds_dir):
        """Test checking if sound exists."""
        registry = SoundRegistry(sounds_dir=test_sounds_dir)
        audio_file = test_sounds_dir / "test_tone.wav"

        assert not registry.has_sound("test_tone")

        registry.add_sound("test_tone", audio_file)

        assert registry.has_sound("test_tone")

    def test_list_sounds(self, test_sounds_dir):
        """Test listing all sounds."""
        registry = SoundRegistry(sounds_dir=test_sounds_dir)

        # Add multiple sounds
        registry.add_sound("sound_a", test_sounds_dir / "test_tone.wav")
        registry.add_sound("sound_z", test_sounds_dir / "test_beep.mp3")
        registry.add_sound("sound_m", test_sounds_dir / "test_tone.wav")

        # Should be sorted alphabetically
        sounds = registry.list_sounds()
        assert sounds == ["sound_a", "sound_m", "sound_z"]

    def test_remove_sound(self, test_sounds_dir):
        """Test removing a sound."""
        registry = SoundRegistry(sounds_dir=test_sounds_dir)
        audio_file = test_sounds_dir / "test_tone.wav"

        registry.add_sound("test_tone", audio_file)
        assert registry.has_sound("test_tone")

        registry.remove_sound("test_tone")
        assert not registry.has_sound("test_tone")

    def test_remove_nonexistent_sound(self):
        """Test that removing nonexistent sound raises KeyError."""
        registry = SoundRegistry()

        with pytest.raises(KeyError, match="Sound not registered"):
            registry.remove_sound("nonexistent")

    def test_clear(self, test_sounds_dir):
        """Test clearing all sounds."""
        registry = SoundRegistry(sounds_dir=test_sounds_dir, auto_discover=True)

        assert len(registry.list_sounds()) > 0

        registry.clear()

        assert registry.list_sounds() == []

    def test_valid_sound_names(self):
        """Test sound name validation."""
        valid_names = [
            "test_sound",
            "test-sound",
            "test123",
            "sound_with_many_underscores",
            "sound-with-many-hyphens",
            "a",
            "123",
        ]

        for name in valid_names:
            assert SoundRegistry._is_valid_sound_name(name)

    def test_invalid_sound_names(self):
        """Test invalid sound name rejection."""
        invalid_names = [
            "test sound",  # Space
            "test.sound",  # Dot
            "test@sound",  # Special char
            "test!sound",  # Special char
            "",  # Empty
            "Test_Sound",  # Should be lowercase or allow uppercase
        ]

        for name in invalid_names:
            # Note: _is_valid_sound_name converts to lowercase, so Test_Sound should be valid
            if name == "Test_Sound":
                assert SoundRegistry._is_valid_sound_name(name)
            else:
                assert not SoundRegistry._is_valid_sound_name(name)

    def test_from_config_with_explicit_sounds(self, test_sounds_dir):
        """Test creating registry from config with explicit sound mappings."""
        config = {
            "sounds_dir": str(test_sounds_dir),
            "auto_discover": False,
            "sounds": {
                "tone": "test_tone.wav",
                "beep": "test_beep.mp3",
            },
        }

        registry = SoundRegistry.from_config(config)

        assert registry.has_sound("tone")
        assert registry.has_sound("beep")
        assert len(registry.list_sounds()) == 2

    def test_from_config_with_auto_discover(self, test_sounds_dir):
        """Test creating registry from config with auto-discovery."""
        config = {
            "sounds_dir": str(test_sounds_dir),
            "auto_discover": True,
        }

        registry = SoundRegistry.from_config(config)

        # Should have discovered sounds
        assert len(registry.list_sounds()) > 0

    def test_from_config_mixed_mode(self, test_sounds_dir):
        """Test config with both auto-discovery and explicit sounds."""
        config = {
            "sounds_dir": str(test_sounds_dir),
            "auto_discover": True,
            "sounds": {
                "custom_name": "test_tone.wav",
            },
        }

        registry = SoundRegistry.from_config(config)

        # Should have both discovered and explicit sounds
        assert registry.has_sound("custom_name")
        assert "test_beep" in registry.list_sounds()

    def test_from_config_handles_errors(self, test_sounds_dir):
        """Test that config errors are logged but don't crash."""
        config = {
            "sounds_dir": str(test_sounds_dir),
            "sounds": {
                "valid": "test_tone.wav",
                "invalid": "nonexistent.wav",  # This will fail
            },
        }

        with patch("orpheus_common.audio.sound_registry.logger") as mock_logger:
            registry = SoundRegistry.from_config(config)

            # Should have logged error for invalid sound
            mock_logger.error.assert_called()

        # Valid sound should still be registered
        assert registry.has_sound("valid")
        assert not registry.has_sound("invalid")

    def test_discover_sounds_nonexistent_directory(self, tmp_path):
        """Test auto-discovery with nonexistent directory."""
        nonexistent = tmp_path / "does_not_exist"

        with patch("orpheus_common.audio.sound_registry.logger") as mock_logger:
            registry = SoundRegistry(sounds_dir=nonexistent, auto_discover=True)

            # Should log warning
            mock_logger.warning.assert_called()

        # Should have no sounds
        assert registry.list_sounds() == []


class TestGetSoundRegistry:
    """Tests for get_sound_registry() global function."""

    def test_returns_singleton(self):
        """Test that get_sound_registry returns same instance."""
        # Reset global instance
        import orpheus_common.audio.sound_registry as registry_module

        registry_module._sound_registry = None

        with patch("orpheus_common.config.OrpheusConfig") as mock_config:
            mock_instance = MagicMock()
            mock_instance._raw = {}
            mock_config.get_instance.return_value = mock_instance

            registry1 = get_sound_registry()
            registry2 = get_sound_registry()

            assert registry1 is registry2

    def test_reload_functionality(self):
        """Test that reload=True reloads configuration."""
        # Reset global instance
        import orpheus_common.audio.sound_registry as registry_module

        registry_module._sound_registry = None

        with patch("orpheus_common.config.OrpheusConfig") as mock_config:
            mock_instance = MagicMock()
            mock_instance._raw = {}
            mock_config.get_instance.return_value = mock_instance

            registry1 = get_sound_registry()
            registry2 = get_sound_registry(reload=True)

            # Should be different instances after reload
            assert registry1 is not registry2

    def test_loads_from_config(self, test_sounds_dir):
        """Test that get_sound_registry loads from OrpheusConfig."""
        # Reset global instance
        import orpheus_common.audio.sound_registry as registry_module

        registry_module._sound_registry = None

        with patch("orpheus_common.config.OrpheusConfig") as mock_config:
            mock_instance = MagicMock()
            mock_instance._raw = {
                "audio": {
                    "sounds": {
                        "sounds_dir": str(test_sounds_dir),
                        "auto_discover": True,
                    }
                }
            }
            mock_config.get_instance.return_value = mock_instance

            registry = get_sound_registry()

            # Should have discovered sounds
            assert len(registry.list_sounds()) > 0

    def test_uses_default_sounds_dir(self):
        """Test that default sounds directory is used when not configured."""
        # Reset global instance
        import orpheus_common.audio.sound_registry as registry_module

        registry_module._sound_registry = None

        with patch("orpheus_common.config.OrpheusConfig") as mock_config:
            mock_instance = MagicMock()
            mock_instance._raw = {}
            mock_config.get_instance.return_value = mock_instance

            registry = get_sound_registry()

            # Should have used default directory
            assert registry._sounds_dir is not None
            assert "orpheus_common/sounds" in str(registry._sounds_dir)
