"""Sound registry for managing audio file mappings.

Maps human-readable sound names to actual audio file paths,
with support for multiple sound directories and validation.
"""

from pathlib import Path
from typing import Any, Optional

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


class SoundRegistry:
    """Registry for mapping sound names to audio file paths.

    Supports:
    - Multiple sound directories
    - File validation
    - Metadata caching
    - HTML/URL-safe sound names

    Example:
        >>> registry = SoundRegistry(sounds_dir="/path/to/sounds")
        >>> registry.add_sound("test_beep", "beep.wav")
        >>> file_path = registry.get_sound_path("test_beep")
        >>> registry.list_sounds()
        ['test_beep', 'test_tone_1', ...]
    """

    # Supported audio file extensions
    SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aiff"}

    def __init__(
        self,
        sounds_dir: Optional[Path] = None,
        auto_discover: bool = False,
    ) -> None:
        """Initialize the sound registry.

        Args:
            sounds_dir: Primary directory for sound files (default: None)
            auto_discover: Automatically discover sounds in sounds_dir (default: False)
        """
        self._sound_map: dict[str, Path] = {}
        self._sounds_dir = sounds_dir

        if sounds_dir and auto_discover:
            self._discover_sounds(sounds_dir)

    def add_sound(self, sound_name: str, file_path: Path) -> None:
        """Register a sound name to file path mapping.

        Args:
            sound_name: HTML/URL-safe identifier (e.g., "crow_call_1")
            file_path: Path to the audio file (absolute or relative to sounds_dir)

        Raises:
            ValueError: If sound_name is invalid or file doesn't exist
        """
        # Validate sound name
        if not sound_name or not self._is_valid_sound_name(sound_name):
            raise ValueError(
                f"Invalid sound name: '{sound_name}'. "
                "Must be alphanumeric with underscores/hyphens only."
            )

        # Resolve file path
        if not file_path.is_absolute() and self._sounds_dir:
            file_path = self._sounds_dir / file_path

        # Validate file existence
        if not file_path.exists():
            raise FileNotFoundError(f"Sound file not found: {file_path}")

        # Validate file extension
        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            logger.warning(
                "File extension may not be supported",
                file_extension=file_path.suffix,
                supported_extensions=", ".join(self.SUPPORTED_EXTENSIONS),
            )

        self._sound_map[sound_name] = file_path
        logger.info("Registered sound", sound_name=sound_name, file_path=file_path)

    def get_sound_path(self, sound_name: str) -> Path:
        """Get the file path for a sound name.

        Args:
            sound_name: The sound identifier

        Returns:
            Path to the audio file

        Raises:
            KeyError: If sound_name is not registered
        """
        if sound_name not in self._sound_map:
            available = ", ".join(sorted(self._sound_map.keys()))
            raise KeyError(
                f"Unknown sound: '{sound_name}'. Available sounds: {available or '(none)'}"
            )

        return self._sound_map[sound_name]

    def has_sound(self, sound_name: str) -> bool:
        """Check if a sound name is registered.

        Args:
            sound_name: The sound identifier

        Returns:
            True if sound is registered, False otherwise
        """
        return sound_name in self._sound_map

    def list_sounds(self) -> list[str]:
        """List all registered sound names.

        Returns:
            Sorted list of sound names
        """
        return sorted(self._sound_map.keys())

    def remove_sound(self, sound_name: str) -> None:
        """Remove a sound from the registry.

        Args:
            sound_name: The sound identifier

        Raises:
            KeyError: If sound_name is not registered
        """
        if sound_name not in self._sound_map:
            raise KeyError(f"Sound not registered: {sound_name}")

        del self._sound_map[sound_name]
        logger.info("Removed sound", sound_name=sound_name)

    def clear(self) -> None:
        """Remove all sounds from the registry."""
        self._sound_map.clear()
        logger.info("Cleared all sounds from registry")

    def _discover_sounds(self, directory: Path) -> None:
        """Auto-discover sound files in a directory.

        Creates sound names from filenames (without extension).

        Args:
            directory: Directory to scan for audio files
        """
        if not directory.exists() or not directory.is_dir():
            logger.warning("Sounds directory not found", directory=directory)
            return

        discovered = 0
        for file_path in directory.glob("*"):
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                # Use filename (without extension) as sound name
                sound_name = file_path.stem

                if self._is_valid_sound_name(sound_name):
                    try:
                        self.add_sound(sound_name, file_path)
                        discovered += 1
                    except Exception as e:
                        logger.warning(
                            "Failed to register sound file", file_path=file_path, error=str(e)
                        )
                else:
                    logger.warning(
                        "Skipping file with invalid name pattern", filename=file_path.name
                    )

        logger.info("Auto-discovered sounds", sound_count=discovered, directory=directory)

    @staticmethod
    def _is_valid_sound_name(name: str) -> bool:
        """Validate that sound name is HTML/URL-safe.

        Allowed: alphanumeric, underscore, hyphen

        Args:
            name: Sound name to validate

        Returns:
            True if valid, False otherwise
        """
        if not name:
            return False

        # Check for valid characters
        allowed_chars = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
        return all(c in allowed_chars for c in name.lower())

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SoundRegistry":
        """Create a SoundRegistry from configuration dictionary.

        Config format:
            {
                "sounds_dir": "/path/to/sounds",
                "auto_discover": true,
                "sounds": {
                    "test_beep": "beep.wav",
                    "crow_call": "crows/call1.wav"
                }
            }

        Args:
            config: Configuration dictionary

        Returns:
            Configured SoundRegistry instance
        """
        sounds_dir = config.get("sounds_dir")
        if sounds_dir:
            sounds_dir = Path(sounds_dir)

        auto_discover = config.get("auto_discover", False)

        registry = cls(sounds_dir=sounds_dir, auto_discover=auto_discover)

        # Add explicit sound mappings
        sounds = config.get("sounds", {})
        for sound_name, file_path in sounds.items():
            try:
                registry.add_sound(sound_name, Path(file_path))
            except Exception as e:
                logger.error("Failed to add sound", sound_name=sound_name, error=str(e))

        return registry


# Global instance (lazy-initialized)
_sound_registry: Optional[SoundRegistry] = None


def get_sound_registry(reload: bool = False) -> SoundRegistry:
    """Get the global sound registry instance.

    This function implements smart path resolution:
    1. Uses explicit config path if provided
    2. Falls back to deployment location (/opt/orpheus/sounds) if it exists
    3. Falls back to package location (for development)

    Args:
        reload: Force reload from config (default: False)

    Returns:
        SoundRegistry: The global sound registry instance
    """
    global _sound_registry

    if _sound_registry is None or reload:
        from orpheus_common.config import OrpheusConfig

        config = OrpheusConfig.get_instance()

        # Get sound configuration (with sensible defaults)
        sounds_config = {}

        # Try to get from config, with fallback to defaults
        try:
            # Check if there's an audio.sounds section
            if hasattr(config, "_raw") and "audio" in config._raw:
                sounds_config = config._raw.get("audio", {}).get("sounds", {})
        except Exception as e:
            logger.debug("No sounds config found, using defaults", error=str(e))

        # Smart path resolution for sounds directory
        if not sounds_config.get("sounds_dir"):
            # Try deployment location first
            deployment_sounds = Path("/opt/orpheus/sounds")
            if deployment_sounds.exists() and deployment_sounds.is_dir():
                sounds_config["sounds_dir"] = str(deployment_sounds)
                logger.debug("Using deployment sounds directory", directory=deployment_sounds)
            else:
                # Fall back to package location (development mode)
                import orpheus_common

                module_dir = Path(orpheus_common.__file__).parent
                package_sounds = module_dir / "sounds"
                sounds_config["sounds_dir"] = str(package_sounds)
                logger.debug("Using package sounds directory", directory=package_sounds)

        _sound_registry = SoundRegistry.from_config(sounds_config)

        logger.info(
            "Initialized sound registry",
            sounds_dir=sounds_config.get("sounds_dir"),
            sound_count=len(_sound_registry.list_sounds()),
        )

    return _sound_registry
