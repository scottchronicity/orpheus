"""
Test sound deployment and discovery.

Tests that sound files are properly packaged and can be discovered
in both development and deployment scenarios.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from orpheus_common.audio.sound_registry import SoundRegistry, get_sound_registry


class TestSoundDeployment:
    """Test sound file deployment and discovery."""

    def test_sounds_packaged_in_module(self):
        """Test that sounds directory exists in the package."""
        import orpheus_common

        module_dir = Path(orpheus_common.__file__).parent
        sounds_dir = module_dir / "sounds"

        assert sounds_dir.exists(), f"Sounds directory not found at {sounds_dir}"
        assert sounds_dir.is_dir(), f"Sounds path is not a directory: {sounds_dir}"

        # Check for test sound files
        test_files = ["test_tone_1.wav", "test_beep.wav", "test_silence.wav"]
        for test_file in test_files:
            sound_path = sounds_dir / test_file
            assert sound_path.exists(), f"Test sound file not found: {sound_path}"

    def test_sound_registry_auto_discover_from_package(self):
        """Test that sound registry can auto-discover sounds from package directory."""
        import orpheus_common

        module_dir = Path(orpheus_common.__file__).parent
        sounds_dir = module_dir / "sounds"

        config = {"sounds_dir": str(sounds_dir), "auto_discover": True}

        registry = SoundRegistry.from_config(config)
        sounds = registry.list_sounds()

        assert len(sounds) >= 3, f"Expected at least 3 sounds, found {len(sounds)}"
        assert "test_tone_1" in sounds
        assert "test_beep" in sounds
        assert "test_silence" in sounds

    def test_sound_registry_deployment_path_fallback(self):
        """Test that get_sound_registry falls back to package path in development."""
        # Mock config with auto_discover enabled
        mock_config = Mock()
        mock_config._raw = {"audio": {"sounds": {"auto_discover": True}}}

        with patch("orpheus_common.config.OrpheusConfig.get_instance") as mock_get_config:
            mock_get_config.return_value = mock_config

            # Force reload to test path resolution
            registry = get_sound_registry(reload=True)

            # Should have discovered sounds from package location
            sounds = registry.list_sounds()
            assert len(sounds) >= 3, f"Expected at least 3 sounds in package, found {len(sounds)}"

    def test_sound_registry_prefers_explicit_config_path(self):
        """Test that explicit config path takes precedence over defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_sounds = Path(tmpdir) / "custom_sounds"
            temp_sounds.mkdir()

            # Create a custom sound file
            custom_sound = temp_sounds / "custom_test.wav"
            custom_sound.write_bytes(b"RIFF" + b"\x00" * 40)  # Minimal WAV header

            # Mock config with explicit path
            mock_config = Mock()
            mock_config._raw = {
                "audio": {"sounds": {"sounds_dir": str(temp_sounds), "auto_discover": True}}
            }

            with patch("orpheus_common.config.OrpheusConfig.get_instance") as mock_get_config:
                mock_get_config.return_value = mock_config

                registry = get_sound_registry(reload=True)
                sounds = registry.list_sounds()

                assert "custom_test" in sounds, f"Custom sound not found. Available: {sounds}"

    def test_manual_sound_registration(self):
        """Test manual sound registration without auto-discovery."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sounds_dir = Path(tmpdir)

            # Create sound files
            sound1 = sounds_dir / "sound1.wav"
            sound2 = sounds_dir / "subdir" / "sound2.mp3"
            sound2.parent.mkdir(parents=True)

            sound1.write_bytes(b"RIFF" + b"\x00" * 40)
            sound2.write_bytes(b"ID3" + b"\x00" * 40)

            config = {
                "sounds_dir": str(sounds_dir),
                "auto_discover": False,
                "sounds": {"mysound1": "sound1.wav", "mysound2": "subdir/sound2.mp3"},
            }

            registry = SoundRegistry.from_config(config)
            sounds = registry.list_sounds()

            assert len(sounds) == 2
            assert "mysound1" in sounds
            assert "mysound2" in sounds

            # Verify paths resolve correctly
            assert registry.get_sound_path("mysound1") == sound1
            assert registry.get_sound_path("mysound2") == sound2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
