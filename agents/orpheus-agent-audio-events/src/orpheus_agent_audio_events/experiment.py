"""Foreground GPU experiment alongside the unchanged live CPU audio-events agent.

Connection settings and classification thresholds are resolved from the live
config in memory. Isolation is applied AFTER env/dotenv normalization and
enforced again at the bus and SQLite boundaries. No credentials are serialized.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import re
import sys
import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from orpheus_common import DetectionDB, OrpheusConfig
from orpheus_common.actor.identity import agent_identity
from orpheus_common.event_bus import EventBus, EventCallback
from orpheus_common.logging import get_logger, setup_logging

from .config import AudioEventsConfig
from .main import AudioEventsAgent
from .worker_model import WorkerSEDModel

logger = get_logger(__name__)


@dataclass(frozen=True)
class Experiment:
    """Fixed per-run destinations, independent of subsequent env/config overrides."""

    root: Path
    instance_id: str
    config: OrpheusConfig
    input_topic: str
    cpu_topic: str
    output_topic: str
    checkpoint: Path
    worker_python: Path

    @property
    def db_path(self) -> Path:
        return self.root / "detections" / "orpheus.db"

    @property
    def health_topic(self) -> str:
        return agent_identity("audio-events", self.instance_id).health_topic


def concrete_topic(topic: str) -> str:
    """Reject wildcards/dotted aliases before passing a topic to the NATS bridge."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)+", topic):
        raise ValueError("live topics must be concrete slash-form topics")
    return topic


def prepare_experiment(
    *,
    live_config: Path,
    scratch_root: Path,
    checkpoint: Path,
    worker_python: Path,
    instance_id: str,
    backend: str,
) -> Experiment:
    """Resolve live settings, then create a fresh, private scratch run.

    Disabling the config-service bootstrap before loading avoids a KV merge
    reintroducing production settings. Normal env/dotenv connection overrides
    still resolve through OrpheusConfig. No derived YAML containing secrets is saved.
    """
    if backend != "gpu_worker":
        raise ValueError("experiment requires explicit backend gpu_worker")
    if not re.fullmatch(r"gpu-test-[a-z0-9][a-z0-9_-]{0,47}", instance_id):
        raise ValueError(
            "instance ID must start gpu-test- and contain lowercase letters/digits/_/-"
        )
    if instance_id == os.environ.get("ORPHEUS_AGENT_INSTANCE_ID"):
        raise ValueError("experiment instance ID must differ from the inherited live instance")
    source = live_config.expanduser().resolve(strict=True)
    with source.open() as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise TypeError("live config must contain a mapping")
    raw["config_service"] = {"enabled": False}
    os.environ["ORPHEUS_CONFIG_PATH"] = str(source)
    live = OrpheusConfig.from_dict(raw, source=str(source))
    if instance_id == os.environ.get("ORPHEUS_AGENT_INSTANCE_ID"):
        raise ValueError("experiment instance ID must differ from the live dotenv instance")
    if live.event_bus.backend != "nats":
        raise ValueError("live-traffic experiment requires the live NATS backend")
    audio = AudioEventsConfig.from_orpheus_config(live)
    input_topic, cpu_topic = concrete_topic(audio.input_topic), concrete_topic(audio.output_topic)
    if input_topic == cpu_topic or cpu_topic.startswith("orpheus/experiments/"):
        raise ValueError("live input and CPU output must be distinct production topics")
    root = scratch_root.expanduser().resolve()
    checkpoint = checkpoint.expanduser().resolve(strict=True)
    worker_python = worker_python.expanduser().absolute()
    if (
        not checkpoint.is_file()
        or not worker_python.is_file()
        or not os.access(worker_python, os.X_OK)
    ):
        raise ValueError("existing checkpoint and executable worker Python are required")
    if worker_python.resolve() == Path(sys.executable).resolve():
        raise ValueError("worker Python must use its separate Python 3.8 environment")
    # Exclusive mkdir rejects production roots, reused runs, symlinks and existing DBs.
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    output_topic = f"orpheus/experiments/panns-gpu/{instance_id}/detections"
    config = copy.deepcopy(live)
    config.event_bus = replace(
        live.event_bus, presence_enabled=False, health_kv_enabled=False, health_on_bus=True
    )
    config.event_sourcing = replace(live.event_sourcing, shadow_publish_enabled=False)
    config.config_service = replace(live.config_service, enabled=False)
    config.storage = replace(live.storage, base_path=str(root))
    worker = replace(audio.gpu_worker, python=str(worker_python))
    isolated = replace(
        audio,
        enabled=True,
        backend="gpu_worker",
        device="cuda",
        model_variant="cnn14_sed",
        model_path=str(checkpoint),
        output_topic=output_topic,
        gpu_worker=worker,
    )
    # Parent consumes this resolved in-memory config directly; no second env merge.
    config._raw.update(
        audio_events=asdict(isolated),
        event_bus=asdict(config.event_bus),
        event_sourcing=asdict(config.event_sourcing),
        config_service=asdict(config.config_service),
        storage=asdict(config.storage),
    )
    os.environ["ORPHEUS_DATA_ROOT"] = str(root)
    os.environ["ORPHEUS_AGENT_INSTANCE_ID"] = instance_id
    plan = Experiment(
        root, instance_id, config, input_topic, cpu_topic, output_topic, checkpoint, worker_python
    )
    # Safe provenance only: deliberately omit broker URL, env and full config.
    (root / "run.json").write_text(
        json.dumps(
            {
                "instance_id": instance_id,
                "input_topic": input_topic,
                "cpu_topic": cpu_topic,
                "output_topic": output_topic,
                "health_topic": plan.health_topic,
                "db_path": str(plan.db_path),
                "checkpoint": str(checkpoint),
                "worker_python": str(worker_python),
                "clip_ttl_seconds": worker.clip_ttl_seconds,
                "classification": {
                    k: asdict(isolated)[k]
                    for k in (
                        "clip_threshold",
                        "frame_threshold",
                        "bridge_ms",
                        "min_interval_ms",
                        "max_labels_per_clip",
                    )
                },
            },
            indent=2,
        )
        + "\n"
    )
    return plan


class Journal:
    """Small append-only scratch results; files are never opened outside this run."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def write(self, kind: str, payload: dict) -> None:
        """Record a result or heartbeat without saving connection configuration."""
        if kind not in {"cpu", "gpu", "health", "clips"}:
            raise ValueError("unknown experiment journal")
        entry = {"received_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        with self._lock, (self.root / f"{kind}.jsonl").open("a") as handle:
            handle.write(json.dumps(entry) + "\n")


class ExperimentBus(EventBus):
    """Allow only test detections/health and read-only live subscriptions.

    EventBus's optional KV/stream/request methods remain unsupported. In
    particular, retain=True cannot write the production last-value KV bucket.
    """

    def __init__(self, bus: EventBus, plan: Experiment, journal: Journal) -> None:
        self._bus, self.plan, self.journal = bus, plan, journal

    def publish(
        self, topic: str, payload: dict, qos: int | None = None, retain: bool = False
    ) -> None:
        if retain or topic not in {self.plan.output_topic, self.plan.health_topic}:
            raise ValueError("experiment cannot publish outside its test destinations or retain")
        self._bus.publish(topic, payload, qos=qos, retain=False)
        self.journal.write("gpu" if topic == self.plan.output_topic else "health", payload)

    def subscribe(self, topic_pattern: str, callback: EventCallback) -> None:
        if topic_pattern not in {self.plan.input_topic, self.plan.cpu_topic}:
            raise ValueError("experiment may only subscribe to live input and CPU results")
        self._bus.subscribe(topic_pattern, callback)

    def unsubscribe(self, topic_pattern: str) -> None:
        self._bus.unsubscribe(topic_pattern)

    def connect(self) -> None:
        self._bus.connect()

    def disconnect(self) -> None:
        self._bus.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._bus.is_connected


class ExperimentAgent(AudioEventsAgent):
    """Same inference/Actor lifecycle, with fixed scratch storage and bus capabilities."""

    def __init__(self, plan: Experiment) -> None:
        self.plan = plan
        self.journal = Journal(plan.root)
        self._experiment_bus: ExperimentBus | None = None
        super().__init__(orpheus_config=plan.config, detection_db=DetectionDB(plan.db_path))
        if self.identity.instance_id != plan.instance_id:
            raise ValueError("experiment identity differs from the selected instance")

    @property
    def bus(self) -> ExperimentBus | None:
        return self._experiment_bus

    @bus.setter
    def bus(self, value: EventBus | None) -> None:
        # Actor assigns its bus before subscribing/connecting/publishing health.
        self._experiment_bus = (
            ExperimentBus(value, self.plan, self.journal) if value is not None else None
        )

    def _assert_isolation(self) -> None:
        if (
            self.config.backend != "gpu_worker"
            or self.config.output_topic != self.plan.output_topic
            or self.config.input_topic != self.plan.input_topic
            or Path(self.config.model_path) != self.plan.checkpoint
            or Path(self.config.gpu_worker.python) != self.plan.worker_python
            or self.detection_db is None
            or self.detection_db.db_path.resolve() != self.plan.db_path
        ):
            raise ValueError("experiment isolation changed; refusing inference/publication/storage")

    async def on_setup(self) -> None:
        self._assert_isolation()
        # Reassert after all config/dotenv loading and before worker cache staging.
        os.environ["ORPHEUS_DATA_ROOT"] = str(self.plan.root)
        await super().on_setup()

    def _emit_detection(self, *args: Any, **kwargs: Any) -> None:
        self._assert_isolation()
        self._shadow_publish = False
        super()._emit_detection(*args, **kwargs)

    def _make_presence(self) -> None:
        return None

    def _make_operational_health(self) -> None:
        return None

    async def on_started(self) -> None:
        # Do not even ensure the production shadow stream, regardless of overrides.
        self._shadow_publish = False
        logger.info(
            "GPU experiment running",
            instance_id=self.plan.instance_id,
            output_topic=self.plan.output_topic,
            results=str(self.plan.root),
        )

    def subscriptions(self) -> list[tuple[str, Any]]:
        def input_clip(topic: str, payload: dict) -> None:
            ready = isinstance(self.model, WorkerSEDModel) and self.model.health()["ready"]
            self.journal.write("clips", dict(payload, experiment_worker_ready=ready))
            self._on_audio_motion_event(topic, payload)

        return [
            (self.plan.input_topic, input_clip),
            (self.plan.cpu_topic, lambda _topic, payload: self.journal.write("cpu", payload)),
        ]

    def health_payload(self, phase: str) -> dict[str, Any]:
        return dict(super().health_payload(phase), experiment_instance_id=self.plan.instance_id)


def compare_results(root: Path) -> dict[str, Any]:
    """Match observed CPU/GPU labels by source event ID and canonical AudioSet mid."""
    if not (root / "run.json").is_file():
        raise FileNotFoundError("experiment run.json missing; check --scratch-root")
    results = {}
    for side in ("cpu", "gpu"):
        rows = {}
        path = root / f"{side}.jsonl"
        if path.exists():
            with path.open() as handle:
                for line in handle:
                    if not line.endswith("\n"):
                        continue  # a concurrent append may not be complete yet
                    detection = json.loads(line)["payload"]
                    taxonomy = detection.get("taxonomy") or {}
                    if detection.get("source_event_id") and taxonomy.get("namespace") == "audioset":
                        rows[(detection["source_event_id"], taxonomy["id"])] = detection
        results[side] = rows
    cpu, gpu = results["cpu"], results["gpu"]
    matched = [
        {
            "source_event_id": key[0],
            "audioset_mid": key[1],
            "cpu_event_id": cpu[key]["event_id"],
            "gpu_event_id": gpu[key]["event_id"],
            "confidence_abs_diff": abs(cpu[key]["confidence"] - gpu[key]["confidence"]),
            "cpu_inference_time_ms": (cpu[key].get("metadata") or {}).get("inference_time_ms"),
            "gpu_inference_time_ms": (gpu[key].get("metadata") or {}).get("inference_time_ms"),
            "cpu_intervals": cpu[key].get("intervals", []),
            "gpu_intervals": gpu[key].get("intervals", []),
        }
        for key in sorted(cpu.keys() & gpu.keys())
    ]
    return {
        "matched_labels": len(matched),
        "matched": matched,
        "cpu_only": sorted(cpu.keys() - gpu.keys()),
        "gpu_only": sorted(gpu.keys() - cpu.keys()),
        "max_confidence_abs_diff": max(
            (row["confidence_abs_diff"] for row in matched), default=None
        ),
    }


async def run_experiment(plan: Experiment) -> None:
    """Use Actor's signal handlers; always stop the child if startup fails."""
    agent = ExperimentAgent(plan)
    try:
        await agent.start()
    finally:
        # Actor shuts down normally on Ctrl-C; this also handles connect/setup errors.
        await agent.on_stopping()
        if agent.bus is not None:
            agent.bus.disconnect()


def main() -> None:
    """Explicit run and read-only comparison commands; no service operations."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--backend", choices=["gpu_worker"], required=True)
    run.add_argument("--live-config", type=Path, required=True)
    run.add_argument("--scratch-root", type=Path, required=True)
    run.add_argument("--checkpoint", type=Path, required=True)
    run.add_argument("--worker-python", type=Path, required=True)
    run.add_argument("--instance-id", required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("--scratch-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "compare":
        print(json.dumps(compare_results(args.scratch_root), indent=2))
        return
    setup_logging("orpheus-panns-gpu-experiment", use_json=True)
    plan = prepare_experiment(**{k: v for k, v in vars(args).items() if k != "command"})
    asyncio.run(run_experiment(plan))


if __name__ == "__main__":
    main()
