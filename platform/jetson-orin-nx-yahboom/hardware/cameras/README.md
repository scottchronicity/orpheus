# Amcrest IP5M-B1186EW-AI-V3 PoE Camera Setup

## Overview

The Amcrest IP5M-B1186EW-AI-V3 is a 5MP PoE (Power over Ethernet) IP camera with AI human detection, night vision, and weatherproof housing. These cameras provide video feeds via RTSP for the Orpheus system.

### Orpheus Camera Configuration
- **Quantity**: 4× Amcrest IP5M-B1186EW-AI-V3 cameras
- **PoE Power Source**: TP-Link TL-SG1210MPE Managed PoE Switch
  - 8× PoE+ ports with 123W total power budget
  - Mounted outside sealed enclosure but inside wooden box
- **Cables**: Amazon Basics CAT6 Ethernet Cable 50ft (5-pack)
  - 4 in use for cameras, 1 spare
- **Network**: Connected via TP-Link CPE210 wireless bridge to house Eero mesh network

### Specifications
- **Resolution**: 5MP (2560x1920) @ 20fps, 1080p @ 30fps
- **Lens**: 2.8mm wide angle (110° viewing angle)
- **Night Vision**: IR LEDs up to 98 feet
- **Power**: PoE 802.3af (12V DC option available)
- **Network**: 10/100Mbps Ethernet
- **Compression**: H.265+/H.265/H.264+/H.264
- **AI Features**: Human detection, motion detection
- **Weather**: IP67 weatherproof rating
- **Audio**: Built-in microphone

## Hardware Setup

### Physical Installation

1. **Mount Camera**
   - **Orpheus Setup**: 12-foot mast with cameras at 8-10 feet height
   - Choose mounting location with good field of view
   - Ensure camera is within PoE switch range (<100m, using 50ft CAT6 cables)
   - Use weatherproof mounts for outdoor installation
   - Angle camera for optimal wildlife coverage

2. **Connect PoE Cable**
   - Use Amazon Basics CAT6 50ft cables
   - Run from TP-Link TL-SG1210MPE PoE switch to each camera
   - Camera is powered via PoE (802.3af), no separate power needed
   - Use cable conduit or weatherproofing for outdoor runs
   - Label cables for easy identification (4 cameras total)

3. **Network Topology**
   ```
   Station Equipment (All on TP-Link TL-SG1210MPE Switch):
   ├─ Camera 1 (50ft CAT6) ─┐
   ├─ Camera 2 (50ft CAT6) ─┤
   ├─ Camera 3 (50ft CAT6) ─┼─ TP-Link TL-SG1210MPE PoE Switch
   ├─ Camera 4 (50ft CAT6) ─┤  (local Layer 2 switching)
   └─ Jetson Orin NX ───────┘
          │
   (Only internet-bound traffic goes through bridge)
          │
   CPE210-B (Wireless Bridge - Client)
          │
     ~~~~ 2.4GHz Wireless ~~~~
          │
   CPE210-A (Wireless Bridge - AP)
          │
   House Eero Mesh Network
   
   Key: Camera ↔ Jetson traffic stays on local switch (<1ms latency)
        Only internet/remote access traverses wireless bridge
   ```

### Initial Camera Configuration

#### Find Camera IP Address

```bash
# Scan network for Amcrest cameras (all 4 should appear)
sudo nmap -sn 192.168.1.0/24

# Or use Amcrest IP Config tool (Windows/Mac)
# Or check DHCP leases on your Eero router

# Common default:
# IP: 192.168.1.108 (may increment for multiple cameras)
# Username: admin
# Password: <printed on camera label>
```

#### Access Web Interface

1. Open browser and navigate to camera IP: `http://192.168.1.108`
2. Login with default credentials (admin / password on label)
3. **IMPORTANT**: Change default password immediately

#### Configure Camera Settings

**Network Settings** (Setup > Network > TCP/IP):
- Set static IP addresses to avoid conflicts:
  - Camera 1: 192.168.1.201
  - Camera 2: 192.168.1.202
  - Camera 3: 192.168.1.203
  - Camera 4: 192.168.1.204
- Subnet mask: 255.255.255.0
- Gateway: Your router IP (e.g., 192.168.1.1)
- DNS: 8.8.8.8 (Google) or your router

**Video Settings** (Setup > Camera > Video):
- **Main Stream**: H.265, 2560x1920, 15fps, VBR, Quality: Best
- **Sub Stream**: H.264, 640x480, 15fps, VBR (for preview/low-bandwidth)
- Enable both streams

**Recording Settings** (Setup > Storage):
- Insert SD card for local recording (optional)
- Enable motion detection recording if desired

**AI Detection** (Setup > Event > Smart Motion Detection):
- Enable Human Detection (useful for filtering wildlife vs human activity)
- Adjust sensitivity (start with 50%, tune as needed)
- Set detection zones if needed

## RTSP Stream URLs

### URL Format

```
# Main Stream (5MP)
rtsp://username:password@<camera_ip>:554/cam/realmonitor?channel=1&subtype=0

# Sub Stream (SD)
rtsp://username:password@<camera_ip>:554/cam/realmonitor?channel=1&subtype=1

# Example with credentials
rtsp://admin:MySecurePass123@192.168.1.201:554/cam/realmonitor?channel=1&subtype=0
```

### Test RTSP Stream

Using FFmpeg:

```bash
# Install FFmpeg (already in baseline-setup.sh)
sudo apt-get install ffmpeg

# Test main stream (save 10 seconds to file)
ffmpeg -i "rtsp://admin:password@192.168.1.201:554/cam/realmonitor?channel=1&subtype=0" \
       -t 10 -c copy test_camera1.mp4

# Test sub stream
ffmpeg -i "rtsp://admin:password@192.168.1.201:554/cam/realmonitor?channel=1&subtype=1" \
       -t 10 -c copy test_camera1_sub.mp4

# Play stream with FFplay
ffplay "rtsp://admin:password@192.168.1.201:554/cam/realmonitor?channel=1&subtype=1"
```

Using VLC:

```bash
# Install VLC
sudo apt-get install vlc

# Play stream
vlc "rtsp://admin:password@192.168.1.201:554/cam/realmonitor?channel=1&subtype=0"
```

Using GStreamer:

```bash
# Play RTSP stream with GStreamer (hardware accelerated on Jetson)
gst-launch-1.0 rtspsrc location="rtsp://admin:password@192.168.1.201:554/cam/realmonitor?channel=1&subtype=0" \
    ! rtph265depay ! h265parse ! nvv4l2decoder ! nvvidconv ! autovideosink
```

## Python Integration

### OpenCV RTSP Capture

```python
#!/usr/bin/env python3
import cv2

# Camera credentials and IP
USERNAME = "admin"
PASSWORD = "MySecurePass123"
CAMERA_IP = "192.168.1.201"

# RTSP URL (sub stream for lower bandwidth)
rtsp_url = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/cam/realmonitor?channel=1&subtype=1"

# Open video stream
cap = cv2.VideoCapture(rtsp_url)

# Set buffer size (lower = less latency)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

if not cap.isOpened():
    print("Error: Could not open RTSP stream")
    exit(1)

print("Streaming from camera...")

while True:
    ret, frame = cap.read()
    
    if not ret:
        print("Error: Failed to grab frame")
        break
    
    # Display frame
    cv2.imshow('Camera Feed', frame)
    
    # Press 'q' to quit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```

### GStreamer Pipeline (Hardware Accelerated)

```python
#!/usr/bin/env python3
import cv2

# GStreamer pipeline for hardware-accelerated decode on Jetson
USERNAME = "admin"
PASSWORD = "MySecurePass123"
CAMERA_IP = "192.168.1.201"

gst_pipeline = (
    f"rtspsrc location=rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}:554/cam/realmonitor?channel=1&subtype=0 latency=0 ! "
    "rtph265depay ! h265parse ! nvv4l2decoder ! nvvidconv ! "
    "video/x-raw, format=BGRx ! videoconvert ! video/x-raw, format=BGR ! appsink"
)

cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)

if not cap.isOpened():
    print("Error: Could not open GStreamer pipeline")
    exit(1)

print("Streaming with hardware acceleration...")

while True:
    ret, frame = cap.read()
    
    if not ret:
        break
    
    cv2.imshow('Camera Feed', frame)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```

### Multi-Camera Capture

```python
#!/usr/bin/env python3
import cv2
import threading

class RTSPCamera:
    def __init__(self, name, rtsp_url):
        self.name = name
        self.rtsp_url = rtsp_url
        self.frame = None
        self.stopped = False
        
    def start(self):
        threading.Thread(target=self.update, args=()).start()
        return self
        
    def update(self):
        cap = cv2.VideoCapture(self.rtsp_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        while not self.stopped:
            ret, frame = cap.read()
            if ret:
                self.frame = frame
                
        cap.release()
        
    def read(self):
        return self.frame
        
    def stop(self):
        self.stopped = True

# Camera configurations
cameras = [
    RTSPCamera("Camera 1", "rtsp://admin:password@192.168.1.201:554/cam/realmonitor?channel=1&subtype=1"),
    RTSPCamera("Camera 2", "rtsp://admin:password@192.168.1.202:554/cam/realmonitor?channel=1&subtype=1"),
    # Add more cameras as needed
]

# Start all cameras
for cam in cameras:
    cam.start()

print("Streaming from multiple cameras...")

while True:
    for cam in cameras:
        frame = cam.read()
        if frame is not None:
            cv2.imshow(cam.name, frame)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Stop all cameras
for cam in cameras:
    cam.stop()

cv2.destroyAllWindows()
```

## Troubleshooting

### Camera Not Accessible

```bash
# Ping camera
ping 192.168.1.201

# Check if camera port is open
nmap -p 554,80 192.168.1.201

# Check PoE power
# Verify PoE switch is providing power
# Check LED on camera (should be lit)

# Reset camera
# Hold reset button for 20 seconds to factory reset
```

### RTSP Stream Issues

1. **Connection Timeout**
   - Verify RTSP URL is correct
   - Check firewall settings: `sudo ufw status`
   - Ensure port 554 is not blocked
   - Try sub stream (subtype=1) instead of main stream

2. **Choppy/Laggy Video**
   - Use sub stream for lower bandwidth
   - Reduce frame rate in camera settings
   - Check network bandwidth: `iperf3 -c <camera_ip>`
   - Use hardware decoding (GStreamer on Jetson)

3. **Authentication Errors**
   - Verify username/password
   - URL-encode special characters in password
   - Check if camera requires digest authentication

### Performance Optimization

```bash
# Monitor network traffic
sudo iftop -i eth0

# Check RTSP stream bitrate
ffprobe "rtsp://admin:password@192.168.1.201:554/cam/realmonitor?channel=1&subtype=0"

# Optimize for Jetson (use hardware decoder)
# See GStreamer pipeline examples above
```

### Common Error Messages

**Error: "Authentication failed"**
- Double-check credentials
- Reset camera password if forgotten

**Error: "Connection refused"**
- Camera may be offline or unreachable
- Check network connectivity
- Verify RTSP port (554) is enabled in camera

**Error: "No route to host"**
- Check if camera is on same network/VLAN
- Verify network cable is connected
- Check PoE switch status

## Camera Configuration File

Create a configuration file for easy management:

```yaml
# cameras.yaml
cameras:
  - name: "Front Door"
    ip: "192.168.1.201"
    username: "admin"
    password: "password1"
    location: "entrance"
    
  - name: "Backyard"
    ip: "192.168.1.202"
    username: "admin"
    password: "password2"
    location: "rear"
    
  - name: "Garage"
    ip: "192.168.1.203"
    username: "admin"
    password: "password3"
    location: "side"
```

## Integration with Orpheus Agents

Camera feeds will be used by:
- **Object detection agents** for visual analysis
- **Motion detection agents** for activity monitoring
- **Recording agents** for video archival
- **Alert agents** for security notifications

Use the RTSP URLs in your agent configurations.

## Security Best Practices

1. **Change Default Passwords**
   - Use strong, unique passwords for each camera
   - Store credentials securely (not in code)

2. **Network Isolation**
   - Put cameras on separate VLAN if possible
   - Block camera internet access (they don't need it)
   - Only allow access from Jetson

3. **Firmware Updates**
   - Regularly check for camera firmware updates
   - Access: Setup > System > Upgrade

4. **Disable Unused Features**
   - Turn off cloud services if not needed
   - Disable UPnP
   - Disable unnecessary ports

## Additional Resources

- [Amcrest IP5M-B1186EW-AI User Manual](https://amcrest.com/ip5m-b1186ew-ai-v3-5mp-outdoor-poe-ai-turret-dome-camera.html)
- [Amcrest API Documentation](https://s3.amazonaws.com/amcrest-files/Amcrest+HTTP+API+3.2017.pdf)
- [RTSP Protocol Specification](https://www.ietf.org/rfc/rfc2326.txt)
- [OpenCV VideoCapture Documentation](https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html)
- [GStreamer RTSP Examples](https://gstreamer.freedesktop.org/documentation/rtp/index.html)
