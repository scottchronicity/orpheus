# Orpheus Hardware Component List

**Authoritative hardware inventory for the Orpheus wildlife monitoring station.**
Last updated: 2025-11-07

## Computing Platform

### Main Computer
- **Yahboom Jetson Orin NX 16GB Developer Kit**
  - NVIDIA Jetson Orin NX 16GB module (157 TOPS AI performance)
  - Yahboom carrier board
  - Native ports: 4× USB-A 3.2, 1× USB-C 3.2, DisplayPort, M.2, Ethernet, GPIO

### Storage
- **Samsung T7 2TB External SSD** (already owned)
  - Connection: Jetson native USB-C port

### Display (Development Only)
- **HMTECH 7 Inch Raspberry Pi Screen** (800×480 IPS LCD)
  - Connection: Anker 555 USB-C Hub → HDMI → Monitor
  - Hub connects to Jetson via USB-C to USB-A adapter → Jetson USB-A port
  - **Note:** Jetson DisplayPort is UNUSED

### Input Devices
- **Logitech K400 Plus Wireless Touch TV Keyboard**
  - USB receiver connects to Anker 7-Port Hub or Jetson USB-A port

### USB Expansion
- **2× Anker 555 USB-C Hub (8-in-1)**
  - 85W PD, 4K HDMI, 10Gbps ports, Gigabit Ethernet, SD/microSD readers
  - Connection: USB-C hub → BLACK+DECKER USB-C to USB-A adapter → Jetson USB-A port
- **1× Anker 7-Port Powered USB Hub** (USB 3.0)
  - 36W power adapter, BC 1.2 charging
  - Connection: Direct to Jetson USB-A port
- **BLACK+DECKER USB-C to USB-A Adapter (2-pack)**
  - Allows Anker 555 hubs to connect to Jetson USB-A ports
- **SABRENT USB 3.0 SD Card Reader (CR-UMSS)**
  - 2-slot (SD + microSD), SuperSpeed USB 3.0

## Audio System

### Microphones (Research-Grade)
- **4× Clippy EM272Z1 XLR Microphones** (matched set)
  - Specifications: 14dB self-noise, 20Hz-20kHz, scientifically validated
  - Vendor: micbooster.com (UK)
  - Wind protection: 4× Rycote Windjammer (grey) + 4× Clippy foam windshields (small)
  - Connection: XLR to UMC404HD

### Audio Interface
- **Behringer UMC404HD USB Audio Interface**
  - 4× XLR/TRS combo inputs with 48V phantom power
  - 24-bit/192kHz sampling, 4×4 USB 2.0
  - Connection: USB to Jetson USB-A port (via Anker 7-Port Hub recommended)

### Audio Output
- **Pyle PDWR42BBT Outdoor Bluetooth Speakers (1 pair)**
  - 3.5" 3-way active/passive, weatherproof, wall/ceiling mount
  - Pre-wired together (active/passive pair)
  - Connection: Bluetooth from Jetson only

### Cables
- **EBXYA XLR Cables 25ft Male to Female (6-pack, multi-color)**
  - 4 in use, 2 spares

## Video System

### Cameras
- **4× Amcrest IP5M-B1186EW-AI-V3 5MP PoE Cameras**
  - H.265 compression, AI detection, IP67 weatherproof
  - RTSP streaming support
  - Connection: CAT6 Ethernet to PoE switch

## Networking

### Network Topology

**Local network at station:**
- All equipment connects to TP-Link TL-SG1210MPE switch
- Jetson + 4 cameras form a local Layer 2 network
- Traffic between cameras and Jetson never leaves the switch (<1ms latency)

**Bridge to house:**
- CPE210 at station connects switch to CPE210 at house
- Transparent Layer 2 bridge (devices appear on same network)
- Only internet-bound traffic traverses the wireless link
- Typical wireless bandwidth: 50-100 Mbps

### Wireless Bridge
- **2× TP-Link CPE210 Outdoor Wireless Access Points**
  - 2.4GHz, 5km+ range, transparent Layer 2 bridge
  - Connects station to house Eero mesh WiFi network
  - One unit at station, one at house

### Network Switch
- **TP-Link TL-SG1210MPE Managed PoE Switch**
  - 8× PoE+ ports (123W power budget), 2× SFP slots
  - Powers all 4 cameras
  - Mounted outside sealed enclosure but inside wooden box
  - Connection: Ethernet from CPE210 + CAT6 to cameras

### Cables
- **5× Amazon Basics CAT6 Ethernet Cable 50ft**
  - 4 for cameras, 1 spare
- **5× Amazon Basics CAT6 Patch Cable 3ft**
  - Internal connections

## Power System

### Current Configuration
- **POWGRN 100ft 12/3 Outdoor Extension Cord** (12AWG, weatherproof, 15A)
  - From house to station
- **2× IPX6 Outdoor Power Strip** (6 outlets + 3 USB each)
  - One primary, one backup/expansion

### Future/Planned
- Battery backup with DC-DC converters (no inverters)
- Solar panels (future expansion)

## Enclosure System

### Primary Enclosure
- **Attabox AH20168C Polycarbonate Enclosure**
  - Dimensions: 20" × 16" × 8", NEMA 4X/IP66, clear
  - Houses: Jetson, audio interface, USB hubs, future batteries
  - Weatherproof, sealed

### Weatherproofing Hardware
- **AMPELE Cable Glands PG13.5 Waterproof (20-pack)**
  - 6-12mm cable range
- **XINGO UV-Resistant Zip Ties 12"** (1200 pack, 75lb tensile)

### Outer Protection
- **Custom wooden enclosure** (materials not yet purchased)
  - Houses polycarbonate enclosure + PoE switch
  - Weather protection and thermal management
  - Includes ventilation system

### Mounting
- **12-foot mast** (materials not yet purchased)
  - Camera mounting height: 8-10 feet
  - Ground-level enclosure with elevated camera positions

## Additional Hardware

### GPS 
- **VK-162 GPS USB Dongle** (deployed)
  - Connection: Anker 555 USB-C Hub (via USB-C to USB-A adapter)
  - 190cm (6.2 foot) USB cable, magnetic antenna mount
  - GPS + GLONASS/Beidou support
  - No driver needed on Linux

## Network Infrastructure (Already Owned)

- **Eero mesh WiFi system** (at house)
  - Target for CPE210 wireless bridge

## Notes

- All USB devices connect to Jetson USB-A ports (via hubs where needed)
- Jetson native USB-C port reserved for Samsung T7 SSD
- Jetson DisplayPort is UNUSED
- Display connection: Anker 555 Hub HDMI → HMTECH monitor
- Purchased 4 cameras at $64.99 each (below $70 estimate)
- XLR cables: 6-pack purchased, 4 in use, 2 spares
- CAT6 cables: 5× 50ft purchased, 4 in use, 1 spare
- Wooden enclosure materials not yet purchased (~$327 estimated)
```

---
