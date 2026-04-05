#!/bin/bash
# Reset audio devices and prepare for orpheus-agent-audio-motion

set -e

echo "=== Stopping PulseAudio ==="
pulseaudio --kill 2>/dev/null || echo "PulseAudio already stopped"
sleep 2

echo ""
echo "=== Checking for lingering PulseAudio processes ==="
pkill -9 pulseaudio 2>/dev/null || echo "No lingering PulseAudio processes"
sleep 1

echo ""
echo "=== Unloading ALSA modules ==="
sudo modprobe -r snd_usb_audio 2>/dev/null || echo "snd_usb_audio not loaded"
sleep 1

echo ""
echo "=== Reloading ALSA modules ==="
sudo modprobe snd_usb_audio
sleep 2

echo ""
echo "=== Checking device availability ==="
./check_audio_device.sh

echo ""
echo "=== Testing direct ALSA access to Behringer ==="
timeout 3 arecord -D hw:0,0 -f S16_LE -r 48000 -c 4 -d 1 /tmp/test_audio.wav 2>&1 || true

if [ -f /tmp/test_audio.wav ]; then
    SIZE=$(stat -f%z /tmp/test_audio.wav 2>/dev/null || stat -c%s /tmp/test_audio.wav)
    echo "Test recording created: $SIZE bytes"
    if [ "$SIZE" -gt 1000 ]; then
        echo "✅ Audio device is accessible!"
    else
        echo "⚠️  Recording file too small - device might not be working"
    fi
    rm /tmp/test_audio.wav
else
    echo "❌ Could not create test recording - device still unavailable"
fi

echo ""
echo "=== Ready to run agent ==="
echo "Run: make run"
