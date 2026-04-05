# Remote Access Configuration for Orpheus Station

**Network topology ensures local traffic (cameras ↔ Jetson) stays on the local switch for maximum performance.**

## Network Architecture
```
Station Equipment:
├─ 4× Amcrest Cameras ──┐
├─ Jetson Orin NX ──────┤─── TP-Link TL-SG1210MPE Switch
└─ PoE Switch ──────────┘           │
                                    │
                             CPE210 Wireless Bridge
                                    │
                            ~~~~ 2.4GHz WiFi ~~~~
                                    │
                             CPE210 at House
                                    │
                              Eero Mesh Network
                                    │
                                Internet
```

**Traffic patterns:**
- **Camera → Jetson:** Stays on local switch (Layer 2 switching, <1ms latency)
- **Jetson → Internet:** Through CPE210 bridge
- **Remote access:** Through CPE210 bridge from your laptop

**Jetson IP assignment:** Static recommended (configure in TP-Link switch or CPE210)

---

## Access Methods

### 1. SSH Access (Primary - Always Use First)

**Setup on Jetson:**
```bash
# Ensure SSH server is running
sudo systemctl enable ssh
sudo systemctl start ssh

# Generate SSH key for passwordless access (from your laptop):
ssh-keygen -t ed25519 -C "orpheus-station"
ssh-copy-id username@jetson-ip

# Test connection
ssh username@jetson-ip
```

**With tmux for persistent sessions:**
```bash
# Install tmux
sudo apt install tmux

# Start a named session
tmux new -s orpheus

# Detach: Ctrl+B, then D
# Reattach: tmux attach -t orpheus
```

**Recommended aliases (add to ~/.bashrc on laptop):**
```bash
alias orpheus-ssh='ssh username@jetson-ip'
alias orpheus-tmux='ssh username@jetson-ip -t tmux attach -t orpheus'
```

---

### 2. NoMachine (For GUI Access When Needed)

**Install on Jetson:**
```bash
# Download NoMachine for ARM64
cd ~/Downloads
wget https://download.nomachine.com/download/8.11/Arm/nomachine_8.11.3_1_arm64.deb

# Install
sudo dpkg -i nomachine_8.11.3_1_arm64.deb

# Fix any dependency issues
sudo apt --fix-broken install

# NoMachine service starts automatically
sudo systemctl status nxserver
```

**Connect from laptop:**
1. Install NoMachine client on your laptop: https://www.nomachine.com/download
2. Connect to: `jetson-ip:4000`
3. Login with your Jetson username/password

**Use cases for NoMachine:**
- Initial Jetson setup and configuration
- Testing GUI applications
- Troubleshooting display issues
- Running visual debugging tools
- System monitoring dashboards

**Performance tips:**
- Set quality to "Good" or "Medium" on poor network
- Disable audio streaming if not needed
- Close when not actively using (uses GPU resources)

---

### 3. Direct Camera RTSP Streams (Best for Viewing Cameras)

**Don't view cameras through the Jetson desktop** - access them directly via RTSP.

**Amcrest RTSP URLs:**
```
# Main stream (high quality, 5MP):
rtsp://admin:password@camera-ip:554/cam/realmonitor?channel=1&subtype=0

# Sub stream (lower quality, for monitoring):
rtsp://admin:password@camera-ip:554/cam/realmonitor?channel=1&subtype=1
```

**View with VLC on your laptop:**
```bash
# Open VLC → Media → Open Network Stream
# Paste RTSP URL
# Or from command line:
vlc rtsp://admin:password@camera-ip:554/cam/realmonitor?channel=1&subtype=0
```

**Multi-camera viewing options:**
- **VLC Playlist:** Add all 4 RTSP streams to a playlist
- **Frigate:** Full NVR with motion detection (can run on Jetson)
- **Blue Iris:** Windows-based NVR software
- **Home Assistant:** Open source home automation platform

**Why direct RTSP is better:**
- Full resolution (5MP vs compressed desktop capture)
- No Jetson GPU load
- Lower network bandwidth (no double-encoding)
- Works even if Jetson desktop isn't running

---

### 4. RustDesk (Alternative to NoMachine)

**If you prefer open-source or want to self-host:**
```bash
# Download latest RustDesk for Jetson
wget https://github.com/rustdesk/rustdesk/releases/download/1.2.3/rustdesk-1.2.3-aarch64.deb
sudo dpkg -i rustdesk-*.deb
```

**Advantages over NoMachine:**
- Open source
- Can self-host relay server
- Very low latency
- Good for development workflows

**Disadvantages:**
- More setup required
- Less tested on Jetson specifically

---

## Recommended Workflow

### Daily Development:
```bash
# Connect via SSH
ssh username@jetson-ip

# Attach to persistent tmux session
tmux attach -t orpheus

# View logs, edit code, test agents
# All in terminal - fast, low bandwidth
```

### When GUI Needed:
```bash
# Connect via NoMachine for:
- Testing visualization tools
- Debugging GUI apps
- System configuration that requires GUI

# Then disconnect when done
```

### Camera Monitoring:
```bash
# Open VLC on your laptop
# View RTSP streams directly
# No Jetson resources used
```

---

## Network Performance Notes

**Local switch performance (Camera ↔ Jetson):**
- Bandwidth: Full gigabit (125 MB/s per camera)
- Latency: <1ms (wire speed switching)
- **This traffic never goes through wireless**

**Wireless bridge performance (Jetson ↔ Internet):**
- Bandwidth: ~50-100 Mbps typical (CPE210 in good conditions)
- Latency: 10-30ms typical
- Shared with: Remote access, updates, cloud uploads

**Bandwidth planning:**
- 4× cameras @ 5MP → Jetson: ~20-30 Mbps total (local, not an issue)
- SSH traffic: <1 Mbps (negligible)
- NoMachine: 5-20 Mbps (depending on quality settings)
- RTSP to laptop: 5-8 Mbps per camera stream

**Recommendation:** View cameras via direct RTSP, not through NoMachine screen sharing, to minimize wireless bandwidth usage.

---

## Security Considerations

**SSH hardening:**
```bash
# Disable password authentication (use keys only)
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication no
# Set: PubkeyAuthentication yes

sudo systemctl restart ssh
```

**Firewall setup:**
```bash
# Install ufw (Uncomplicated Firewall)
sudo apt install ufw

# Allow SSH
sudo ufw allow ssh

# Allow NoMachine
sudo ufw allow 4000/tcp

# Allow RTSP from local network only
sudo ufw allow from 192.168.1.0/24 to any port 554 proto tcp

# Enable firewall
sudo ufw enable
```

**Camera passwords:**
- Change default Amcrest passwords immediately
- Use strong unique passwords (not shared with other devices)
- Document in a password manager, not in code

---

## Troubleshooting

### Can't SSH to Jetson
```bash
# Check if Jetson is reachable
ping jetson-ip

# Check if SSH is running (need physical access or NoMachine)
sudo systemctl status ssh

# Check CPE210 bridge status lights
# Verify Jetson has correct IP assigned
```

### NoMachine won't connect
```bash
# On Jetson, check service status
sudo systemctl status nxserver

# Restart NoMachine service
sudo systemctl restart nxserver

# Check port 4000 is open
sudo netstat -tulpn | grep 4000
```

### RTSP streams won't load
```bash
# Verify camera is reachable
ping camera-ip

# Check camera web interface
# Browse to: http://camera-ip
# Login with admin credentials

# Verify RTSP URL format
# Test with: ffprobe rtsp://admin:password@camera-ip:554/cam/realmonitor?channel=1&subtype=0
```

### Poor wireless bridge performance
```bash
# Check CPE210 signal strength (should be >-70dBm)
# Log into CPE210 web interface
# Check for interference (WiFi analyzer)
# Consider repositioning CPE210 antennas
```

---

## Quick Reference

**Connect via SSH:**
```bash
ssh username@jetson-ip
```

**Connect via NoMachine:**
- App: NoMachine client
- Address: `jetson-ip:4000`

**View Camera in VLC:**
```bash
vlc rtsp://admin:password@camera-ip:554/cam/realmonitor?channel=1&subtype=0
```

**Monitor system resources:**
```bash
# On Jetson via SSH
htop                  # CPU/RAM usage
tegrastats            # GPU/temp stats
df -h                 # Disk usage
journalctl -f         # System logs
```

---

**Document Created:** 2025-11-07  
**Last Updated:** 2025-11-07