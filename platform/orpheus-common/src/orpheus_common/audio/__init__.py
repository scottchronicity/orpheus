"""Audio module for Orpheus platform.

Provides audio playback and sound management functionality.
"""

from .playback import MAX_VOLUME, AudioPlayer, SubprocessAudioPlayer, get_audio_player
from .sound_registry import SoundRegistry, get_sound_registry

__all__ = [
    "AudioPlayer",
    "SubprocessAudioPlayer",
    "get_audio_player",
    "MAX_VOLUME",
    "SoundRegistry",
    "get_sound_registry",
]
