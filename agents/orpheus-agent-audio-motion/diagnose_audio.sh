#!/bin/bash
# Deep diagnosis of what's holding the audio device

echo "=== What processes have the Behringer device open? ==="
sudo fuser -v /dev/snd/pcmC0D0c 2>&1 || echo "fuser not available or device not locked"

echo ""
echo "=== Detailed lsof for card 0 (Behringer) ==="
sudo lsof | grep "116," | grep -E "controlC0|pcmC0"

echo ""
echo "=== Check if device is in use via /proc ==="
cat /proc/asound/card0/pcm0c/sub0/status

echo ""
echo "=== ALSA device information ==="
aplay -l 2>/dev/null | head -20
arecord -l 2>/dev/null | head -20

echo ""
echo "=== Try to see what sounddevice thinks about device 'orpheus_umc' ==="
python3 << 'PYEOF'
import sounddevice as sd
devices = sd.query_devices()
for i, dev in enumerate(devices):
    if 'UMC' in str(dev) or 'BEHRINGER' in str(dev) or 'U192k' in str(dev):
        print(f"\nDevice {i}:")
        print(dev)
PYEOF

echo ""
echo "=== Current orpheus.yaml audio config ==="
grep -A 30 "audio:" /opt/orpheus/config/orpheus.yaml | head -40
