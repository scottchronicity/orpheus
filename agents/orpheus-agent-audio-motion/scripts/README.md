# Orpheus Audio Diagnostic Tools

This directory contains diagnostic tools for audio hardware troubleshooting.

## orpheus_audioscope.py

Real-time AudioScope tool with a curses-based terminal UI. Displays audio signal levels, XRUN counts, and system health information.

### Usage

```bash
# Run normally (from scripts directory)
./orpheus_audioscope.py

# Run with specific device
./orpheus_audioscope.py -d UMC404HD

# Run with larger buffer (reduces XRUNs)
./orpheus_audioscope.py -b 4096

# Run with real-time priority (recommended for production)
sudo chrt -f 90 ./orpheus_audioscope.py

# List available audio devices
./orpheus_audioscope.py --list-devices
```

### Controls

| Key | Action |
| ----- | -------- |
| `b` | Cycle block sizes [1024, 2048, 4096, 8192] |
| `r` | Reset XRUN counter |
| `q` | Quit |

### Display

- **GLITCH COUNT**: Total XRUN (buffer overrun/underrun) events
- **Channel Levels**: Per-channel horizontal meters
  - Green: Below -18dB (quiet)
  - Yellow: -18dB to -6dB (moderate)
  - Red: Above -6dB (loud)
- **NO SIGNAL - PHANTOM OFF?**: Warning when channel below -90dB

### Requirements

- Python 3.9+
- `sounddevice` package (`pip install sounddevice`)
- PortAudio library (libportaudio2 on Linux)
- `orpheus_common` package

## Raw ALSA Testing

To bypass Python/PortAudio and test ALSA directly:

```bash
# Record 4-channel audio for 5 seconds
arecord -D hw:UMC404HD -c 4 -f S32_LE -r 48000 -d 5 test.wav

# List available ALSA devices
arecord -l

# Monitor input levels with alsamixer
alsamixer -c UMC404HD

# Check for XRUNs in dmesg
dmesg | grep -i xrun
```

## Dashboard Integration

The audio health data is also available via the Orpheus Dashboard:

- **UI**: Navigate to the "Audio System Health" section
- **API**: `GET /api/diagnostics/audio` returns JSON status

Example API response:

```json
{
  "running": true,
  "xrun": {"total": 0, "input_overflow": 0, "input_underflow": 0},
  "channels": [
    {"channel_id": "ch1", "level_db": -25.3, "has_signal": true, "level_color": "green"}
  ],
  "hardware": {"sample_rate": 48000, "buffer_size": 1024, "device_name": "orpheus_umc"},
  "timing": {"callback_interval_ms": 21.3, "jitter_ms": 0.5},
  "system": {"cpu_percent": 12.5, "thermal_temp_c": 45.2}
}
```
