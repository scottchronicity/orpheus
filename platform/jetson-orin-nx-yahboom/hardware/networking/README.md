# TP-Link CPE210 Wireless Bridge Configuration

## Overview

The TP-Link CPE210 is a 2.4GHz outdoor wireless access point/bridge designed for long-range point-to-point or point-to-multipoint connections. It's used to extend network connectivity to remote locations where running Ethernet cables is impractical.

### Orpheus Network Topology

**Goal**: Connect remote wildlife monitoring station to house network while keeping local traffic local

```
Station Equipment (All on TP-Link TL-SG1210MPE Switch):
┌─────────────────────────────────────────┐
│  Local Network (Layer 2 Switching)     │
│  - 4× Amcrest Cameras (PoE)            │
│  - Jetson Orin NX                       │
│  - PoE Switch                           │
│                                         │
│  Camera ↔ Jetson: <1ms latency         │
│  Traffic NEVER leaves the switch       │
└─────────────────┬───────────────────────┘
                  │
           CPE210-B (Client)
                  │
          ~~~~ 2.4GHz WiFi ~~~~
          (50-100 Mbps typical)
                  │
           CPE210-A (AP)
                  │
          Eero Mesh Network
                  │
              Internet

Traffic Patterns:
├─ Camera → Jetson: Local switch only (gigabit, <1ms)
├─ Jetson → Camera: Local switch only (gigabit, <1ms)
├─ Jetson → Internet: Through CPE210 bridge
└─ Remote Access → Jetson: Through CPE210 bridge
```

**Key Points**:
- **2× CPE210 units**: One at house (AP), one at station (Client)
- **PoE Switch**: TP-Link TL-SG1210MPE powers all 4 cameras and provides network connectivity
- **Switch Location**: Outside sealed enclosure but inside wooden box
- **Cables**: Amazon Basics CAT6 (4× 50ft for cameras, 1 spare)
- **Local traffic stays local**: The switch routes camera-Jetson packets directly (Layer 2 switching)
- **Only internet-bound traffic** uses the wireless bridge

### Specifications
- **Frequency**: 2.4GHz (802.11b/g/n)
- **Max Speed**: 300Mbps
- **Range**: Up to 5km+ (line of sight)
- **Antenna**: 9dBi directional antenna (built-in)
- **Power**: PoE (24V passive) via included adapter
- **Ports**: 2x 10/100Mbps Ethernet (1 LAN, 1 PoE)
- **Weather**: IP64 rated for outdoor use
- **Operating Modes**: AP, Client, Repeater, Bridge (AP Client)

## Hardware Setup

### Physical Installation

1. **Mounting**
   - Mount CPE210 with clear line of sight to main network location
   - Use included pole mounting kit
   - Point antenna toward receiving location
   - Ensure weatherproof cable connections

2. **Power Connection**
   - Use included PoE injector (24V passive PoE)
   - **PoE Port**: Connect to CPE210 via outdoor-rated Ethernet cable
   - **LAN Port**: Connect to network switch or Jetson
   - Power injector goes indoors (not weatherproof)

3. **Network Connection**
   - Connect PoE LAN port to your main network switch
   - Or connect directly to Jetson Ethernet port if using as client

## Initial Configuration

### Access Web Interface

1. **Connect to CPE210**
   - Connect computer to LAN port on PoE injector
   - Default IP: `192.168.0.254`
   - Default credentials: `admin` / `admin`

2. **Login**
   - Open browser: `http://192.168.0.254`
   - Enter default credentials
   - **IMPORTANT**: Change password immediately

### Basic Setup Wizard

The CPE210 has a setup wizard for common configurations:

1. Navigate to Quick Setup
2. Select operation mode (see modes below)
3. Follow wizard to configure
4. Save and reboot

## Configuration Modes

### Mode 1: Access Point (AP) Mode
**Use Case**: Provide wireless network at remote location

```
Main Network (Jetson) --[Ethernet]--> CPE210-A (AP Mode) ~~[Wireless]~~ Devices
```

**Configuration**:
- **Mode**: Access Point
- **SSID**: `Orpheus-Remote`
- **Security**: WPA2-PSK, strong password
- **Channel**: 1, 6, or 11 (avoid interference)
- **IP**: Static (e.g., 192.168.1.250)

### Mode 2: Client/Bridge Mode (Most Common)
**Use Case**: Extend network to remote Jetson or cameras

```
Main Network --[Ethernet]--> CPE210-A (AP) ~~[Wireless]~~ CPE210-B (Client) --[Ethernet]--> Remote Devices
```

**CPE210-A Configuration (Access Point)**:
- **Mode**: Access Point
- **SSID**: `Orpheus-Bridge`
- **Channel**: Fixed (e.g., Channel 11)
- **Wireless Security**: WPA2-PSK
- **IP**: 192.168.1.251

**CPE210-B Configuration (Client)**:
- **Mode**: Client (or Bridge/AP Client)
- **Survey**: Scan for `Orpheus-Bridge`
- **Lock to AP MAC**: Yes (recommended for stability)
- **IP**: 192.168.1.252
- **DHCP**: Disabled on client bridge

### Mode 3: Repeater Mode
**Use Case**: Extend wireless range

**Configuration**:
- **Mode**: Repeater
- **Root AP**: Select existing network to extend
- **Extended SSID**: Can be same or different

## Detailed Configuration Steps

### Step 1: Set Operation Mode

**Network > Operation Mode**:
- Select: `Client` (for receiving end) or `Access Point` (for transmitting end)
- Save

### Step 2: Wireless Settings

**Network > Wireless**:

For **Access Point**:
```
Mode: 11bgn mixed
SSID: Orpheus-Bridge
Channel: 11 (or least congested)
Channel Width: 20MHz (more stable) or 40MHz (faster)
Tx Power: 27 dBm (max)
```

For **Client**:
```
Mode: 11bgn mixed
Click "Survey" to scan for networks
Select: Orpheus-Bridge
Lock to AP: [Enable and select MAC address]
```

### Step 3: Wireless Security

**Network > Wireless Security**:
```
Security Mode: WPA2-PSK
Encryption: AES
Password: [Strong password, 20+ characters recommended]
```

### Step 4: Network Settings

**Network > LAN**:

For **Primary AP** (192.168.1.251):
```
IP Address: 192.168.1.251
Subnet Mask: 255.255.255.0
Gateway: 192.168.1.1 (your router)
```

For **Client** (192.168.1.252):
```
IP Address: 192.168.1.252
Subnet Mask: 255.255.255.0
Gateway: 192.168.1.1
DNS: 8.8.8.8, 8.8.4.4
```

### Step 5: MAC Clone (if needed)

If ISP requires MAC address registration:
- **Network > MAC Clone**
- Clone PC MAC address or enter manually

## Testing the Connection

### Test Link Quality

From CPE210 web interface:
- **Status > Wireless**
- Check: Signal strength, noise, TX/RX rates
- Good signal: -65 dBm or better
- Marginal: -70 to -75 dBm
- Poor: -80 dBm or worse

### Ping Test from Jetson

```bash
# Ping the CPE210 AP
ping 192.168.1.251

# Ping through the wireless bridge
ping 192.168.1.252

# Ping remote device (e.g., camera through bridge)
ping 192.168.1.201

# Continuous ping to monitor stability
ping -i 0.5 192.168.1.252
```

### Bandwidth Test

```bash
# Install iperf3 (already in baseline-setup.sh)
sudo apt-get install iperf3

# On remote device (server):
iperf3 -s

# On Jetson (client):
iperf3 -c <remote_device_ip> -t 30

# Expected throughput: 50-150 Mbps depending on distance/obstacles
```

### Monitor Connection

```bash
# Check link status continuously
watch -n 1 'ping -c 1 192.168.1.252 | grep time'

# Monitor with mtr (better than ping)
sudo apt-get install mtr
mtr 192.168.1.252
```

## Optimization

### Antenna Alignment

1. **Access CPE210 web interface** (both units)
2. **Status > Wireless** - Note signal strength
3. **Physically adjust antenna** direction
4. **Goal**: Signal strength -65 dBm or better
5. **Fine-tune**: Small adjustments make big difference
6. **Lock down**: Secure mounting once optimal

### Channel Selection

```bash
# Scan for interference (from Linux machine)
sudo iwlist wlan0 scan | grep -E "Channel|ESSID|Quality"

# Use least congested channel (1, 6, or 11 recommended)
```

In CPE210:
- **Network > Wireless**
- Set fixed channel (don't use Auto)
- Channels 1, 6, 11 don't overlap
- Use 20MHz width for stability

### Airtime Fairness

For multiple client connections:
- **Network > Wireless > Advanced**
- Enable `Airtime Fairness`
- Prevents slow clients from degrading overall performance

### QoS Settings

**Network > QoS**:
```
Enable QoS: Yes
Uplink Bandwidth: 80% of tested speed
Downlink Bandwidth: 80% of tested speed

Priority:
- High: RTSP (port 554), SSH (port 22)
- Medium: HTTP (port 80), MQTT (port 1883)
- Low: Everything else
```

## Troubleshooting

### No Wireless Connection

1. **Check Power**
   - Verify PoE injector LED is on
   - Check cable connections

2. **Check Mode**
   - AP side must be in AP mode
   - Client side must be in Client mode

3. **Check SSID/Password**
   - Client must match AP exactly (case-sensitive)
   - Re-enter password if unsure

4. **Survey for Network**
   - In Client mode: Network > Wireless > Survey
   - Verify AP is visible
   - Check signal strength

5. **Reset to Factory**
   - Hold reset button 10+ seconds
   - Reconfigure from scratch

### Poor Performance

1. **Check Signal Strength**
   - Target: -65 dBm or better
   - Realign antennas if needed

2. **Check for Interference**
   - 2.4GHz is crowded
   - Change channel if needed
   - Use WiFi analyzer app on phone

3. **Check Distance/Obstacles**
   - Maximum range: ~5km line-of-sight
   - Trees/buildings reduce range significantly
   - Consider raising mounting height

4. **Test with iperf3**
   - Measure actual throughput
   - Expected: 50-150 Mbps
   - If much lower, check alignment/interference

### Intermittent Disconnections

1. **Lock to AP MAC Address**
   - In Client mode: enable "Lock to AP"
   - Prevents roaming to other networks

2. **Disable Auto Channel**
   - Set fixed channel on both units
   - Auto can cause disconnects

3. **Check Power Supply**
   - Ensure PoE adapter is rated correctly
   - Long cable runs can cause voltage drop

4. **Update Firmware**
   - System > Backup/Restore > Firmware Upgrade
   - Download latest from TP-Link website

## Firmware Update

1. **Download Firmware**
   - Visit: https://www.tp-link.com/us/support/download/cpe210/
   - Download latest firmware for your hardware version

2. **Backup Configuration**
   - System > Backup/Restore > Backup
   - Save configuration file

3. **Upload Firmware**
   - System > Backup/Restore > Firmware Upgrade
   - Select downloaded .bin file
   - Upload and wait 5-10 minutes
   - **DO NOT POWER OFF during update**

4. **Verify**
   - Login after reboot
   - Check System > System Info > Firmware Version

## Security Best Practices

1. **Change Default Password**
   - System > User Account
   - Use strong, unique password

2. **Disable Remote Management**
   - System > Management > Remote Management
   - Set to: Local Only

3. **Use Strong Wireless Encryption**
   - WPA2-PSK with AES only
   - 20+ character password

4. **Keep Firmware Updated**
   - Check quarterly for updates
   - Apply security patches promptly

5. **Disable WPS**
   - Network > Wireless > WPS
   - Disable (security risk)

## Integration with Orpheus

### Use Cases

1. **Remote Camera Access**
   - Extend network to PoE cameras
   - Stream RTSP over wireless bridge
   - Monitor signal quality for reliability

2. **Distributed Sensors**
   - Connect remote sensor nodes
   - Low-latency MQTT communication
   - Redundant paths if possible

3. **Backup Connectivity**
   - Secondary network path
   - Automatic failover (requires routing config)

## Example Network Topology

```
Main Building:
  Jetson Orin NX (192.168.1.100)
    |
  [Gigabit Switch]
    |
  CPE210-A (AP Mode, 192.168.1.251)
    |
   ~~~~ Wireless Bridge (2.4GHz) ~~~~
    |
  CPE210-B (Client Mode, 192.168.1.252)
    |
  [PoE Switch]
    |-- Amcrest Camera 1 (192.168.1.201)
    |-- Amcrest Camera 2 (192.168.1.202)
    |-- Amcrest Camera 3 (192.168.1.203)
```

## Monitoring Script

```bash
#!/bin/bash
# monitor-bridge.sh - Monitor CPE210 wireless bridge

BRIDGE_IP="192.168.1.252"
LOG_FILE="/var/log/orpheus/bridge-monitor.log"

while true; do
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Ping test
    if ping -c 1 -W 2 $BRIDGE_IP &> /dev/null; then
        # Get latency
        latency=$(ping -c 5 $BRIDGE_IP | tail -1 | awk '{print $4}' | cut -d '/' -f 2)
        echo "$timestamp - OK - Latency: ${latency}ms" | tee -a $LOG_FILE
    else
        echo "$timestamp - FAIL - Bridge unreachable!" | tee -a $LOG_FILE
        # Could trigger alert here
    fi
    
    sleep 60
done
```

## Additional Resources

- [TP-Link CPE210 User Guide](https://www.tp-link.com/us/support/download/cpe210/)
- [Pharos Control Documentation](https://www.tp-link.com/us/support/faq/1368/)
- [Wireless Bridge Setup Guide](https://www.tp-link.com/us/support/faq/2024/)
- [Long Range WiFi Best Practices](https://www.tp-link.com/us/support/faq/2670/)
