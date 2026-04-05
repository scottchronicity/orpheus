# Jetson Orin NX 16GB on Yahboom Carrier Board

## Overview

This platform configuration targets the NVIDIA Jetson Orin NX 16GB module mounted on the Yahboom carrier board. The Yahboom carrier provides excellent expansion capabilities including multiple USB 3.0 ports, M.2 slots, GPIO headers, and robust power delivery.

### Hardware Specifications
- **Module**: NVIDIA Jetson Orin NX 16GB
- **Carrier Board**: Yahboom Jetson Orin NX Developer Kit
- **CPU**: 8-core ARM Cortex-A78AE v8.2
- **GPU**: 1024-core NVIDIA Ampere architecture GPU with 32 Tensor Cores
- **AI Performance**: 100 TOPS (INT8)
- **Memory**: 16GB 128-bit LPDDR5
- **Storage**: Samsung T7 2TB External SSD (USB-C connection)
- **Network**: Gigabit Ethernet + WiFi 6E/BT 5.2
- **Power**: 19V DC input, ~15-25W typical operation
- **USB Expansion**: 
  - 2× Anker 555 USB-C Hub (8-in-1): 85W PD, 4K HDMI, 10Gbps ports, Gigabit Ethernet
  - 1× Anker 7-Port Powered USB Hub: 36W power adapter, USB 3.0
  - BLACK+DECKER USB-C to USB-A Adapter (2-pack) for hub connections

### Orpheus-Specific USB Configuration
- **Jetson Native USB-C Port**: Samsung T7 2TB SSD (dedicated)
- **Jetson Native USB-A Ports** (4× available):
  - Anker 555 Hub #1 (via USB-C to USB-A adapter) → HMTECH display via HDMI
  - Anker 555 Hub #2 (via USB-C to USB-A adapter) → Network Ethernet port
  - Anker 7-Port Hub → Behringer UMC404HD, Logitech K400 Plus keyboard
  - Direct connection options for additional devices
- **Note**: Jetson native DisplayPort is UNUSED

## Baseline System Requirements

### Operating System
- **OS**: Ubuntu 24.04 LTS (Noble Numbat)
- **Kernel**: 5.15.x or later (Jetson-specific)
- **JetPack**: 6.0 or later
  - CUDA 12.2+
  - cuDNN 8.9+
  - TensorRT 8.6+
  - VPI 3.0+
  - OpenCV 4.8+ with CUDA support

### Verification Commands
```bash
# Check Jetson model
cat /proc/device-tree/model

# Check JetPack version
sudo apt-cache show nvidia-jetpack | grep Version

# Check CUDA version
nvcc --version

# Check GPU status
sudo tegrastats

# Check L4T (Linux for Tegra) version
cat /etc/nv_tegra_release
```

### Expected Output
```
NVIDIA Jetson Orin NX (16GB ram)
JetPack 6.0 [L4T 36.3.0]
CUDA compilation tools, release 12.2
```

## Quick Setup Checklist

### Initial Setup (First Boot)
- [ ] Flash JetPack 6.0+ using NVIDIA SDK Manager
- [ ] Connect to network (Ethernet recommended for initial setup)
- [ ] Update system: `sudo apt update && sudo apt upgrade`
- [ ] Verify all hardware detected: `lshw`, `lsusb`, `lspci`
- [ ] Set power mode: `sudo nvpmodel -m 0` (MAXN mode)
- [ ] Enable jetson_clocks: `sudo jetson_clocks`

### Platform Configuration
- [ ] Run `baseline-setup.sh` for system dependencies
- [ ] Configure audio interface (see `hardware/audio-interface/`)
- [ ] Set up IP cameras (see `hardware/cameras/`)
- [ ] Configure wireless bridge (see `hardware/networking/`)
- [ ] Pair Bluetooth speakers (see `hardware/bluetooth-audio/`)
- [ ] Configure display if needed (see `hardware/display/`)

### Service Setup
- [ ] Install MQTT broker (handled by baseline-setup.sh)
- [ ] Configure systemd services (see `services/`)
- [ ] Set up agent deployment
- [ ] Verify all services start on boot

### Performance Tuning
- [ ] Set CPU governor to performance: `sudo jetson_clocks`
- [ ] Configure swap if needed (not typically required with 16GB)
- [ ] Monitor temperatures: `tegrastats` or `jtop`
- [ ] Optimize power consumption for your use case

### Monitoring Tools
```bash
# Install jtop (recommended)
sudo pip3 install -U jetson-stats
sudo systemctl restart jtop.service
jtop  # Interactive monitor

# Or use built-in tegrastats
sudo tegrastats --interval 1000
```

## Directory Structure

```
platform/jetson-orin-nx-yahboom/
├── README.md                    # This file
├── baseline-setup.sh            # Automated system setup script
├── hardware/                    # Hardware-specific configurations
│   ├── audio-interface/        # Behringer UMC404HD setup
│   ├── bluetooth-audio/        # Bluetooth speaker pairing
│   ├── cameras/                # IP camera RTSP configuration
│   ├── display/                # Monitor setup
│   ├── input-devices/          # Keyboard/mouse notes
│   └── networking/             # TP-Link CPE210 wireless bridge
└── services/                    # Systemd service configurations
```

## Troubleshooting

### Common Issues

**Issue**: Jetson not booting after flash
- Verify power supply provides adequate current (>=60W recommended)
- Try recovery mode: Hold recovery button, press reset, release after 2 seconds
- Re-flash using SDK Manager in recovery mode

**Issue**: GPU not detected or low performance
- Verify power mode: `sudo nvpmodel -q`
- Enable max clocks: `sudo jetson_clocks`
- Check thermal throttling: `tegrastats` (temps should be <80°C)

**Issue**: USB devices not detected
- Check USB port type (USB 2.0 vs 3.0)
- Verify power: Some devices need powered USB hub
- Check dmesg: `dmesg | tail -50`

**Issue**: Network performance issues
- Use Gigabit Ethernet for critical connections
- For WiFi, ensure antenna connected properly
- Check link speed: `ethtool eth0`

## Additional Resources

- [NVIDIA Jetson Orin NX Module Data Sheet](https://developer.nvidia.com/jetson-orin-nx)
- [Yahboom Carrier Board Documentation](https://www.yahboom.net/)
- [JetPack SDK Documentation](https://docs.nvidia.com/jetson/jetpack/)
- [Jetson Developer Forums](https://forums.developer.nvidia.com/c/agx-autonomous-machines/jetson-embedded-systems/)
- [jetson-stats Tool](https://github.com/rbonghi/jetson_stats)

## Hardware Notes

### GPS Module
- **VK-162 GPS USB Dongle** - Currently deployed
  - Connection: Anker 555 USB-C Hub (via USB-C to USB-A adapter)
  - 190cm (6.2 foot) USB cable, magnetic antenna mount
  - GPS + GLONASS/Beidou support
  - No driver needed on Linux (uses standard USB serial)
  - Provides precise location stamping for wildlife observations

## Next Steps

1. Run the baseline setup: `sudo bash baseline-setup.sh`
2. Configure hardware components (see `hardware/` subdirectories)
3. Set up application services (see `../../services/`)
4. Deploy and test agents (see `../../agents/`)
