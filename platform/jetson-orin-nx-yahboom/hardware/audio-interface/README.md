# Behringer UMC404HD USB Audio Interface Setup

## Overview

The Behringer UMC404HD is a 4-input, 4-output USB 2.0 audio interface providing professional-quality audio I/O for the Orpheus system. It features MIDAS preamps, 24-bit/192kHz recording capability, and zero-latency direct monitoring.

### Specifications
- **Inputs**: 4x XLR/TRS combo inputs with MIDAS preamps
- **Outputs**: 4x balanced TRS outputs (1/4")
- **Sample Rates**: 44.1, 48, 88.2, 96, 176.4, 192 kHz
- **Bit Depth**: 24-bit
- **Connection**: USB 2.0 (Class Compliant)
- **Power**: USB bus-powered
- **Phantom Power**: +48V switchable per input pair

### Orpheus Audio Hardware Configuration

**Microphones**: 4× Clippy EM272Z1 XLR Microphones (matched set)
- Specifications: 14dB self-noise, 20Hz-20kHz frequency response
- Scientifically validated for wildlife recording (micbooster.com UK)
- Wind protection: Rycote Windjammer (grey) + Clippy foam windshields (small)

**Cables**: EBXYA XLR Cables 25ft Male to Female (6-pack, multi-color)
- 4 in use for microphones, 2 spares
- Color coding helps identify microphone positions

**USB Connection**: Via Anker 7-Port Powered USB Hub recommended
- Provides stable power for audio interface
- Reduces potential for USB bus noise

**Note**: Audio output (speakers) is handled separately via Bluetooth. See `hardware/bluetooth-audio/` for Pyle PDWR42BBT speaker setup.

## Hardware Setup

### Physical Connections

1. **Connect USB Cable**
   - Use the included USB 2.0 cable
   - **Recommended**: Connect via Anker 7-Port Powered USB Hub → Jetson USB-A port
   - Alternative: Direct to Jetson USB 3.0 port
   - Powered hub provides cleaner power and reduces audio interference

2. **Connect Clippy EM272Z1 Microphones**
   - Connect 4× EBXYA 25ft XLR cables (multi-color for easy identification)
   - XLR male to UMC404HD inputs 1-4
   - **Enable +48V phantom power** (required for Clippy EM272Z1)
   - Set input gain using front panel knobs (aim for -12dB to -6dB peaks)
   - Attach Rycote Windjammer and foam windshields for outdoor use

3. **Monitor Audio** (optional for setup)
   - Use headphone jack on front panel for monitoring
   - TRS outputs 1-4 available if needed for other equipment

4. **Front Panel Controls**
   - **Gain**: Adjust input levels per channel (turn clockwise to increase)
   - **48V**: Enable for Clippy EM272Z1 microphones (buttons above inputs 1-2 and 3-4)
   - **Direct Monitor**: Mix knob between USB playback and direct input monitoring
   - **Main Output**: Master volume control (primarily affects headphone output)

## Software Configuration

### Verify Device Detection

```bash
# List USB audio devices
lsusb | grep -i audio

# Should show something like:
# Bus 001 Device 003: ID 1397:0508 Behringer UMC404HD

# List ALSA sound cards
aplay -l

# Should show:
# card 2: U192k [UMC404HD 192k], device 0: USB Audio [USB Audio]
#   Subdevices: 1/1
#   Subdevice #0: subdevice #0

# Get card number (usually card 2 or higher on Jetson)
cat /proc/asound/cards
```

### Set as Default Audio Device

Create or edit ALSA configuration:

```bash
sudo nano /etc/asound.conf
```

Add the following (replace `hw:2` with your card number from `aplay -l`):

```
# Behringer UMC404HD default configuration
pcm.!default {
    type hw
    card 2  # Replace with your card number
    device 0
}

ctl.!default {
    type hw
    card 2  # Replace with your card number
}

# Higher quality capture settings
pcm.UMC404HD {
    type plug
    slave {
        pcm "hw:2,0"
        format S24_3LE
        rate 48000
        channels 4
    }
}

# Multi-channel playback
pcm.umc404hd_playback {
    type plug
    slave {
        pcm "hw:2,0"
        format S24_3LE
        rate 48000
        channels 4
    }
}
```

### PulseAudio Configuration

If using PulseAudio (default on Ubuntu):

```bash
# List PulseAudio sources
pactl list sources short

# List PulseAudio sinks
pactl list sinks short

# Set default source (input)
pactl set-default-source <source_name>

# Set default sink (output)
pactl set-default-sink <sink_name>

# Example:
# pactl set-default-source alsa_input.usb-Behringer_UMC404HD_192k-00.multichannel-input
```

To make PulseAudio settings persistent:

```bash
# Edit PulseAudio configuration
nano ~/.config/pulse/default.pa

# Add these lines:
set-default-source alsa_input.usb-Behringer_UMC404HD_192k-00.multichannel-input
set-default-sink alsa_output.usb-Behringer_UMC404HD_192k-00.multichannel-output

# Restart PulseAudio
pulseaudio -k
pulseaudio --start
```

### Test Audio Recording

```bash
# Record 5 seconds of audio from input 1 (48kHz, 16-bit)
arecord -D hw:2,0 -f S16_LE -r 48000 -c 1 -d 5 test.wav

# Record from all 4 inputs simultaneously
arecord -D hw:2,0 -f S16_LE -r 48000 -c 4 -d 5 test_4ch.wav

# Play back the recording
aplay test.wav

# Test with PulseAudio
parecord --device=<source_name> --file-format=wav test_pulse.wav
```

### Python Audio Capture Example

Install PyAudio:

```bash
sudo apt-get install python3-pyaudio
# or
pip3 install pyaudio
```

Basic capture script:

```python
#!/usr/bin/env python3
import pyaudio
import wave

# Configuration
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 4  # All 4 inputs
RATE = 48000
RECORD_SECONDS = 5
DEVICE_INDEX = 2  # Check with: python3 -m sounddevice

# Initialize PyAudio
p = pyaudio.PyAudio()

# Open stream
stream = p.open(format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=DEVICE_INDEX,
                frames_per_buffer=CHUNK)

print("Recording...")
frames = []

for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
    data = stream.read(CHUNK)
    frames.append(data)

print("Finished recording.")

# Stop and close stream
stream.stop_stream()
stream.close()
p.terminate()

# Save to file
wf = wave.open("output.wav", 'wb')
wf.setnchannels(CHANNELS)
wf.setsampwidth(p.get_sample_size(FORMAT))
wf.setframerate(RATE)
wf.writeframes(b''.join(frames))
wf.close()
```

### List Available Audio Devices (Python)

```python
#!/usr/bin/env python3
import pyaudio

p = pyaudio.PyAudio()
print("Available audio devices:")
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    print(f"\nDevice {i}: {info['name']}")
    print(f"  Max Input Channels: {info['maxInputChannels']}")
    print(f"  Max Output Channels: {info['maxOutputChannels']}")
    print(f"  Default Sample Rate: {info['defaultSampleRate']}")
p.terminate()
```

## Troubleshooting

### Device Not Detected

```bash
# Check USB connection
lsusb
dmesg | tail -50

# Check for USB errors
dmesg | grep -i "usb.*error"

# Reload ALSA
sudo alsa force-reload

# Restart PulseAudio
pulseaudio -k && pulseaudio --start
```

**Common Solutions:**
- Try a different USB port (preferably USB 3.0)
- Use a high-quality USB cable
- Avoid USB hubs - connect directly to Jetson
- Check power: `lsusb -v | grep "MaxPower"` (should be <500mA)

### No Audio / Low Levels

1. **Check Gain Settings**
   - Turn input gain knobs on the UMC404HD
   - Aim for -12dB to -6dB peaks (green LED, avoid red)

2. **Enable Phantom Power**
   - Required for condenser microphones
   - Press +48V buttons on front panel

3. **Check Direct Monitor Mix**
   - Turn "Direct Monitor" knob counter-clockwise for USB signal
   - Turn clockwise for direct input monitoring

4. **Verify ALSA Mixer Levels**
   ```bash
   alsamixer
   # Press F6 to select UMC404HD
   # Adjust levels with arrow keys
   # Press M to unmute channels
   ```

### Crackling / Dropouts

```bash
# Increase buffer size for USB audio
echo 'options snd-usb-audio nrpacks=1' | sudo tee /etc/modprobe.d/alsa-base.conf

# Reload module
sudo modprobe -r snd_usb_audio
sudo modprobe snd_usb_audio

# Check for USB errors
dmesg | grep -i "usb.*xhci"
```

### Sample Rate Issues

The UMC404HD supports multiple sample rates. Ensure your application matches the hardware:

```bash
# Check current sample rate
cat /proc/asound/card2/stream0

# Set sample rate (in your application)
# Common rates: 44100, 48000, 96000, 192000
```

### Permission Denied Errors

```bash
# Ensure user is in audio group
sudo usermod -aG audio $USER

# Logout and login, or:
newgrp audio

# Check permissions
ls -l /dev/snd/
```

## Performance Tuning

### Optimize Latency

For real-time audio processing:

```bash
# Set CPU governor to performance
sudo jetson_clocks

# Reduce audio buffer size (in your application)
# Smaller buffers = lower latency but higher CPU usage
# Typical values: 128, 256, 512, 1024 frames
```

### Monitor Performance

```bash
# Check for audio underruns/overruns
cat /proc/asound/card2/pcm0p/sub0/status
cat /proc/asound/card2/pcm0c/sub0/status

# Monitor CPU usage during audio processing
htop

# Check USB interrupt load
cat /proc/interrupts | grep usb
```

## Udev Rules

Persistent device naming (already configured in baseline-setup.sh):

```bash
# Check current rules
cat /etc/udev/rules.d/99-orpheus-hardware.rules

# Should include:
# SUBSYSTEM=="usb", ATTR{idVendor}=="1397", MODE="0660", GROUP="audio"

# Reload rules if needed
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Integration with Orpheus Agents

The audio interface will be used by:
- **Audio detection agents** for environmental sound analysis
- **Voice/speech agents** for microphone input
- **Audio playback agents** for output/announcements

Configure your agents to use the appropriate ALSA device or PulseAudio source.

## Additional Resources

- [Behringer UMC404HD Product Page](https://www.behringer.com/product.html?modelCode=P0BK1)
- [ALSA Project Documentation](https://www.alsa-project.org/wiki/Main_Page)
- [PulseAudio Documentation](https://www.freedesktop.org/wiki/Software/PulseAudio/)
- [PyAudio Documentation](https://people.csail.mit.edu/hubert/pyaudio/docs/)
