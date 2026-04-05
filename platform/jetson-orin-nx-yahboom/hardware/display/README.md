# Display Configuration

## Overview

Display configuration for the Jetson Orin NX. While the Orpheus project is primarily headless, a display is useful for development, debugging, and visualization.

### Actual Orpheus Display Hardware
- **HMTECH 7 Inch Raspberry Pi Screen** (800×480 IPS LCD)
- **Connection Path**: HMTECH monitor → Anker 555 USB-C Hub (HDMI port) → BLACK+DECKER USB-C to USB-A adapter → Jetson USB-A port
- **Note**: Jetson DisplayPort is **UNUSED** in this setup
- **Remote Display**: VNC or NoMachine for remote access
- **Headless** mode for production deployment

### Important: USB-Based Display Connection

This setup uses an **Anker 555 USB-C Hub** with HDMI output, connected to the Jetson via USB-A port. The Jetson's native DisplayPort and HDMI capabilities are NOT used. The display signal is routed through the USB hub's HDMI port.

## Physical Display Setup

### Actual Setup: HMTECH 7" via USB Hub

```bash
# The HMTECH monitor connects via the Anker 555 hub's HDMI port
# Connection chain:
# 1. HMTECH monitor HDMI input
# 2. Anker 555 USB-C Hub HDMI output
# 3. BLACK+DECKER USB-C to USB-A adapter
# 4. Jetson USB-A port

# Check connected displays
xrandr

# The display will show up as a USB display device
lsusb | grep -i display

# Check display information
xrandr --verbose
```

### HMTECH 7" Display Resolution

```bash
# Native resolution: 800×480
xrandr --output HDMI-0 --mode 800x480

# If auto-detection doesn't work, you may need to create custom mode:
cvt 800 480 60
# Then add the mode using xrandr --newmode and --addmode
```

## Headless Configuration

### Running Without Physical Display

For headless operation (typical for Orpheus deployment):

```bash
# Create virtual display
sudo nano /etc/X11/xorg.conf
```

Add:

```
Section "Device"
    Identifier     "Device0"
    Driver         "nvidia"
    VendorName     "NVIDIA Corporation"
    Option         "AllowEmptyInitialConfiguration" "true"
EndSection

Section "Screen"
    Identifier     "Screen0"
    Device         "Device0"
EndSection
```

Or use a dummy HDMI plug (recommended for consistent behavior):
- Purchase HDMI dummy plug
- Simulates 1920x1080 display
- Allows GUI applications to run headless

### Virtual Frame Buffer (Xvfb)

```bash
# Install Xvfb
sudo apt-get install xvfb

# Start virtual display
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# Run GUI applications in virtual display
glxgears  # Test OpenGL
```

## GPU Acceleration

### Verify GPU Status

```bash
# Check GPU info
nvidia-smi

# Expected output:
# +-----------------------------------------------------------------------------+
# | NVIDIA-SMI 535.xx.xx    Driver Version: 535.xx.xx    CUDA Version: 12.2    |
# |-------------------------------+----------------------+----------------------+
# | GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
# | Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
# |                               |                      |               MIG M. |
# |===============================+======================+======================|
# |   0  Orin NX 16GB    Off      | 00000000:00:00.0  On |                  N/A |
# | N/A   42C    P8    8W /  25W  |    512MiB / 15360MiB |      5%      Default |

# Monitor GPU continuously
watch -n 1 nvidia-smi
```

### Enable Maximum Performance

```bash
# Set to maximum performance mode
sudo nvpmodel -m 0

# Lock clocks to maximum
sudo jetson_clocks

# Verify settings
sudo nvpmodel -q
```

### CUDA Verification

```bash
# Check CUDA installation
nvcc --version

# Run CUDA sample (if installed)
cd /usr/local/cuda/samples/1_Utilities/deviceQuery
sudo make
./deviceQuery

# Should show:
# Device 0: "Orin NX 16GB"
#   CUDA Capability: 8.7
#   Total global memory: 15.xx GB
```

## Graphics Libraries

### OpenGL

```bash
# Check OpenGL version
glxinfo | grep "OpenGL version"

# Expected: OpenGL version string: 4.6.x NVIDIA

# Test OpenGL
glxgears
# Should show smooth rotating gears, FPS in terminal

# Benchmark
glmark2
```

### Vulkan

```bash
# Install Vulkan tools
sudo apt-get install vulkan-tools

# List Vulkan devices
vulkaninfo

# Test Vulkan
vkcube
```

## VNC Remote Desktop

For remote GUI access:

### Install TigerVNC

```bash
# Install VNC server
sudo apt-get install tigervnc-standalone-server tigervnc-common

# Set VNC password
vncpasswd

# Start VNC server (1920x1080, 24-bit color)
vncserver :1 -geometry 1920x1080 -depth 24

# Connect from remote machine:
# vncviewer <jetson_ip>:5901
```

### Systemd Service for VNC

```bash
sudo nano /etc/systemd/system/vncserver@.service
```

Add:

```ini
[Unit]
Description=Remote desktop service (VNC)
After=syslog.target network.target

[Service]
Type=forking
User=%i
ExecStartPre=/bin/sh -c '/usr/bin/vncserver -kill :%i > /dev/null 2>&1 || :'
ExecStart=/usr/bin/vncserver :%i -geometry 1920x1080 -depth 24
ExecStop=/usr/bin/vncserver -kill :%i

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable vncserver@1.service
sudo systemctl start vncserver@1.service
```

## NoMachine Remote Desktop

Alternative to VNC with better performance:

```bash
# Download NoMachine for ARM64
wget https://download.nomachine.com/download/8.11/Linux/nomachine_8.11.3_1_arm64.deb

# Install
sudo dpkg -i nomachine_8.11.3_1_arm64.deb

# NoMachine server starts automatically
# Connect from remote machine using NoMachine client
# Default port: 4000
```

## Frame Buffer Configuration

### Check Frame Buffer

```bash
# List frame buffer devices
ls -l /dev/fb*

# Should show:
# /dev/fb0  - Primary frame buffer

# Get frame buffer info
fbset -i
```

### Direct Frame Buffer Access

For low-level graphics without X11:

```bash
# Install frame buffer utilities
sudo apt-get install fbi

# Display image directly to frame buffer
sudo fbi -T 1 -d /dev/fb0 image.png
```

## Visualization Tools

### OpenCV Display

```python
#!/usr/bin/env python3
import cv2
import numpy as np

# Create test pattern
img = np.zeros((480, 640, 3), dtype=np.uint8)
cv2.rectangle(img, (100, 100), (540, 380), (0, 255, 0), -1)
cv2.putText(img, "Orpheus Display Test", (120, 250), 
            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

# Display (requires X11 or remote desktop)
cv2.imshow("Test", img)
cv2.waitKey(5000)  # Display for 5 seconds
cv2.destroyAllWindows()
```

### Matplotlib Visualization

```python
#!/usr/bin/env python3
import matplotlib.pyplot as plt
import numpy as np

# Generate sample data
x = np.linspace(0, 10, 100)
y = np.sin(x)

# Plot
plt.figure(figsize=(10, 6))
plt.plot(x, y)
plt.title("Orpheus Sensor Data")
plt.xlabel("Time (s)")
plt.ylabel("Value")
plt.grid(True)

# Save to file (for headless)
plt.savefig('/tmp/plot.png')

# Or display (requires X11)
# plt.show()
```

## Troubleshooting

### No Display Output

```bash
# Check if X server is running
ps aux | grep X

# Check display variable
echo $DISPLAY
# Should show: :0 or :1

# Restart display manager
sudo systemctl restart gdm3
# or
sudo systemctl restart lightdm

# Check for errors
journalctl -u gdm3 -n 50
```

### Low Resolution / Wrong Resolution

```bash
# Force resolution in GRUB
sudo nano /etc/default/grub

# Add or modify:
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash video=HDMI-A-1:1920x1080@60"

# Update GRUB
sudo update-grub

# Reboot
sudo reboot
```

### Display Flickering

```bash
# Disable compositor (if using X11)
nvidia-settings --assign CurrentMetaMode="HDMI-0: 1920x1080 +0+0 { ForceCompositionPipeline = On }"

# Or create xorg.conf
sudo nvidia-xconfig --force-generate
```

### GPU Not Detected in Display Applications

```bash
# Check NVIDIA driver
lsmod | grep nvidia

# Reinstall NVIDIA drivers (if missing)
sudo apt-get install --reinstall nvidia-l4t-core nvidia-l4t-graphics

# Reboot
sudo reboot
```

### Remote Desktop Performance Issues

1. **Reduce Resolution**: Use 1280x720 instead of 1920x1080
2. **Lower Color Depth**: 16-bit instead of 24-bit
3. **Disable Composition**: Turn off desktop effects
4. **Use H.264 Encoding**: NoMachine or Chrome Remote Desktop

## Display Power Management

### Disable Screen Blanking

```bash
# Disable DPMS (screen timeout)
xset -dpms
xset s off

# Make permanent
sudo nano /etc/X11/xorg.conf

# Add:
Section "ServerFlags"
    Option "BlankTime" "0"
    Option "StandbyTime" "0"
    Option "SuspendTime" "0"
    Option "OffTime" "0"
EndSection
```

### HDMI CEC Control

If your display supports CEC:

```bash
# Install CEC utilities
sudo apt-get install cec-utils

# List CEC devices
echo 'scan' | cec-client -s -d 1

# Turn display on/off
echo 'on 0' | cec-client -s -d 1
echo 'standby 0' | cec-client -s -d 1
```

## Kiosk Mode

For dedicated display applications:

```bash
# Install minimal window manager
sudo apt-get install openbox

# Create autostart script
mkdir -p ~/.config/openbox
nano ~/.config/openbox/autostart

# Add:
#!/bin/bash
# Hide cursor
unclutter -idle 0 &
# Launch application fullscreen
chromium-browser --kiosk --disable-infobars http://localhost:8080 &
```

## Integration with Orpheus

### Typical Display Use Cases

1. **Development/Debugging**
   - Monitor agent status via GUI
   - Visualize sensor data in real-time
   - Debug computer vision algorithms

2. **Visualization Dashboard**
   - Display system metrics (CPU, GPU, memory)
   - Show camera feeds
   - Audio spectrum analyzer
   - Alert notifications

3. **Headless Operation** (Production)
   - No physical display
   - All monitoring via web interface or remote desktop
   - Lower power consumption

### Recommended Setup for Orpheus

**Development**: 
- Connect 1080p HDMI monitor
- Use nvidia-settings for GPU monitoring
- VNC for remote access

**Production**:
- Headless with dummy HDMI plug
- NoMachine for occasional remote access
- Web-based dashboards for monitoring

## Performance Monitoring Overlay

```bash
# Install GPU monitoring overlay
sudo pip3 install jetson-stats

# Run jtop (interactive GPU/CPU monitor)
jtop

# For display overlay in applications:
# Use tegrastats output in your visualization
tegrastats --interval 1000
```

## Additional Resources

- [NVIDIA Jetson Linux Developer Guide - Display](https://docs.nvidia.com/jetson/l4t/index.html)
- [X.Org Configuration Guide](https://www.x.org/releases/current/doc/)
- [OpenGL on Jetson](https://docs.nvidia.com/jetson/archives/r35.1/DeveloperGuide/text/SD/PlatformPowerAndPerformance.html)
- [VNC Setup Guide](https://wiki.archlinux.org/title/TigerVNC)
- [NoMachine Documentation](https://www.nomachine.com/getting-started-with-nomachine)
