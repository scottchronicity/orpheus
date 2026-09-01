"""Pump fake Orpheus detection events through MQTT to exercise the correlator.

Simulates:
  - audio.motion fires
  - bird-detection enriches with American Crow + Common Raven
  - audio-events enriches with AudioSet Crow tag
  - crow-detection enriches with call-type analysis (no taxonomy)

All four observations share root_event_id and should cluster into ONE
Entity with all evidence rolled up.

Runs 5 such cycles spaced 8 seconds apart so the cluster window
(3s default) closes between cycles and we see 5 distinct Entities.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# Force the DetectionDB to write into our test data dir, matching the
# correlator's ORPHEUS_DATA_ROOT setting.
os.environ.setdefault("ORPHEUS_DATA_ROOT", "/tmp/orpheus-test-data")

from orpheus_common.detection import Detection, DetectionDB  # noqa: E402

BROKER = "localhost"
PORT = 1884

db = DetectionDB()
client = mqtt.Client(client_id="fake-pump", protocol=mqtt.MQTTv311)
client.connect(BROKER, PORT, 60)
client.loop_start()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def publish(topic: str, payload: dict) -> None:
    """Publish to MQTT AND persist to DB (mirrors what each agent does)."""
    client.publish(topic, json.dumps(payload), qos=1)
    # Persist so the chain endpoint + auto-discovery worker have data.
    try:
        det = Detection.from_dict(payload)
        db.save(det)
    except Exception as e:
        print(f"   (persist skipped: {e})")
    print(f"  → {topic}: detection_type={payload.get('detection_type')} "
          f"species_code={payload.get('species_code')} "
          f"root={payload.get('root_event_id')}")


def make_audio_motion(event_id: str) -> dict:
    return {
        "event_id": event_id,
        "event_timestamp": now(),
        "timestamp": now(),
        "detection_type": "audio.motion",
        "channel": 1,
        "audio_clip_path": f"/data/clips/{event_id}.flac",
        "metadata": {"duration_seconds": 10.0, "peak_energy_db": -25.0},
        "source_event_id": None,
        "root_event_id": event_id,  # audio.motion is its own root
        "intervals": [{"start_seconds": 0.0, "end_seconds": 10.0, "confidence": None}],
        "taxonomy": None,
    }


def make_bird_detection(am_id: str, species_code: str, species_common: str, scientific: str, conf: float) -> dict:
    det_id = f"{am_id}_{species_code}"
    return {
        "event_id": det_id,
        "event_timestamp": now(),
        "timestamp": now(),
        "detection_type": "species.detected",
        "channel": 1,
        "species_code": species_code,
        "species_common": species_common,
        "confidence": conf,
        "audio_clip_path": f"/data/clips/{am_id}.flac",
        "source_event_id": am_id,
        "root_event_id": am_id,
        "intervals": [
            {"start_seconds": 0.0, "end_seconds": 3.0, "confidence": conf * 0.85},
            {"start_seconds": 3.0, "end_seconds": 6.0, "confidence": conf},
        ],
        "taxonomy": {
            "namespace": "ioc",
            "id": scientific,
            "common_name": species_common,
        },
        "metadata": {"species_scientific": scientific, "is_corvid": True},
    }


def make_audio_classified(am_id: str) -> dict:
    return {
        "event_id": f"{am_id}_audioset_crow",
        "event_timestamp": now(),
        "timestamp": now(),
        "detection_type": "audio.classified",
        "channel": 1,
        "species_code": "audioset_/m/04s8yn",
        "species_common": "Crow",
        "confidence": 0.85,
        "audio_clip_path": f"/data/clips/{am_id}.flac",
        "source_event_id": am_id,
        "root_event_id": am_id,
        "intervals": [
            {"start_seconds": 0.5, "end_seconds": 2.8, "confidence": 0.85},
        ],
        "taxonomy": {
            "namespace": "audioset",
            "id": "/m/04s8yn",
            "common_name": "Crow",
        },
        "metadata": {"model": "panns_cnn14_sed"},
    }


def make_crow_analyzed(am_id: str, bird_event_id: str) -> dict:
    return {
        "event_id": f"crow_{bird_event_id}",
        "event_timestamp": now(),
        "timestamp": now(),
        "detection_type": "crow.analyzed",
        "channel": 1,
        "species_code": "crow",
        "species_common": "Crow",
        "confidence": 0.78,
        "audio_clip_path": f"/data/clips/{am_id}.flac",
        "source_event_id": bird_event_id,
        "root_event_id": am_id,  # 2-hop chain back to audio.motion
        "intervals": [
            {"start_seconds": 1.2, "end_seconds": 1.9, "confidence": 0.78},
        ],
        "taxonomy": None,  # crow-tools opts out — call-type analyzer
        "metadata": {"call_type": "alert", "age": "adult"},
    }


print("=== Pumping 5 crow events through the pipeline ===")
for i in range(5):
    am_id = f"am-test-{uuid.uuid4().hex[:8]}"
    print(f"\n[Event {i+1}/5] audio.motion = {am_id}")

    # Step 1: audio-motion fires. NB: correlator IGNORES audio.motion
    # (per PROCESSED_DETECTION_TYPES rules) — it's still useful to
    # publish for traceability.
    publish("orpheus/audio/motion/events", make_audio_motion(am_id))

    # Step 2: bird-detection emits 2 species in same clip (American Crow + Common Raven).
    bird_crow = make_bird_detection(
        am_id, "corvus", "American Crow", "Corvus brachyrhynchos", 0.92,
    )
    publish("orpheus/detection/bird/events", bird_crow)
    bird_raven = make_bird_detection(
        am_id, "corvus", "Common Raven", "Corvus corax", 0.71,
    )
    # Make the raven event_id unique (otherwise it collides with crow's slug-based id).
    bird_raven["event_id"] = f"{am_id}_corvus_raven"
    publish("orpheus/detection/bird/events", bird_raven)

    # Step 3: audio-events fires AudioSet Crow.
    publish("orpheus/detection/audio/events", make_audio_classified(am_id))

    # Step 4: crow-detection processes the bird event (using the American Crow id).
    publish("orpheus/detection/crow/events", make_crow_analyzed(am_id, bird_crow["event_id"]))

    # Wait long enough for the cluster window (3s) to close so the next
    # event becomes a separate cluster.
    print(f"   ⏱ sleeping 5s for cluster window to close…")
    time.sleep(5)

print("\n=== Pump complete. Sleeping 5s for final cluster to close. ===")
time.sleep(5)
client.loop_stop()
client.disconnect()
