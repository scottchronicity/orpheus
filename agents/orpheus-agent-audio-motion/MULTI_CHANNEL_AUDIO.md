# Multi-Channel Audio Source Implementation

## Overview

The audio source handling has been refactored to support multi-channel audio devices like the Behringer UMC404HD. Previously, the system would create separate `ALSAAudioSource` instances for each channel, which is inefficient and can cause device access conflicts. Now, a single `ALSAAudioSource` instance captures all channels from a device simultaneously.

## What Changed

### 1. ALSAAudioSource Refactoring

**Before:**
- Accepted a single `device_string` parameter (e.g., `"alsa://orpheus_umc?channel=2"`)
- Opened a stream for ONE channel
- Yielded frames for that single channel only

**After:**
- Accepts a list of `device_configs` containing all channels for the same device
- Opens ONE stream with all physical channels (e.g., `channels=4` for Behringer)
- Deinterleaves multi-channel data in the audio callback
- Yields frames for ALL logical channels with proper `channel_id` tagging

### 2. create_audio_source() Logic

**Before:**
- Loaded only the first enabled channel
- Created one source per channel (if called multiple times)

**After:**
- Loads ALL enabled audio channels from config
- Groups channels by device type (ALSA vs. default)
- Creates ONE multi-channel `ALSAAudioSource` for all ALSA channels on same device
- Properly handles multiple channels from the same physical device

### 3. SyntheticAudioSource Enhancement

- Added `channel_id` parameter (default: `"synthetic"`)
- Allows testing with multiple synthetic channels if needed

## Configuration Example

For a Behringer UMC404HD with 4 microphones, configure in `orpheus.yaml`:

```yaml
audio:
  sample_rate: 48000
  chunk_size: 1024
  format: "float32"
  channels:
    - id: 1
      name: "North Microphone"
      enabled: true
      device: "alsa://orpheus_umc?channel=1"
    - id: 2
      name: "South Microphone"
      enabled: true
      device: "alsa://orpheus_umc?channel=2"
    - id: 3
      name: "East Microphone"
      enabled: true
      device: "alsa://orpheus_umc?channel=3"
    - id: 4
      name: "West Microphone"
      enabled: true
      device: "alsa://orpheus_umc?channel=4"
```

## How It Works

### Audio Capture Flow

1. **Initialization**: `create_audio_source()` is called with runtime settings
2. **Channel Loading**: All enabled channels are loaded from `OrpheusConfig`
3. **Grouping**: Channels with `alsa://` devices are grouped together
4. **Source Creation**: ONE `ALSAAudioSource` is created with all 4 channel configs
5. **Stream Opening**: `ALSAAudioSource._start_internal()` opens a 4-channel stream
6. **Data Capture**: Audio callback receives interleaved 4-channel data
7. **Deinterleaving**: Callback splits data by channel and queues frames separately
8. **Frame Generation**: `stream_frames()` yields frames for all channels with correct `channel_id`

### Data Flow Example (4 channels)

```
ALSA Device (Behringer UMC404HD)
  ↓
sounddevice callback receives:
  [ch0_s0, ch1_s0, ch2_s0, ch3_s0, ch0_s1, ch1_s1, ch2_s1, ch3_s1, ...]
  ↓
Deinterleave into separate channels:
  ch0: [ch0_s0, ch0_s1, ch0_s2, ...]  → AudioFrame(channel_id="1", ...)
  ch1: [ch1_s0, ch1_s1, ch1_s2, ...]  → AudioFrame(channel_id="2", ...)
  ch2: [ch2_s0, ch2_s1, ch2_s2, ...]  → AudioFrame(channel_id="3", ...)
  ch3: [ch3_s0, ch3_s1, ch3_s2, ...]  → AudioFrame(channel_id="4", ...)
  ↓
Queue all frames
  ↓
stream_frames() yields frames for all channels
```

## Key Benefits

1. **Efficiency**: Only ONE audio stream is opened for all channels
2. **Synchronization**: All channels captured from the same device are perfectly synchronized
3. **No Device Conflicts**: Single stream prevents ALSA device access conflicts
4. **Correct Tagging**: Each frame has the proper `channel_id` for downstream processing
5. **Scalable**: Works with any number of channels on the device (tested with 4)

## Testing

All tests pass, including new multi-channel tests:

```bash
pytest tests/audio_source/test_audio_source_simple.py
```

New tests added:
- `test_multi_channel_config`: Validates 4-channel configuration parsing
- `test_different_devices_rejected`: Ensures all channels reference same device

## Migration Notes

No breaking changes for existing single-channel setups. If you have:

```yaml
audio:
  channels:
    - id: 1
      name: "Single Mic"
      enabled: true
      device: "alsa://hw:2,0?channel=1"
```

This continues to work - it will create one `ALSAAudioSource` with a single channel.

## Files Modified

1. `src/orpheus_agent_audio_motion/audio_source.py`
   - Refactored `ALSAAudioSource.__init__()` to accept `device_configs` list
   - Updated `_start_internal()` to open multi-channel stream
   - Modified `_stream_internal()` to yield frames for all channels
   - Refactored `create_audio_source()` to group and create multi-channel sources
   - Added `channel_id` parameter to `SyntheticAudioSource`

2. `tests/audio_source/test_audio_source_simple.py`
   - Updated test signatures to use `device_configs`
   - Added multi-channel configuration tests
   - Added cross-device rejection test

3. `config/orpheus.example.yaml` (new)
   - Example configuration showing Behringer 4-channel setup

## Future Enhancements

Potential improvements:
- Support for multiple different ALSA devices simultaneously
- Per-channel sample rate configuration (currently uses global)
- Automatic channel discovery from ALSA device capabilities
