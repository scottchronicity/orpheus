#!/bin/bash
# Check what's using the audio device

echo "=== Processes using ALSA audio devices ==="
sudo lsof /dev/snd/* 2>/dev/null

echo ""
echo "=== PulseAudio status (if running) ==="
pactl info 2>/dev/null || echo "PulseAudio not running"

echo ""
echo "=== Check for orpheus-agent-audio-motion service ==="
systemctl status orpheus-agent-audio-motion 2>/dev/null || echo "Service not installed/running"

echo ""
echo "=== Python processes that might be using audio ==="
ps aux | grep -E "python.*audio|orpheus.*audio" | grep -v grep

echo ""
echo "=== Available audio devices via sounddevice ==="
python3 -c "import sounddevice as sd; print(sd.query_devices())" 2>/dev/null || echo "Could not query devices"

echo ""
echo "=== ALSA device status ==="
cat /proc/asound/cards
