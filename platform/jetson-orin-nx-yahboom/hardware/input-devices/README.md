# Input Devices Configuration

## Overview

Configuration for various input devices on the Jetson Orin NX, including keyboards, mice, GPIO buttons, and other human interface devices (HIDs). While Orpheus primarily operates autonomously, input devices are useful for development, debugging, and manual control.

### Orpheus Input Hardware
- **Keyboard**: Logitech K400 Plus Wireless Touch TV Keyboard
  - Integrated touchpad (eliminates need for separate mouse)
  - USB wireless receiver (2.4GHz)
  - Connection: USB receiver → Anker 7-Port Hub or direct to Jetson USB-A port
  - Range: Up to 33 feet (10m)

### Supported Input Types
- **USB Keyboards** - Standard USB or wireless (like K400 Plus)
- **USB Mice/Trackpads** - HID-compliant devices
- **Bluetooth Input** - Wireless keyboards/mice
- **GPIO Buttons** - Physical buttons connected to GPIO pins
- **Touch Screen** - USB or I2C touch controllers
- **Game Controllers** - Xbox, PlayStation, or generic USB controllers

## Logitech K400 Plus Setup

### Hardware Connection

```bash
# The K400 Plus uses a USB wireless receiver
# Connection options:
# Option 1: Direct to Jetson USB-A port (preferred for low latency)
# Option 2: Via Anker 7-Port Powered USB Hub

# Insert the USB receiver into USB port
# Keyboard should auto-connect (no pairing needed)

# Verify detection
lsusb | grep -i logitech

# Should show:
# Bus 001 Device 00X: ID 046d:XXXX Logitech, Inc. Wireless Touch Keyboard K400 Plus
```

### Touchpad Configuration

The K400 Plus has an integrated touchpad that functions as a mouse:

```bash
# Check if touchpad is detected
xinput list

# Should show both keyboard and touchpad:
# ⎜   ↳ Logitech Wireless Touch Keyboard K400 Plus    id=XX [slave keyboard]
# ⎜   ↳ Logitech Wireless Touch Keyboard K400 Plus    id=YY [slave pointer]

# Adjust touchpad sensitivity
xinput list-props YY  # Replace YY with touchpad ID

# Adjust pointer speed (-1.0 to 1.0)
xinput set-prop YY "libinput Accel Speed" 0.5

# Enable/disable tap-to-click
xinput set-prop YY "libinput Tapping Enabled" 1
```

### Function Keys

The K400 Plus has dedicated media and function keys:
- **F1-F12**: Standard function keys
- **Media Keys**: Volume up/down, mute, play/pause
- **Left Mouse Button**: Dedicated button next to touchpad

## USB Keyboard and Mouse (General)

### Verify Detection

```bash
# List USB devices
lsusb

# Look for input devices (e.g., Logitech, Microsoft, etc.)
# Example output:
# Bus 001 Device 004: ID 046d:c52b Logitech, Inc. Unifying Receiver

# List input devices
ls -l /dev/input/

# Should show:
# event0, event1, etc. - Event devices
# mouse0, mouse1, etc. - Mouse devices
# by-id/               - Devices by ID
# by-path/             - Devices by path

# Check input device details
cat /proc/bus/input/devices

# Real-time event monitoring
sudo evtest
# Select device from list to see events
```

### Configure Keyboard Layout

```bash
# Set keyboard layout (console)
sudo dpkg-reconfigure keyboard-configuration

# Set keyboard layout (X11)
setxkbmap us  # US layout
setxkbmap gb  # UK layout
setxkbmap de  # German layout

# Make permanent
sudo nano /etc/default/keyboard

# Modify:
XKBLAYOUT="us"
XKBVARIANT=""
```

### Configure Mouse Settings

```bash
# Check mouse acceleration
xinput list

# Get device ID (e.g., 9)
xinput list-props 9

# Disable mouse acceleration
xinput set-prop 9 "libinput Accel Speed" 0

# Adjust pointer speed (-1.0 to 1.0)
xinput set-prop 9 "libinput Accel Speed" 0.5

# Set mouse buttons for left-handed
xinput set-button-map 9 3 2 1
```

## Bluetooth Input Devices

### Pair Bluetooth Keyboard/Mouse

```bash
# Start bluetooth
sudo systemctl start bluetooth

# Interactive pairing
bluetoothctl

# In bluetoothctl:
[bluetooth]# power on
[bluetooth]# agent on
[bluetooth]# default-agent
[bluetooth]# scan on

# Put keyboard/mouse in pairing mode
# When device appears:
[bluetooth]# pair AA:BB:CC:DD:EE:FF
[bluetooth]# trust AA:BB:CC:DD:EE:FF
[bluetooth]# connect AA:BB:CC:DD:EE:FF
[bluetooth]# exit
```

### Auto-Connect on Boot

```bash
# Trust device (done above)
# Should auto-connect on next boot

# If not, create systemd service:
sudo nano /etc/systemd/system/bluetooth-input-autoconnect.service
```

Add:

```ini
[Unit]
Description=Auto-connect Bluetooth Input Devices
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=oneshot
ExecStart=/usr/bin/bluetoothctl connect AA:BB:CC:DD:EE:FF
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl enable bluetooth-input-autoconnect.service
```

## GPIO Buttons

### Jetson GPIO Overview

The Yahboom carrier board provides access to GPIO pins for custom buttons and switches.

```bash
# Install Jetson GPIO library
sudo pip3 install Jetson.GPIO

# Check available GPIO pins
sudo cat /sys/kernel/debug/gpio
```

### GPIO Pin Mapping

Refer to Yahboom carrier board documentation for specific pin mappings. Typical layout:

```
Pin 7  - GPIO79  (J41.7)
Pin 11 - GPIO80  (J41.11)
Pin 12 - GPIO81  (J41.12)
Pin 13 - GPIO82  (J41.13)
...
```

### Simple Button Example

```python
#!/usr/bin/env python3
import Jetson.GPIO as GPIO
import time

# Pin Definitions (update based on your wiring)
BUTTON_PIN = 7  # Physical pin 7 (GPIO79)
LED_PIN = 12    # Physical pin 12 (GPIO81)

# Setup
GPIO.setmode(GPIO.BOARD)  # Use physical pin numbering
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)

print("Button test - Press button to toggle LED")
print("Press Ctrl+C to exit")

try:
    while True:
        # Read button state (active low with pull-up)
        button_state = GPIO.input(BUTTON_PIN)
        
        if button_state == GPIO.LOW:
            print("Button pressed!")
            GPIO.output(LED_PIN, GPIO.HIGH)
            time.sleep(0.5)  # Debounce
            GPIO.output(LED_PIN, GPIO.LOW)
            
        time.sleep(0.1)
        
except KeyboardInterrupt:
    print("\nExiting...")
    
finally:
    GPIO.cleanup()
```

### Button with Callback (Event-driven)

```python
#!/usr/bin/env python3
import Jetson.GPIO as GPIO
import time
import signal
import sys

BUTTON_PIN = 7

def button_callback(channel):
    """Called when button is pressed"""
    print(f"Button pressed on pin {channel}")
    # Add your action here
    # e.g., trigger recording, send MQTT message, etc.

def signal_handler(sig, frame):
    """Handle Ctrl+C"""
    print("\nCleaning up...")
    GPIO.cleanup()
    sys.exit(0)

# Setup
GPIO.setmode(GPIO.BOARD)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Add event detection (falling edge = button press with pull-up)
GPIO.add_event_detect(BUTTON_PIN, GPIO.FALLING, 
                      callback=button_callback, 
                      bouncetime=300)  # 300ms debounce

signal.signal(signal.SIGINT, signal_handler)

print("Button monitoring active. Press Ctrl+C to exit.")
signal.pause()  # Wait indefinitely
```

### Multi-Button Input Panel

```python
#!/usr/bin/env python3
import Jetson.GPIO as GPIO

class ButtonPanel:
    def __init__(self, button_pins):
        """
        button_pins: dict of {name: pin_number}
        e.g., {"start": 7, "stop": 11, "reset": 12}
        """
        self.buttons = button_pins
        GPIO.setmode(GPIO.BOARD)
        
        for name, pin in self.buttons.items():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(pin, GPIO.FALLING,
                                callback=lambda ch, n=name: self.on_button(n),
                                bouncetime=300)
    
    def on_button(self, button_name):
        """Override this method with your button actions"""
        print(f"Button '{button_name}' pressed")
        
        # Example actions:
        if button_name == "start":
            print("Starting system...")
        elif button_name == "stop":
            print("Stopping system...")
        elif button_name == "reset":
            print("Resetting...")
    
    def cleanup(self):
        GPIO.cleanup()

# Example usage
if __name__ == "__main__":
    panel = ButtonPanel({
        "start": 7,
        "stop": 11,
        "reset": 12
    })
    
    try:
        print("Button panel active. Press Ctrl+C to exit.")
        signal.pause()
    except KeyboardInterrupt:
        panel.cleanup()
```

## USB Game Controllers

### Detect Controller

```bash
# List joystick devices
ls -l /dev/input/js*

# Should show:
# /dev/input/js0

# Install joystick utilities
sudo apt-get install joystick jstest-gtk

# Test controller
jstest /dev/input/js0

# Calibrate controller (if needed)
jscal /dev/input/js0
```

### Python Controller Input

```bash
# Install pygame (includes joystick support)
pip3 install pygame
```

```python
#!/usr/bin/env python3
import pygame

pygame.init()
pygame.joystick.init()

# Check for controllers
if pygame.joystick.get_count() == 0:
    print("No controller detected")
    exit(1)

# Initialize first controller
joystick = pygame.joystick.Joystick(0)
joystick.init()

print(f"Controller: {joystick.get_name()}")
print(f"Axes: {joystick.get_numaxes()}")
print(f"Buttons: {joystick.get_numbuttons()}")
print(f"Hats: {joystick.get_numhats()}")
print("\nPress Ctrl+C to exit")

try:
    while True:
        pygame.event.pump()
        
        # Read axes
        for i in range(joystick.get_numaxes()):
            axis = joystick.get_axis(i)
            if abs(axis) > 0.1:  # Deadzone
                print(f"Axis {i}: {axis:.2f}")
        
        # Read buttons
        for i in range(joystick.get_numbuttons()):
            button = joystick.get_button(i)
            if button:
                print(f"Button {i} pressed")
        
        pygame.time.wait(100)
        
except KeyboardInterrupt:
    print("\nExiting...")
    pygame.quit()
```

## Touch Screen Input

### USB Touch Screen

```bash
# Check if detected
xinput list

# Should show touch device, e.g.:
# ⎜   ↳ eGalax Inc. USB TouchController  id=10 [slave  pointer  (2)]

# Calibrate touch screen
xinput_calibrator

# Follow on-screen instructions
# Copy output to create calibration file
```

### Save Calibration

```bash
sudo nano /etc/X11/xorg.conf.d/99-calibration.conf
```

Paste calibration output, example:

```
Section "InputClass"
    Identifier "calibration"
    MatchProduct "eGalax Inc. USB TouchController"
    Option "Calibration" "3996 122 208 3996"
    Option "SwapAxes" "0"
EndSection
```

## Input Device Mapping

### Create Persistent Device Names

```bash
# Create udev rules for consistent naming
sudo nano /etc/udev/rules.d/99-input-devices.rules
```

Add rules to identify devices:

```
# Keyboard
SUBSYSTEM=="input", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c52b", SYMLINK+="input/orpheus-keyboard"

# Mouse
SUBSYSTEM=="input", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c077", SYMLINK+="input/orpheus-mouse"

# Game controller
SUBSYSTEM=="input", ATTRS{idVendor}=="045e", ATTRS{idProduct}=="02ea", SYMLINK+="input/orpheus-gamepad"
```

Reload udev:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger

# Check new symlinks
ls -l /dev/input/orpheus-*
```

## Input Event Monitoring

### System-wide Input Logger

```python
#!/usr/bin/env python3
import evdev
from evdev import InputDevice, categorize, ecodes

# List all input devices
devices = [evdev.InputDevice(path) for path in evdev.list_devices()]

print("Available devices:")
for dev in devices:
    print(f"{dev.path} - {dev.name}")

# Select device
device_path = devices[0].path  # Change index as needed
device = InputDevice(device_path)

print(f"\nMonitoring: {device.name}")
print("Press Ctrl+C to stop\n")

try:
    for event in device.read_loop():
        if event.type == ecodes.EV_KEY:
            key_event = categorize(event)
            print(f"Key: {key_event.keycode}, State: {key_event.keystate}")
        elif event.type == ecodes.EV_REL:  # Mouse movement
            if event.code == ecodes.REL_X:
                print(f"Mouse X: {event.value}")
            elif event.code == ecodes.REL_Y:
                print(f"Mouse Y: {event.value}")
            
except KeyboardInterrupt:
    print("\nStopped")
```

## Troubleshooting

### Device Not Detected

```bash
# Check USB
lsusb

# Check kernel messages
dmesg | tail -30

# For USB devices, check power
lsusb -v | grep -i "MaxPower"

# Try different USB port
# USB 3.0 ports preferred for wireless receivers
```

### Keyboard Not Working

```bash
# Check if detected
cat /proc/bus/input/devices | grep -A 5 Keyboard

# Test raw input
sudo cat /dev/input/event2  # Replace with correct event number
# Press keys, should see garbage (binary data)

# If in X11, restart input
sudo systemctl restart gdm3
```

### GPIO Permissions

```bash
# Add user to gpio group
sudo usermod -aG gpio $USER

# Logout and login

# Or run with sudo (not recommended for production)
sudo python3 gpio_script.py
```

### GPIO Pin Already in Use

```bash
# List GPIO usage
sudo cat /sys/kernel/debug/gpio

# Unexport GPIO before reuse
echo 79 | sudo tee /sys/class/gpio/unexport

# Or in Python:
GPIO.cleanup()  # Releases all GPIO pins
```

## Integration with Orpheus

### Use Cases

1. **Manual Control**
   - Start/stop recording with button press
   - Reset system state
   - Emergency stop

2. **Development/Debugging**
   - Keyboard shortcuts for testing
   - Mouse for GUI interaction
   - Controller for robot/PTZ camera control

3. **Status Indicators**
   - LED feedback for system status
   - Buzzer for audio alerts
   - Physical switch for modes

### Example: MQTT Button Bridge

```python
#!/usr/bin/env python3
"""
Send MQTT messages when GPIO buttons are pressed
"""
import Jetson.GPIO as GPIO
import paho.mqtt.client as mqtt
import time

MQTT_BROKER = "localhost"
MQTT_PORT = 1883

BUTTON_CONFIG = {
    7: "orpheus/button/start",
    11: "orpheus/button/stop",
    12: "orpheus/button/reset"
}

# Setup MQTT
client = mqtt.Client()
client.connect(MQTT_BROKER, MQTT_PORT)
client.loop_start()

# Setup GPIO
GPIO.setmode(GPIO.BOARD)

def button_callback(channel):
    """Publish MQTT message on button press"""
    topic = BUTTON_CONFIG.get(channel)
    if topic:
        client.publish(topic, "pressed")
        print(f"Published to {topic}")

# Configure all buttons
for pin, topic in BUTTON_CONFIG.items():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(pin, GPIO.FALLING, 
                         callback=button_callback,
                         bouncetime=300)

print("Button MQTT bridge active")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    GPIO.cleanup()
    client.loop_stop()
    client.disconnect()
```

## Additional Resources

- [Jetson GPIO Library](https://github.com/NVIDIA/jetson-gpio)
- [Linux Input Documentation](https://www.kernel.org/doc/Documentation/input/)
- [evdev Python Library](https://python-evdev.readthedocs.io/)
- [pygame Joystick Documentation](https://www.pygame.org/docs/ref/joystick.html)
- [xinput Manual](https://www.x.org/releases/current/doc/man/man1/xinput.1.xhtml)
