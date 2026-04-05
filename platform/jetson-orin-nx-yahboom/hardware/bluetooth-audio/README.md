# Bluetooth Audio Speaker Setup

## Overview

This guide covers pairing and configuring Bluetooth speakers with the Jetson Orin NX for audio playback. Bluetooth audio is useful for wireless sound output, alerts, and voice feedback in the Orpheus system.

### Orpheus Audio Hardware
- **Speakers**: Pyle PDWR42BBT Outdoor Bluetooth Speakers (1 pair)
  - 3.5" 3-way active/passive design
  - Weatherproof for outdoor installation
  - Wall/ceiling mount capability
  - Pre-wired together (active/passive pair)
- **Connection**: Bluetooth from Jetson only
  - No wired audio connection to Jetson
  - Speakers are self-contained unit

### Typical Use Cases
- Audio notifications and alerts
- Voice assistant responses
- Environmental sound playback
- Music/audio streaming
- Text-to-speech output

## Prerequisites

Bluetooth packages should already be installed via `baseline-setup.sh`:
- `bluez` - Bluetooth protocol stack
- `bluez-tools` - Command-line tools
- `bluetooth` - Additional utilities
- `pulseaudio-module-bluetooth` - PulseAudio Bluetooth module

## Verify Bluetooth Hardware

```bash
# Check Bluetooth adapter
hciconfig

# Should show something like:
# hci0:	Type: Primary  Bus: USB
# 	BD Address: XX:XX:XX:XX:XX:XX  ACL MTU: 1021:8  SCO MTU: 64:1

# Check Bluetooth service status
sudo systemctl status bluetooth

# Enable and start if not running
sudo systemctl enable bluetooth
sudo systemctl start bluetooth

# Check rfkill (should not be blocked)
rfkill list
# If blocked:
sudo rfkill unblock bluetooth
```

## Pairing Pyle PDWR42BBT Speakers

### Method 1: Using bluetoothctl (Recommended)

```bash
# Start bluetoothctl interactive mode
bluetoothctl

# In bluetoothctl prompt:
[bluetooth]# power on
[bluetooth]# agent on
[bluetooth]# default-agent
[bluetooth]# scan on

# Wait for your speaker to appear in scan results
# Look for something like:
# [NEW] Device AA:BB:CC:DD:EE:FF PDWR42BBT or Pyle

# Note the MAC address, then:
[bluetooth]# scan off
[bluetooth]# pair AA:BB:CC:DD:EE:FF
[bluetooth]# trust AA:BB:CC:DD:EE:FF
[bluetooth]# connect AA:BB:CC:DD:EE:FF

# If successful, exit
[bluetooth]# exit
```

### Pyle PDWR42BBT Pairing Mode

To put the Pyle speakers in pairing mode:
1. Power on the speaker
2. Press and hold the Bluetooth button until LED flashes rapidly (blue/red)
3. Speaker will appear as "PDWR42BBT" or "Pyle" in Bluetooth scan
4. Once paired, LED will turn solid blue

### Method 2: Using bluetoothctl Commands

```bash
# All-in-one script
sudo bluetoothctl << EOF
power on
agent on
default-agent
scan on
EOF

# Wait 10 seconds for scan
sleep 10

# Show discovered devices
bluetoothctl devices

# Pair with Pyle speaker (replace with your MAC)
SPEAKER_MAC="AA:BB:CC:DD:EE:FF"
bluetoothctl pair $SPEAKER_MAC
bluetoothctl trust $SPEAKER_MAC
bluetoothctl connect $SPEAKER_MAC
```

### Method 3: Using bt-device (bluez-tools)

```bash
# List available devices
bt-device -l

# Pair with device
bt-device --connect AA:BB:CC:DD:EE:FF
```

## Configure Audio Output

### PulseAudio Setup

```bash
# Ensure PulseAudio is running
pulseaudio --check
# If not running:
pulseaudio --start

# List available audio sinks
pactl list sinks short

# Should show Bluetooth speaker like:
# 2  bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink  module-bluez5-device.c  s16le 2ch 44100Hz  SUSPENDED

# Set Bluetooth speaker as default
pactl set-default-sink bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink

# Or find by name
pactl set-default-sink $(pactl list short sinks | grep bluez | awk '{print $2}')

# Test audio output
paplay /usr/share/sounds/alsa/Front_Center.wav
```

### Make Default Permanent

```bash
# Create or edit PulseAudio config
mkdir -p ~/.config/pulse
nano ~/.config/pulse/default.pa

# Add this line (replace with your sink name):
set-default-sink bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink

# Restart PulseAudio
pulseaudio -k
pulseaudio --start
```

## Auto-Connect on Boot

### Method 1: Systemd Service

Create a service to auto-connect Bluetooth devices:

```bash
sudo nano /etc/systemd/system/bluetooth-autoconnect.service
```

Add the following:

```ini
[Unit]
Description=Bluetooth Auto-Connect
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/bluetooth-connect.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Create the connection script:

```bash
sudo nano /usr/local/bin/bluetooth-connect.sh
```

Add:

```bash
#!/bin/bash
# Auto-connect to trusted Bluetooth devices

# Wait for Bluetooth to be ready
sleep 5

# Replace with your device MAC address
SPEAKER_MAC="AA:BB:CC:DD:EE:FF"

# Power on Bluetooth
bluetoothctl power on

# Connect to speaker
bluetoothctl connect $SPEAKER_MAC

# Set as default audio sink (wait for connection)
sleep 3
pactl set-default-sink $(pactl list short sinks | grep bluez | awk '{print $2}')
```

Make executable and enable:

```bash
sudo chmod +x /usr/local/bin/bluetooth-connect.sh
sudo systemctl enable bluetooth-autoconnect.service
sudo systemctl start bluetooth-autoconnect.service
```

### Method 2: Udev Rule (Auto-connect when speaker is powered on)

```bash
sudo nano /etc/udev/rules.d/99-bluetooth-autoconnect.rules
```

Add:

```
# Auto-connect Bluetooth audio devices
ACTION=="add", SUBSYSTEM=="bluetooth", RUN+="/usr/local/bin/bluetooth-connect.sh"
```

Reload udev:

```bash
sudo udevadm control --reload-rules
```

## Testing Audio Output

### Test with paplay

```bash
# Play test sound
paplay /usr/share/sounds/alsa/Front_Center.wav

# Specify Bluetooth sink explicitly
paplay --device=bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink /usr/share/sounds/alsa/Front_Center.wav
```

### Test with speaker-test

```bash
# Generate test tone
speaker-test -D bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink -c 2 -t wav
# Press Ctrl+C to stop
```

### Test with Python

```bash
# Install pygame for easy audio playback
pip3 install pygame
```

```python
#!/usr/bin/env python3
import pygame
import time

# Initialize pygame mixer
pygame.mixer.init()

# Load and play a sound
pygame.mixer.music.load('/usr/share/sounds/alsa/Front_Center.wav')
pygame.mixer.music.play()

# Wait for playback to finish
while pygame.mixer.music.get_busy():
    time.sleep(0.1)

print("Playback complete!")
```

### Text-to-Speech Example

```bash
# Install espeak or festival
sudo apt-get install espeak

# Test TTS
espeak "Hello, this is Orpheus speaking through bluetooth"

# Or with festival
sudo apt-get install festival
echo "Hello from Orpheus" | festival --tts
```

```python
#!/usr/bin/env python3
import subprocess

def speak(text):
    """Text-to-speech via espeak"""
    subprocess.run(['espeak', text])

# Test
speak("Bluetooth audio is working correctly")
```

## Troubleshooting

### Bluetooth Not Working

```bash
# Check Bluetooth status
systemctl status bluetooth

# Check for hardware blocks
rfkill list

# Unblock if needed
sudo rfkill unblock bluetooth

# Restart Bluetooth service
sudo systemctl restart bluetooth

# Check kernel modules
lsmod | grep bluetooth
# Should show: bluetooth, btusb, bnep, etc.

# If missing, load manually:
sudo modprobe bluetooth
sudo modprobe btusb
```

### Cannot Pair Device

1. **Put speaker in pairing mode** (usually hold power button)
2. **Clear previous pairings** on the speaker
3. **Remove and re-pair**:
   ```bash
   bluetoothctl remove AA:BB:CC:DD:EE:FF
   bluetoothctl scan on
   # Wait for device to appear
   bluetoothctl pair AA:BB:CC:DD:EE:FF
   ```

### No Audio Output

```bash
# Check PulseAudio is running
pulseaudio --check || pulseaudio --start

# List sinks
pactl list sinks short

# If Bluetooth sink is SUSPENDED, try:
pactl set-sink-port bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink a2dp-sink

# Check volume (should be >0%)
pactl list sinks | grep -A 10 bluez_sink | grep Volume

# Set volume to 100%
pactl set-sink-volume bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink 100%

# Unmute
pactl set-sink-mute bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink 0
```

### Choppy/Stuttering Audio

```bash
# Edit PulseAudio config for better Bluetooth performance
nano ~/.config/pulse/daemon.conf

# Add or modify:
default-sample-rate = 48000
alternate-sample-rate = 44100
resample-method = speex-float-10
# For Bluetooth specifically:
enable-remixing = no
enable-lfe-remixing = no

# Restart PulseAudio
pulseaudio -k && pulseaudio --start
```

### Connection Drops

1. **Check range** - Bluetooth range is ~10m, less through walls
2. **Reduce interference** - Move away from WiFi routers, microwaves
3. **Check battery** - Low speaker battery can cause drops
4. **Disable power saving**:
   ```bash
   sudo nano /etc/bluetooth/main.conf
   # Add under [General]:
   FastConnectable = true
   
   sudo systemctl restart bluetooth
   ```

### Audio Latency

Bluetooth audio has inherent latency (~100-200ms). For time-critical audio:

```bash
# Use aptX codec if supported (lower latency)
# Check available codecs:
pactl list | grep -A 10 "Name: bluez_sink"

# Some speakers support aptX-LL (Low Latency)
# If not available, use wired audio for real-time applications
```

## Managing Multiple Speakers

```bash
# List paired devices
bluetoothctl devices

# Connect to specific speaker
bluetoothctl connect AA:BB:CC:DD:EE:FF  # Speaker 1
bluetoothctl connect AA:BB:CC:DD:EE:GG  # Speaker 2

# Switch between speakers
pactl set-default-sink bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink
# or
pactl set-default-sink bluez_sink.AA_BB_CC_DD_EE_GG.a2dp_sink

# Disconnect speaker
bluetoothctl disconnect AA:BB:CC:DD:EE:FF
```

## Python Integration

### PyBluez (Low-level control)

```bash
pip3 install pybluez
```

```python
#!/usr/bin/env python3
import bluetooth

# Scan for nearby Bluetooth devices
print("Scanning for Bluetooth devices...")
nearby_devices = bluetooth.discover_devices(lookup_names=True)

for addr, name in nearby_devices:
    print(f"Found: {name} [{addr}]")
```

### Simple Audio Playback Function

```python
#!/usr/bin/env python3
import subprocess

def play_audio_file(filepath):
    """Play audio file via PulseAudio (uses default sink)"""
    subprocess.run(['paplay', filepath])

def play_audio_bluetooth(filepath, device_mac):
    """Play audio file via specific Bluetooth speaker"""
    sink = f"bluez_sink.{device_mac.replace(':', '_')}.a2dp_sink"
    subprocess.run(['paplay', f'--device={sink}', filepath])

# Example usage
play_audio_file('/usr/share/sounds/alsa/Front_Center.wav')
```

## Configuration Script

Save this as a helper script:

```bash
#!/bin/bash
# bt-speaker-setup.sh - Bluetooth speaker configuration helper

case "$1" in
    scan)
        echo "Scanning for Bluetooth devices..."
        bluetoothctl scan on &
        sleep 10
        kill $!
        bluetoothctl devices
        ;;
    pair)
        if [ -z "$2" ]; then
            echo "Usage: $0 pair <MAC_ADDRESS>"
            exit 1
        fi
        bluetoothctl pair $2
        bluetoothctl trust $2
        ;;
    connect)
        if [ -z "$2" ]; then
            echo "Usage: $0 connect <MAC_ADDRESS>"
            exit 1
        fi
        bluetoothctl connect $2
        sleep 2
        pactl set-default-sink $(pactl list short sinks | grep bluez | awk '{print $2}')
        ;;
    disconnect)
        if [ -z "$2" ]; then
            echo "Usage: $0 disconnect <MAC_ADDRESS>"
            exit 1
        fi
        bluetoothctl disconnect $2
        ;;
    status)
        echo "=== Bluetooth Status ==="
        systemctl status bluetooth --no-pager
        echo ""
        echo "=== Paired Devices ==="
        bluetoothctl devices
        echo ""
        echo "=== Audio Sinks ==="
        pactl list sinks short
        ;;
    *)
        echo "Usage: $0 {scan|pair|connect|disconnect|status} [MAC_ADDRESS]"
        exit 1
        ;;
esac
```

Make executable:
```bash
chmod +x bt-speaker-setup.sh
```

## Quick Start Scripts for Orpheus

### Complete Setup Script

Save this as `setup-pyle-speakers.sh`:

```bash
#!/bin/bash
# Complete Pyle PDWR42BBT Bluetooth speaker setup for Orpheus

set -e

echo "=== Pyle PDWR42BBT Bluetooth Speaker Setup ==="
echo ""
echo "Prerequisites:"
echo "1. Put speakers in pairing mode (hold Bluetooth button until flashing)"
echo "2. Make sure Bluetooth is enabled on Jetson"
echo ""
read -p "Press Enter when ready..."

# Enable Bluetooth
echo "Enabling Bluetooth..."
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
sudo rfkill unblock bluetooth

# Scan for devices
echo ""
echo "Scanning for Pyle speakers (10 seconds)..."
timeout 10 bluetoothctl scan on &
sleep 11

# Show discovered devices
echo ""
echo "Discovered devices:"
bluetoothctl devices | grep -i "pyle\|pdwr42bbt" || bluetoothctl devices

echo ""
read -p "Enter Pyle speaker MAC address (format: AA:BB:CC:DD:EE:FF): " SPEAKER_MAC

if [ -z "$SPEAKER_MAC" ]; then
    echo "Error: No MAC address entered"
    exit 1
fi

# Pair and trust
echo "Pairing with $SPEAKER_MAC..."
bluetoothctl pair $SPEAKER_MAC
bluetoothctl trust $SPEAKER_MAC
bluetoothctl connect $SPEAKER_MAC

# Wait for connection
sleep 3

# Set as default audio sink
echo "Setting as default audio output..."
SINK=$(pactl list short sinks | grep bluez | awk '{print $2}')
if [ -n "$SINK" ]; then
    pactl set-default-sink $SINK
    echo "Default audio sink set to: $SINK"
else
    echo "Warning: Could not find Bluetooth audio sink"
fi

# Test audio
echo ""
echo "Testing audio output..."
if [ -f /usr/share/sounds/alsa/Front_Center.wav ]; then
    paplay /usr/share/sounds/alsa/Front_Center.wav
    echo "You should hear a test sound"
else
    echo "Skipping audio test (test file not found)"
fi

# Save MAC address for future use
mkdir -p ~/.config/orpheus
echo "PYLE_SPEAKER_MAC=$SPEAKER_MAC" > ~/.config/orpheus/bluetooth-speakers.conf
echo "PYLE_SPEAKER_SINK=$SINK" >> ~/.config/orpheus/bluetooth-speakers.conf

echo ""
echo "=== Setup Complete! ==="
echo "MAC Address: $SPEAKER_MAC"
echo "Audio Sink: $SINK"
echo "Config saved to: ~/.config/orpheus/bluetooth-speakers.conf"
echo ""
echo "To reconnect in the future, run: bluetoothctl connect $SPEAKER_MAC"
```

### Daily Use Script

Save this as `connect-speakers.sh`:

```bash
#!/bin/bash
# Quick connect to Pyle speakers for Orpheus

# Load saved config
if [ -f ~/.config/orpheus/bluetooth-speakers.conf ]; then
    source ~/.config/orpheus/bluetooth-speakers.conf
else
    echo "Error: No saved speaker configuration"
    echo "Run setup-pyle-speakers.sh first"
    exit 1
fi

echo "Connecting to Pyle speakers..."
bluetoothctl connect $PYLE_SPEAKER_MAC

sleep 2

# Set as default sink
if [ -n "$PYLE_SPEAKER_SINK" ]; then
    pactl set-default-sink $PYLE_SPEAKER_SINK 2>/dev/null || {
        # If saved sink name doesn't work, find it dynamically
        SINK=$(pactl list short sinks | grep bluez | awk '{print $2}')
        pactl set-default-sink $SINK
        echo "Updated sink to: $SINK"
    }
fi

echo "Speakers connected!"
```

### Text-to-Speech Test Script

Save this as `speak-test.sh`:

```bash
#!/bin/bash
# Test text-to-speech through Pyle speakers

# Ensure speakers are connected
if ! pactl list sinks short | grep -q bluez; then
    echo "Connecting to speakers..."
    ~/.config/orpheus/connect-speakers.sh
fi

# Install espeak if not present
if ! command -v espeak &> /dev/null; then
    echo "Installing espeak..."
    sudo apt-get install -y espeak
fi

# Speak message
MESSAGE="${1:-Orpheus system is operational. Wildlife monitoring active.}"
espeak -a 200 "$MESSAGE"
```

### Make Scripts Executable

```bash
chmod +x setup-pyle-speakers.sh
chmod +x connect-speakers.sh
chmod +x speak-test.sh

# Run initial setup
./setup-pyle-speakers.sh

# Daily use
./connect-speakers.sh

# Test TTS
./speak-test.sh "Motion detected on camera three"
```

## Integration with Orpheus

### Use Cases

1. **Alert Notifications**
   - Play audio alerts for detected events
   - Voice announcements via TTS

2. **Status Updates**
   - Audio feedback for system status
   - Confirmation sounds for actions

3. **Audio Playback**
   - Music/sound effects for ambiance
   - Voice responses from AI agents

### Example Agent Integration

```python
import subprocess

class BluetoothAudioAgent:
    def __init__(self, device_mac):
        self.device_mac = device_mac
        self.sink = f"bluez_sink.{device_mac.replace(':', '_')}.a2dp_sink"
    
    def play_alert(self, audio_file):
        """Play alert sound"""
        subprocess.run(['paplay', f'--device={self.sink}', audio_file])
    
    def speak(self, text):
        """Text-to-speech"""
        subprocess.run(['espeak', f'-a 200', text])
    
    def set_volume(self, volume_percent):
        """Set volume (0-100)"""
        subprocess.run(['pactl', 'set-sink-volume', self.sink, f'{volume_percent}%'])
```

## Security Considerations

1. **Pairing Security**
   - Only pair in secure locations
   - Remove unknown devices: `bluetoothctl remove <MAC>`

2. **Disable When Not Needed**
   - Turn off Bluetooth to save power: `bluetoothctl power off`

3. **Visibility**
   - Don't leave in discoverable mode
   - Only enable during pairing

## Additional Resources

- [BlueZ Documentation](http://www.bluez.org/documentation/)
- [PulseAudio Bluetooth Setup](https://wiki.archlinux.org/title/bluetooth#PulseAudio)
- [Bluetoothctl User Guide](https://wiki.archlinux.org/title/Bluetooth#Bluetoothctl)
- [A2DP Profile Specification](https://www.bluetooth.com/specifications/specs/advanced-audio-distribution-profile-1-3/)
