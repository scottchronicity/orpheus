#!/usr/bin/env python3
"""
Manual test script to send sample bird and crow detection data to the dashboard via MQTT.
This simulates the full detection pipeline with proper event lineage tracking:
    Audio Motion → Bird Detection → Crow Analysis

Each event references its source event to create a traceable chain.

Usage:
    python3 scripts/test_bird_crow_detections.py
"""

import time
from datetime import datetime, timezone
from orpheus_common.mqtt import MQTTClient


def create_audio_motion_event(channel_id: str = "1", event_id: str = None) -> dict:
    """Create a sample audio motion detection event.

    Args:
        channel_id: Audio channel ID (1-4)
        event_id: Optional event ID (auto-generated if not provided)

    Returns:
        Audio motion event dict
    """
    if event_id is None:
        event_id = f"evt_audio_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_ch{channel_id}"

    return {
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "channel_id": channel_id,
        "duration_seconds": 5.2,
        "peak_energy_db": -22.5,
        "clip_path": f"/data/orpheus/audio/audio_motion/{channel_id}/20251205T143022.flac",
    }


def create_bird_detection_event(
    channel_id: str = "1", event_id: str = None, source_event_id: str = None
) -> dict:
    """Create a sample bird detection event.

    Args:
        channel_id: Audio channel ID (1-4)
        event_id: Optional event ID (auto-generated if not provided)
        source_event_id: Event ID of the audio motion event that triggered this

    Returns:
        Bird detection event dict with source_event_id for traceability
    """
    if event_id is None:
        event_id = f"evt_bird_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_ch{channel_id}"

    return {
        "event_id": event_id,
        "source_event_id": source_event_id,  # Links back to audio event
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "channel_id": channel_id,
        "detections": [
            {
                "species_code": "amecro",
                "species_common": "American Crow",
                "confidence": 0.87,
                "start_time": 0.5,
                "end_time": 3.2,
            },
            {
                "species_code": "blujay",
                "species_common": "Blue Jay",
                "confidence": 0.65,
                "start_time": 4.0,
                "end_time": 6.5,
            },
        ],
        "audio_clip_path": f"/data/orpheus/audio/audio_motion/{channel_id}/20251205T143022.flac",
    }


def create_crow_analysis_event(
    channel_id: str = "1", event_id: str = None, source_event_id: str = None
) -> dict:
    """Create a sample crow analysis event with nested detection object.

    Args:
        channel_id: Audio channel ID (1-4)
        event_id: Optional event ID (auto-generated if not provided)
        source_event_id: Event ID of the bird detection event that triggered this

    Returns:
        Crow analysis event dict with nested detection and source_event_id
    """
    if event_id is None:
        event_id = f"evt_crow_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_ch{channel_id}"

    return {
        "event_id": event_id,
        "source_event_id": source_event_id,  # Links back to bird detection event
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "channel_id": channel_id,
        "detection": {
            "is_crow": True,
            "species": "crow",
            "call_type": "alert",  # Dominant behavior
            "quality_score": 0.95,
            "attributes": {
                "age": "adult",
                "alert": 0.95,
                "begging": 0.01,
                "soft_song": 0.03,
                "rattle": 0.78,
                "mob": 0.05,
            },
        },
        "audio_clip_path": f"/data/orpheus/audio/audio_motion/{channel_id}/20251205T143022.flac",
        "model_version": "crow-tools-v1",
    }


def main():
    """Send sample detection data to MQTT, simulating the full pipeline with event lineage."""
    # Connect to MQTT broker
    client = MQTTClient(
        broker_host="localhost",
        broker_port=1883,
        client_id="test-dashboard-detections",
    )

    try:
        client.connect()
        print("=" * 70)
        print("🔊 ORPHEUS DETECTION PIPELINE TEST")
        print("=" * 70)
        print("\nSimulating full pipeline with event lineage:")
        print("  Audio Motion → Bird Detection → Crow Analysis")
        print("\nEach event references its source to create a traceable chain.")
        print("=" * 70)

        # Track event IDs for lineage
        audio_events = {}
        bird_events = {}

        # STEP 1: Send audio motion events (triggers bird detection)
        print("\n[STEP 1/3] 🎤 AUDIO MOTION DETECTION")
        print("-" * 70)
        for channel_id in ["1", "2", "3", "4"]:
            audio_event = create_audio_motion_event(channel_id)
            audio_events[channel_id] = audio_event["event_id"]
            client.publish("orpheus/audio/motion/events", audio_event, qos=1)
            print(f"  ✓ Channel {channel_id}: {audio_event['event_id']}")
            print(f"    Duration: {audio_event['duration_seconds']}s, "
                  f"Peak: {audio_event['peak_energy_db']} dB")
            time.sleep(0.2)

        time.sleep(0.5)  # Brief pause to simulate processing time

        # STEP 2: Send bird detection events (bird agent analyzes audio)
        print("\n[STEP 2/3] 🐦 BIRD SPECIES IDENTIFICATION")
        print("-" * 70)
        for channel_id in ["1", "2", "3", "4"]:
            bird_event = create_bird_detection_event(
                channel_id, source_event_id=audio_events[channel_id]
            )
            bird_events[channel_id] = bird_event["event_id"]
            client.publish("orpheus/detection/bird/events", bird_event, qos=1)
            print(f"  ✓ Channel {channel_id}: {bird_event['event_id']}")
            print(f"    Source: {bird_event['source_event_id']}")
            species = [d["species_common"] for d in bird_event["detections"]]
            print(f"    Species: {', '.join(species)}")
            time.sleep(0.2)

        time.sleep(0.5)  # Brief pause to simulate processing time

        # STEP 3: Send crow analysis events (crow agent analyzes crows from bird detections)
        print("\n[STEP 3/3] 🐦‍⬛ CROW BEHAVIORAL ANALYSIS")
        print("-" * 70)
        for channel_id in ["1", "3"]:  # Only channels with crow detections
            crow_event = create_crow_analysis_event(
                channel_id, source_event_id=bird_events[channel_id]
            )
            client.publish("orpheus/detection/crow/events", crow_event, qos=1)
            print(f"  ✓ Channel {channel_id}: {crow_event['event_id']}")
            print(f"    Source: {crow_event['source_event_id']}")
            detection = crow_event["detection"]
            print(f"    Call Type: {detection['call_type']}")
            print(f"    Quality: {detection['quality_score']:.2f}")
            print(f"    Age: {detection['attributes']['age']}")
            # Show top 3 behaviors
            behaviors = {
                k: v
                for k, v in detection["attributes"].items()
                if k in ["alert", "begging", "soft_song", "rattle", "mob"]
            }
            top_behaviors = sorted(behaviors.items(), key=lambda x: x[1], reverse=True)[
                :3
            ]
            print(f"    Top Behaviors: {', '.join([f'{k}={v:.2f}' for k, v in top_behaviors])}")
            time.sleep(0.2)

        print("\n" + "=" * 70)
        print("✅ TEST COMPLETED SUCCESSFULLY")
        print("=" * 70)
        print("\n📊 Summary:")
        print(f"   - {len(audio_events)} audio motion events")
        print(f"   - {len(bird_events)} bird detection events (American Crow + Blue Jay)")
        print("   - 2 crow analysis events (channels 1, 3)")
        print("\n🔗 Event Lineage:")
        print("   Audio → Bird → Crow (linked via source_event_id)")
        print("\n🌐 View Results:")
        print("   http://localhost:8080")
        print("   - Check 'Bird Detections' panel")
        print("   - Check 'Crow Analysis' panel")
        print("   - Look for 'Source Event' or 'Triggered By' columns")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        client.disconnect()
        print("\n👋 Disconnected from MQTT broker")


if __name__ == "__main__":
    main()
