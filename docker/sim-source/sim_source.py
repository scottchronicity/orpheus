"""Simulacrum sim-source — drive the collective under test without sensor hardware.

Emits detection events onto the messaging backplane so the cognitive pipeline
(correlator -> EntityEvents) runs end-to-end in containers, no ALSA/cameras
required. Two modes (SIM_MODE env var):

synthetic (default)
    Emits synthetic species.detected events. The detection shape mirrors the
    real correlator contract (the same one the BDD suite uses); species are
    GROUNDED (real species_code + IOC taxonomy from the BDD spec) — no invented
    taxonomy. Extend SPECIES from a real source, not by guessing. Each cycle
    emits a short BURST (same sensor + clip root, within the correlator's
    window) so detections cluster into one entity; it alternates sensors so you
    also see cross-sensor merging. Watch the correlator logs / the entities
    topic / the DB.

replay
    Replays the REAL audio clips mounted under $ORPHEUS_DATA_ROOT/clips
    (artifacts/audio-samples in compose) as audio.motion chain-root events —
    the exact shape the real audio-motion agent publishes, with a fresh
    event_id/root_event_id and now-timestamps, cycling one clip per INTERVAL.
    Deliberately NO species fields: the fleet-profile classifiers run the real
    models on the real clip and decide. SIM_BURST is ignored (every
    audio.motion is its own chain root; fan-out comes from the classifiers).
"""

from __future__ import annotations

import os
import signal
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from orpheus_common import Detection, OrpheusConfig, create_event_bus
from orpheus_common.events import SpatiotemporalContext

# Grounded (from tests/bdd/steps/cognitive_loop_steps.py): real species_code +
# IOC taxonomy. Do not invent additional species/taxonomy here.
SPECIES = {
    "American Crow": {
        "species_code": "corvus",
        "taxonomy": {"namespace": "ioc", "id": "Corvus brachyrhynchos"},
    },
}
SENSORS = ["mic-1", "mic-2"]
TOPIC = "orpheus/detection/bird/events"
# Replay mode publishes on the chain-ROOT topic the real audio-motion agent owns
# (a new consumer of an existing topic/shape — no payload change).
AUDIO_MOTION_TOPIC = "orpheus/audio/motion/events"
MODE = os.environ.get("SIM_MODE", "synthetic").strip().lower()
INTERVAL = float(os.environ.get("SIM_INTERVAL_SECONDS", "5"))
BURST = int(os.environ.get("SIM_BURST", "2"))
# Where the real clips are mounted in-container ($ORPHEUS_DATA_ROOT, never a
# hardcoded home dir). Compose mounts artifacts/audio-samples at the same path
# in the fleet classifiers, so a replayed audio_clip_path resolves there too.
CLIPS_DIR = Path(
    os.environ.get(
        "SIM_CLIPS_DIR",
        os.path.join(os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus"), "clips"),
    )
)
CLIP_SUFFIXES = {".ogg", ".flac", ".wav", ".mp3"}


def _detection(species: str, sensor_id: str, root: str, ts: datetime) -> dict:
    spec = SPECIES[species]
    return {
        "event_id": "det-" + uuid.uuid4().hex[:8],
        "timestamp": ts.isoformat(),
        "detection_type": "species.detected",
        "species_code": spec["species_code"],
        "species_common": species,
        "taxonomy": spec["taxonomy"],
        # sensor_id rides in the spatiotemporal context (where the correlator reads it).
        "context": {"sensor_id": sensor_id, "lat": 47.6, "lon": -122.3},
        # Same root across the burst = one clip = one cluster.
        "root_event_id": root,
        "source_event_id": root,
        "confidence": 0.9,
    }


def _audio_motion(clip: Path, sensor_idx: int) -> dict:
    """A REAL-shaped audio.motion chain-root event pointing at a mounted clip.

    Mirrors the real audio-motion agent's publish (channel_processor.py):
    ``Detection(detection_type="audio.motion")`` with ``audio_clip_path``,
    sensor context, fresh event_id/now-timestamps, and root_event_id set to its
    own event_id (audio.motion is the chain root — cross-classifier-identity
    §1.1). Deliberately NO species fields and NO intervals/energy metadata (we
    didn't measure any) — the classifiers decide what's in the clip.
    """
    det = Detection(
        timestamp=datetime.now(timezone.utc),
        detection_type="audio.motion",
        channel=sensor_idx + 1,
        context=SpatiotemporalContext(
            lat=47.6, lon=-122.3, sensor_id=SENSORS[sensor_idx]
        ),
        audio_clip_path=str(clip),
        metadata={"channel_id": str(sensor_idx + 1), "sim_mode": "replay"},
    )
    det.root_event_id = det.event_id
    return det.model_dump(mode="json")


def _wait(stop: dict) -> None:
    # sleep in small steps so SIGTERM is responsive
    waited = 0.0
    while waited < INTERVAL and not stop["stop"]:
        time.sleep(0.25)
        waited += 0.25


def _run_synthetic(bus, stop: dict) -> None:
    print(f"[sim-source] connected; emitting {BURST}x bursts every {INTERVAL}s on {TOPIC}", flush=True)
    cycle = 0
    species = next(iter(SPECIES))
    while not stop["stop"]:
        sensor = SENSORS[cycle % len(SENSORS)]
        root = f"root-{sensor}-{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc)
        for _ in range(BURST):
            det = _detection(species, sensor, root, now)
            bus.publish(TOPIC, det)
        print(f"[sim-source] cycle {cycle}: emitted {BURST}x {species} on {sensor}", flush=True)
        cycle += 1
        _wait(stop)


def _run_replay(bus, stop: dict) -> None:
    clips = sorted(p for p in CLIPS_DIR.glob("*") if p.suffix.lower() in CLIP_SUFFIXES)
    if not clips:
        # Fail loudly — restart:unless-stopped makes the crash-loop visible in
        # `docker compose ps` instead of silently emitting nothing.
        raise SystemExit(
            f"[sim-source] replay: no audio clips under {CLIPS_DIR} — "
            "is artifacts/audio-samples mounted there?"
        )
    print(
        f"[sim-source] connected; replaying {len(clips)} real clips from {CLIPS_DIR} "
        f"every {INTERVAL}s on {AUDIO_MOTION_TOPIC}",
        flush=True,
    )
    cycle = 0
    while not stop["stop"]:
        clip = clips[cycle % len(clips)]
        event = _audio_motion(clip, cycle % len(SENSORS))
        bus.publish(AUDIO_MOTION_TOPIC, event)
        print(
            f"[sim-source] cycle {cycle}: replayed {clip.name} as audio.motion "
            f"{event['event_id']} on {event['context']['sensor_id']}",
            flush=True,
        )
        cycle += 1
        _wait(stop)


def main() -> None:
    config = OrpheusConfig.get_instance()
    bus = create_event_bus(config, client_id="orpheus-sim-source")
    bus.connect()

    stop = {"stop": False}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.__setitem__("stop", True))

    try:
        if MODE == "replay":
            _run_replay(bus, stop)
        else:
            _run_synthetic(bus, stop)
    finally:
        bus.disconnect()
        print("[sim-source] stopped", flush=True)


if __name__ == "__main__":
    main()
