# Orpheus Sound Files

This directory contains audio files used by the Orpheus audio playback system.

## Current Test Sounds

The following test sounds are provided for development and testing:

- **test_tone_1.wav**: 1-second sine wave at 440 Hz (A4 note)
- **test_beep.wav**: 0.5-second sine wave at 880 Hz (A5 note) 
- **test_silence.wav**: 1-second of silence

These files are minimal test fixtures (~40-90 KB each) used to validate the audio playback infrastructure.

## Adding New Sounds

### Manual Registration

1. **Add your audio file** to this directory (or a subdirectory)
2. **Update the configuration** in `config/orpheus.yaml`:

```yaml
audio:
  sounds:
    sounds_dir: "platform/orpheus-common/sounds"
    auto_discover: false  # Set to true to auto-discover all files
    sounds:
      my_sound_name: "my_audio_file.wav"
      another_sound: "subdirectory/another.mp3"
```

3. **Sound names must be HTML/URL-safe**: Only alphanumeric, underscore, and hyphen characters

### Auto-Discovery

Set `auto_discover: true` in the configuration to automatically register all audio files in the sounds directory. Files will be registered using their filename (without extension) as the sound name.

## Supported Formats

- WAV (`.wav`)
- MP3 (`.mp3`)
- FLAC (`.flac`)
- OGG Vorbis (`.ogg`)
- M4A (`.m4a`)
- AIFF (`.aiff`)

## Git LFS

All audio files are tracked using Git LFS (Large File Storage). This is configured in the repository's `.gitattributes` file:

```
*.wav filter=lfs diff=lfs merge=lfs -text
*.flac filter=lfs diff=lfs merge=lfs -text
```

When adding new audio files:

1. Ensure Git LFS is installed: `git lfs install`
2. Add your files normally: `git add sounds/my_file.wav`
3. Commit: `git commit -m "Add sound: my_file"`

The files will be automatically uploaded to Git LFS storage.

## Usage Examples

### In Python Code

```python
from orpheus_common.audio import get_sound_registry, get_audio_player

# Get the sound registry
registry = get_sound_registry()

# List available sounds
sounds = registry.list_sounds()
print(f"Available sounds: {sounds}")

# Get path to a sound file
sound_path = registry.get_sound_path("test_tone_1")

# Play the sound
player = get_audio_player()
await player.play(sound_path, repeat_count=3, pause_between=1.0)
```

### Via MQTT

```json
{
  "sound_name": "test_tone_1",
  "repeat_count": 3,
  "pause_between": 1.0
}
```

Publish to `orpheus/audio/playback/request` topic.

### Via CLI Tool

```bash
orpheus_play_sound test_tone_1 --repeat 3 --pause 1.0
```

## Best Practices

1. **Keep test sounds small**: Use short duration files for testing (1-5 seconds)
2. **Organize by category**: Use subdirectories for different sound types
3. **Use descriptive names**: `crow_call_1`, `alarm_beep`, not `sound1`, `audio2`
4. **Document your sounds**: Add comments in the config file explaining each sound's purpose
5. **Test before committing**: Verify sounds play correctly on target hardware

## Production Sounds

For production deployment:

1. Source high-quality recordings appropriate for wildlife communication
2. Ensure proper licensing and attribution
3. Optimize file sizes while maintaining quality
4. Test on actual deployment hardware (Jetson Orin NX with Pyle speakers)
5. Document sound sources and intended use cases

## File Size Guidelines

- Test sounds: < 100 KB
- Development sounds: < 1 MB
- Production sounds: < 5 MB per file
- Total repository sounds: < 100 MB (to keep clone times reasonable)

For larger sound libraries, consider hosting separately and downloading during deployment.
