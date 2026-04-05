#!/usr/bin/env python3
"""CLI tool to play sounds via the Orpheus audio playback system.

This tool sends MQTT playback requests to the orpheus-agent-audio-playback service.

Usage:
    orpheus_play_sound <sound_name> [options]

Examples:
    orpheus_play_sound test_tone_1
    orpheus_play_sound test_beep --repeat 3 --pause 1.0
    orpheus_play_sound crow_call --broker mqtt.local --port 1883
"""

import argparse
import sys
import time
from typing import Any, Dict, Optional

from orpheus_common.config import OrpheusConfig
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.mqtt import MQTTClient

logger = get_logger(__name__)


def play_sound(
    sound_name: str,
    repeat_count: int = 1,
    pause_between: float = 0.0,
    broker_host: Optional[str] = None,
    broker_port: Optional[int] = None,
    timeout: float = 5.0,
    wait_for_completion: bool = False,
) -> bool:
    """Play a sound via MQTT.

    Args:
        sound_name: Name of the sound to play
        repeat_count: Number of times to play (default: 1)
        pause_between: Seconds to pause between repeats (default: 0.0)
        broker_host: MQTT broker host (default: from config)
        broker_port: MQTT broker port (default: from config)
        timeout: Seconds to wait for response (default: 5.0)
        wait_for_completion: Wait for playback to complete (default: False)

    Returns:
        True if playback started successfully, False otherwise
    """
    # Load configuration
    config = OrpheusConfig.get_instance()

    # Use provided broker settings or defaults from config
    if not broker_host:
        broker_host = config.mqtt.broker_host
    if not broker_port:
        broker_port = config.mqtt.broker_port

    logger.info(f"Connecting to MQTT broker at {broker_host}:{broker_port}")

    # Create MQTT client
    client = MQTTClient(
        broker_host=broker_host,
        broker_port=broker_port,
        client_id="orpheus-cli-play-sound",
    )

    # Track response
    response_received = {"value": False, "success": False, "error": None}

    def handle_response(topic: str, payload: Dict[str, Any]) -> None:
        """Handle playback response."""
        response_received["value"] = True
        if payload.get("status") == "success":
            response_received["success"] = True
            logger.info(f"Playback started: {sound_name}")
        else:
            response_received["error"] = payload.get("error", "Unknown error")
            logger.error(f"Playback failed: {response_received['error']}")

    # Subscribe to response topic
    client.subscribe("orpheus/audio/playback/response", handle_response)

    # Connect to broker
    try:
        client.connect()
    except Exception as e:
        logger.error(f"Failed to connect to MQTT broker: {e}")
        return False

    # Publish playback request
    request = {
        "sound_name": sound_name,
        "repeat_count": repeat_count,
        "pause_between": pause_between,
    }

    logger.info(
        f"Playing sound: {sound_name}, repeat={repeat_count}, pause={pause_between}s"
    )

    client.publish("orpheus/audio/playback/request", request, qos=1)

    # Wait for response
    start_time = time.time()
    while not response_received["value"] and (time.time() - start_time) < timeout:
        time.sleep(0.1)

    # Disconnect
    client.disconnect()

    # Check result
    if not response_received["value"]:
        logger.error("Timeout waiting for response from audio playback agent")
        return False

    if not response_received["success"]:
        logger.error(f"Playback failed: {response_received['error']}")
        return False

    # If wait_for_completion, estimate playback duration and wait
    if wait_for_completion:
        # Rough estimate: 1 second per repeat + pause_between
        estimated_duration = repeat_count * (1.0 + pause_between)
        logger.info(f"Waiting for playback to complete (~{estimated_duration:.1f}s)")
        time.sleep(estimated_duration)

    return True


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Optional argument list

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Play audio sounds via the Orpheus audio playback system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s test_tone_1
  %(prog)s test_beep --repeat 3 --pause 1.0
  %(prog)s crow_call --broker mqtt.local --port 1883
  %(prog)s test_tone_1 --wait --log-level DEBUG

For more information: https://github.com/scottchronicity/orpheus
        """,
    )

    parser.add_argument(
        "sound_name",
        help="Name of the sound to play (e.g., test_tone_1, test_beep)",
    )

    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="Number of times to play the sound (default: 1)",
    )

    parser.add_argument(
        "--pause",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="Seconds to pause between repeats (default: 0.0)",
    )

    parser.add_argument(
        "--broker",
        type=str,
        help="MQTT broker host (default: from config)",
    )

    parser.add_argument(
        "--port",
        type=int,
        help="MQTT broker port (default: from config)",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="Seconds to wait for response (default: 5.0)",
    )

    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for playback to complete before exiting",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log level (default: INFO)",
    )

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Main entrypoint.

    Args:
        argv: Optional argument list

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    args = parse_args(argv)

    # Setup logging
    setup_logging("orpheus-cli-play-sound", level=args.log_level, use_json=False)

    # Validate arguments
    if args.repeat < 1:
        logger.error("--repeat must be >= 1")
        return 1

    if args.pause < 0:
        logger.error("--pause must be >= 0")
        return 1

    # Play sound
    try:
        success = play_sound(
            sound_name=args.sound_name,
            repeat_count=args.repeat,
            pause_between=args.pause,
            broker_host=args.broker,
            broker_port=args.port,
            timeout=args.timeout,
            wait_for_completion=args.wait,
        )

        if success:
            logger.info("✓ Playback command sent successfully")
            return 0
        else:
            logger.error("✗ Playback command failed")
            return 1

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
