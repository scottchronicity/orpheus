#!/usr/bin/env python3
"""
Orpheus AudioScope - Real-time audio diagnostics tool.

Displays audio signal levels, XRUN counts, and system health information
using a curses-based terminal UI. Designed for diagnosing audio hardware
issues on Jetson and other embedded platforms.

Usage:
    ./orpheus_audioscope.py                    # Run normally
    sudo chrt -f 90 ./orpheus_audioscope.py    # Run with RT priority

Controls:
    b     - Cycle block sizes [1024, 2048, 4096, 8192]
    r     - Reset XRUN counter
    q     - Quit

Requirements:
    - orpheus_common package installed
    - sounddevice package installed
    - curses-compatible terminal
"""

import argparse
import curses
import math
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

import numpy as np

# Add parent paths for development (agent src and orpheus-common)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "platform", "orpheus-common", "src"
    ),
)

try:
    import sounddevice as sd
except ImportError:
    print("ERROR: sounddevice not installed. Run: pip install sounddevice")
    sys.exit(1)

from orpheus_common.diagnostics.audio_health import (
    AudioHealthMonitor,
    LEVEL_THRESHOLD_GREEN,
    LEVEL_THRESHOLD_YELLOW,
    NO_SIGNAL_THRESHOLD,
)


# Available block sizes to cycle through
BLOCK_SIZES = [1024, 2048, 4096, 8192]

# Color pair definitions
COLOR_GREEN = 1
COLOR_YELLOW = 2
COLOR_RED = 3
COLOR_CYAN = 4
COLOR_WHITE = 5
COLOR_MAGENTA = 6


class AudioScope:
    """Real-time audio scope with curses UI."""

    def __init__(
        self,
        device: Optional[str] = None,
        sample_rate: int = 48000,
        block_size: int = 1024,
        num_channels: int = 4,
    ) -> None:
        """
        Initialize the audio scope.

        Args:
            device: Audio device name or index (None for default)
            sample_rate: Sample rate in Hz
            block_size: Audio buffer size in samples
            num_channels: Number of input channels to monitor
        """
        self.device = device
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.num_channels = num_channels
        self.block_size_index = BLOCK_SIZES.index(block_size) if block_size in BLOCK_SIZES else 0

        self.monitor = AudioHealthMonitor()
        self.stream: Optional[sd.InputStream] = None
        self.running = False
        self.device_name = "Unknown"

    def _find_device(self) -> Optional[int]:
        """Find the audio device by name or return default."""
        if self.device is None:
            return None

        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if self.device.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
                return idx
        return None

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        """Process audio callback."""
        # Record timing
        self.monitor.record_callback_timing()

        # Check for XRUNs
        if status:
            if status.input_overflow:
                self.monitor.record_xrun(is_input_overflow=True)
            if status.input_underflow:
                self.monitor.record_xrun(is_input_underflow=True)

        # Calculate per-channel RMS levels
        for ch in range(min(indata.shape[1], self.num_channels)):
            channel_data = indata[:, ch]

            # RMS to dB
            rms = np.sqrt(np.mean(channel_data**2))
            if rms > 0:
                db = 20 * math.log10(rms)
            else:
                db = -100.0

            # Record level
            self.monitor.record_channel_level(f"ch{ch + 1}", db)

    def start_stream(self) -> bool:
        """Start the audio input stream."""
        try:
            device_idx = self._find_device()

            # Get device info
            if device_idx is not None:
                dev_info = sd.query_devices(device_idx)
            else:
                dev_info = sd.query_devices(kind="input")

            self.device_name = dev_info["name"]
            actual_channels = min(self.num_channels, dev_info["max_input_channels"])

            self.stream = sd.InputStream(
                device=device_idx,
                samplerate=self.sample_rate,
                channels=actual_channels,
                dtype="float32",
                blocksize=self.block_size,
                callback=self._audio_callback,
            )

            # Update monitor with hardware config
            self.monitor.set_hardware_config(
                sample_rate=self.sample_rate,
                buffer_size=self.block_size,
                device_name=self.device_name,
                num_channels=actual_channels,
                audio_format="float32",
            )

            self.stream.start()
            self.monitor.set_running(True)
            self.running = True
            return True

        except Exception as e:
            self.device_name = f"ERROR: {e}"
            return False

    def stop_stream(self) -> None:
        """Stop the audio input stream."""
        self.running = False
        self.monitor.set_running(False)
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def cycle_blocksize(self) -> None:
        """Cycle to the next block size and restart stream."""
        self.block_size_index = (self.block_size_index + 1) % len(BLOCK_SIZES)
        self.block_size = BLOCK_SIZES[self.block_size_index]

        if self.running:
            self.stop_stream()
            time.sleep(0.1)
            self.start_stream()


def draw_level_bar(
    win: Any,
    y: int,
    x: int,
    width: int,
    level_db: float,
    peak_db: float,
    channel_name: str,
    has_signal: bool,
) -> None:
    """
    Draw a horizontal level meter bar.

    Args:
        win: Curses window
        y: Y position
        x: X position
        width: Bar width in characters
        level_db: Current level in dB
        peak_db: Peak level in dB
        channel_name: Channel label
        has_signal: Whether signal is present
    """
    # Calculate bar positions (scale: -60dB to 0dB)
    min_db = -60.0
    max_db = 0.0
    db_range = max_db - min_db

    # Clamp levels
    level_db = max(min_db, min(max_db, level_db))
    peak_db = max(min_db, min(max_db, peak_db))

    # Calculate bar widths
    level_pos = int((level_db - min_db) / db_range * width)
    peak_pos = int((peak_db - min_db) / db_range * width)

    # Calculate color zone positions
    green_end = int((LEVEL_THRESHOLD_GREEN - min_db) / db_range * width)
    yellow_end = int((LEVEL_THRESHOLD_YELLOW - min_db) / db_range * width)

    # Draw channel name
    try:
        win.addstr(y, x, f"{channel_name}: ", curses.color_pair(COLOR_WHITE))
    except curses.error:
        pass

    bar_x = x + 6

    # Draw the bar
    for i in range(width):
        char = " "
        color = COLOR_GREEN

        if i < level_pos:
            char = "█"
            if i < green_end:
                color = COLOR_GREEN
            elif i < yellow_end:
                color = COLOR_YELLOW
            else:
                color = COLOR_RED
        elif i == peak_pos and peak_pos > 0:
            char = "│"
            color = COLOR_WHITE

        try:
            win.addstr(y, bar_x + i, char, curses.color_pair(color))
        except curses.error:
            pass

    # Draw dB value
    db_str = f" {level_db:+5.1f}dB"
    try:
        win.addstr(y, bar_x + width + 1, db_str, curses.color_pair(COLOR_WHITE))
    except curses.error:
        pass

    # Draw warning if no signal
    if not has_signal:
        warn_str = " NO SIGNAL - PHANTOM OFF?"
        try:
            win.addstr(y, bar_x + width + 10, warn_str, curses.color_pair(COLOR_MAGENTA) | curses.A_BLINK)
        except curses.error:
            pass


def main(stdscr: Any, args: argparse.Namespace) -> None:
    """Main curses application loop."""
    # Initialize colors
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_GREEN, curses.COLOR_GREEN, -1)
    curses.init_pair(COLOR_YELLOW, curses.COLOR_YELLOW, -1)
    curses.init_pair(COLOR_RED, curses.COLOR_RED, -1)
    curses.init_pair(COLOR_CYAN, curses.COLOR_CYAN, -1)
    curses.init_pair(COLOR_WHITE, curses.COLOR_WHITE, -1)
    curses.init_pair(COLOR_MAGENTA, curses.COLOR_MAGENTA, -1)

    # Configure curses
    curses.curs_set(0)  # Hide cursor
    stdscr.nodelay(True)  # Non-blocking input
    stdscr.timeout(50)  # 50ms refresh rate

    # Create audio scope
    scope = AudioScope(
        device=args.device,
        sample_rate=args.sample_rate,
        block_size=args.blocksize,
        num_channels=args.channels,
    )

    # Start audio stream
    if not scope.start_stream():
        stdscr.addstr(5, 2, f"Failed to start audio: {scope.device_name}")
        stdscr.addstr(7, 2, "Press any key to exit...")
        stdscr.nodelay(False)
        stdscr.getch()
        return

    try:
        while True:
            # Get terminal size
            max_y, max_x = stdscr.getmaxyx()
            bar_width = min(50, max_x - 40)

            # Clear screen
            stdscr.clear()

            # Get current status
            status = scope.monitor.get_status()

            # Draw header
            header = "══════════════════════════════════════════════════════════════════════════════"
            try:
                stdscr.addstr(0, 0, header[:max_x-1], curses.color_pair(COLOR_CYAN))
                stdscr.addstr(1, 0, "  ORPHEUS AUDIOSCOPE - Real-time Audio Diagnostics", curses.color_pair(COLOR_CYAN) | curses.A_BOLD)
                stdscr.addstr(2, 0, header[:max_x-1], curses.color_pair(COLOR_CYAN))
            except curses.error:
                pass

            # Draw hardware config
            hw = status["hardware"]
            config_line = f"Device: {hw['device_name']}"
            try:
                stdscr.addstr(4, 2, config_line[:max_x-4], curses.color_pair(COLOR_WHITE))
            except curses.error:
                pass

            config_line2 = f"Sample Rate: {hw['sample_rate']}Hz | Buffer: {hw['buffer_size']} samples | Channels: {hw['num_channels']} | Format: {hw['format']}"
            try:
                stdscr.addstr(5, 2, config_line2[:max_x-4], curses.color_pair(COLOR_WHITE))
            except curses.error:
                pass

            # Draw XRUN counter prominently
            xrun_count = status["xrun"]["total"]
            xrun_color = COLOR_GREEN if xrun_count == 0 else COLOR_RED
            xrun_str = f"┌─────────────────────┐"
            try:
                stdscr.addstr(7, 2, xrun_str, curses.color_pair(xrun_color))
                stdscr.addstr(8, 2, f"│  GLITCH COUNT: {xrun_count:4d} │", curses.color_pair(xrun_color) | curses.A_BOLD)
                stdscr.addstr(9, 2, "└─────────────────────┘", curses.color_pair(xrun_color))
            except curses.error:
                pass

            # Draw timing stats
            timing = status["timing"]
            timing_str = f"Callback: {timing['callback_interval_ms']:.1f}ms | Jitter: {timing['jitter_ms']:.2f}ms | Count: {timing['callback_count']}"
            try:
                stdscr.addstr(7, 28, timing_str[:max_x-30], curses.color_pair(COLOR_WHITE))
            except curses.error:
                pass

            # Draw system info
            sys_info = status["system"]
            sys_str = f"CPU: {sys_info['cpu_percent']:.1f}% @ {sys_info['cpu_freq_mhz']:.0f}MHz | Mem: {sys_info['memory_percent']:.1f}%"
            if sys_info.get("thermal_temp_c"):
                sys_str += f" | Temp: {sys_info['thermal_temp_c']:.1f}°C"
            try:
                stdscr.addstr(8, 28, sys_str[:max_x-30], curses.color_pair(COLOR_WHITE))
            except curses.error:
                pass

            if sys_info.get("thermal_throttling"):
                try:
                    stdscr.addstr(9, 28, "⚠ THERMAL THROTTLING", curses.color_pair(COLOR_RED) | curses.A_BOLD)
                except curses.error:
                    pass

            # Draw channel level meters
            try:
                stdscr.addstr(11, 2, "Channel Levels:", curses.color_pair(COLOR_CYAN) | curses.A_BOLD)
                stdscr.addstr(12, 2, "─" * (bar_width + 30), curses.color_pair(COLOR_CYAN))
            except curses.error:
                pass

            # Sort channels and draw meters
            channels = sorted(status["channels"], key=lambda c: c["channel_id"])
            for i, ch in enumerate(channels):
                y_pos = 13 + i
                if y_pos < max_y - 4:
                    draw_level_bar(
                        stdscr,
                        y_pos,
                        2,
                        bar_width,
                        ch["level_db"],
                        ch["peak_db"],
                        ch["channel_id"],
                        ch["has_signal"],
                    )

            # If no channels, show placeholder
            if not channels:
                try:
                    stdscr.addstr(13, 2, "No channels detected - waiting for audio data...", curses.color_pair(COLOR_YELLOW))
                except curses.error:
                    pass

            # Draw footer with controls
            footer_y = max_y - 2
            try:
                stdscr.addstr(footer_y - 1, 0, "─" * (max_x - 1), curses.color_pair(COLOR_CYAN))
                controls = f"[b] Cycle blocksize ({scope.block_size})  [r] Reset XRUNs  [q] Quit"
                stdscr.addstr(footer_y, 2, controls, curses.color_pair(COLOR_WHITE))

                # Session duration
                duration = status["session"]["duration_seconds"]
                duration_str = f"Session: {int(duration // 60)}m {int(duration % 60)}s"
                stdscr.addstr(footer_y, max_x - len(duration_str) - 2, duration_str, curses.color_pair(COLOR_WHITE))
            except curses.error:
                pass

            # Refresh display
            stdscr.refresh()

            # Handle input
            try:
                key = stdscr.getch()
                if key == ord("q") or key == ord("Q"):
                    break
                elif key == ord("b") or key == ord("B"):
                    scope.cycle_blocksize()
                elif key == ord("r") or key == ord("R"):
                    scope.monitor.reset()
            except curses.error:
                pass

    finally:
        scope.stop_stream()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Orpheus AudioScope - Real-time audio diagnostics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s                              # Use default audio device
    %(prog)s -d UMC404HD                  # Use specific device
    %(prog)s -b 4096                      # Use larger buffer
    sudo chrt -f 90 %(prog)s              # Run with RT priority

For raw ALSA testing (bypass Python/PortAudio):
    arecord -D hw:UMC404HD -c 4 -f S32_LE -r 48000 -d 5 test.wav
        """,
    )

    parser.add_argument(
        "-d", "--device",
        type=str,
        default=None,
        help="Audio device name or substring (default: system default)",
    )
    parser.add_argument(
        "-r", "--sample-rate",
        type=int,
        default=48000,
        help="Sample rate in Hz (default: 48000)",
    )
    parser.add_argument(
        "-b", "--blocksize",
        type=int,
        default=1024,
        choices=BLOCK_SIZES,
        help=f"Block size in samples (default: 1024, options: {BLOCK_SIZES})",
    )
    parser.add_argument(
        "-c", "--channels",
        type=int,
        default=4,
        help="Number of channels to monitor (default: 4)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio devices and exit",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.list_devices:
        print("Available audio input devices:")
        print("-" * 60)
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                print(f"  [{idx}] {dev['name']}")
                print(f"      Inputs: {dev['max_input_channels']}, Default SR: {dev['default_samplerate']}")
        sys.exit(0)

    # Run curses application
    try:
        curses.wrapper(lambda stdscr: main(stdscr, args))
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
