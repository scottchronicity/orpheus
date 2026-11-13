"""Experiment isolation with hostile config/env and a synthetic live backplane."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
import yaml
from orpheus_common import DetectionDB, OrpheusConfig
from orpheus_common.detection import Detection
from orpheus_common.detection.database import open_connection

from orpheus_agent_audio_events.experiment import (
    ExperimentAgent,
    ExperimentBus,
    Journal,
    compare_results,
    main,
    prepare_experiment,
    run_experiment,
)
from orpheus_agent_audio_events.main import AudioEventsAgent
from orpheus_agent_audio_events.model import DeterministicFakeSED

from .test_gpu_backend import (
    worker_factory as worker_factory,  # noqa: PLC0414 — pytest fixture re-export
)


@pytest.fixture
def experiment_args(tmp_path, monkeypatch):
    """Everything that resembles credentials here is synthetic test data."""
    production = tmp_path / "production"
    production.mkdir()
    checkpoint = production / "panns.pth"
    checkpoint.write_bytes(b"existing checkpoint; must never be rewritten")
    worker = production / "gpu-venv/bin/python"
    worker.parent.mkdir(parents=True)
    worker.write_text("#!/bin/sh\nexit 1\n")
    worker.chmod(0o700)
    live = tmp_path / "station.yaml"
    live.write_text(
        yaml.safe_dump(
            {
                "event_bus": {
                    "backend": "nats",
                    "nats_url": "${EXPERIMENT_TEST_NATS}",
                    "presence_enabled": True,
                    "health_kv_enabled": True,
                    "health_on_bus": False,
                },
                "event_sourcing": {"shadow_publish_enabled": True},
                "config_service": {"enabled": True},
                "storage": {"base_path": str(production)},
                "audio_events": {
                    "backend": "inprocess",
                    "device": "cpu",
                    "input_topic": "orpheus/audio/motion/events",
                    "output_topic": "orpheus/detection/audio/events",
                    "clip_threshold": 0.35,
                },
            }
        )
    )
    monkeypatch.setenv("EXPERIMENT_TEST_NATS", "nats://synthetic-user:test-only@127.0.0.1:4222")
    monkeypatch.delenv("ORPHEUS_AGENT_INSTANCE_ID", raising=False)
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(production))
    return {
        "live_config": live,
        "scratch_root": tmp_path / "scratch",
        "checkpoint": checkpoint,
        "worker_python": worker,
        "instance_id": "gpu-test-laptop",
        "backend": "gpu_worker",
    }


@pytest.fixture
def plan(experiment_args):
    with patch.object(
        OrpheusConfig, "_read_kv_config", side_effect=AssertionError("no KV bootstrap")
    ):
        return prepare_experiment(**experiment_args)


def read_journal(root, kind):
    return [
        json.loads(line)["payload"] for line in (root / f"{kind}.jsonl").read_text().splitlines()
    ]


def test_hostile_env_cannot_redirect_experiment(experiment_args, monkeypatch):
    for key, value in {
        "ORPHEUS_AUDIO_EVENTS__BACKEND": "inprocess",
        "ORPHEUS_AUDIO_EVENTS__OUTPUT_TOPIC": "orpheus/detection/audio/events",
        "ORPHEUS_AUDIO_EVENTS__MODEL_PATH": "/wrong/model.pth",
        "ORPHEUS_STORAGE__BASE_PATH": str(experiment_args["checkpoint"].parent),
        "ORPHEUS_EVENT_BUS__PRESENCE_ENABLED": "true",
        "ORPHEUS_EVENT_BUS__HEALTH_KV_ENABLED": "true",
        "ORPHEUS_EVENT_SOURCING__SHADOW_PUBLISH_ENABLED": "true",
        "ORPHEUS_CONFIG_SERVICE__ENABLED": "true",
        "ORPHEUS_CONFIG_PATH": "/wrong/config.yaml",
        "ORPHEUS_EVENT_BUS__NATS_URL": "nats://synthetic-user:test-only@127.0.0.1:4333",
    }.items():
        monkeypatch.setenv(key, value)
    with patch.object(OrpheusConfig, "_read_kv_config", side_effect=AssertionError("no KV")):
        selected = prepare_experiment(**experiment_args)
    agent = ExperimentAgent(selected)
    try:
        assert agent.config.backend == "gpu_worker"
        assert agent.config.output_topic == selected.output_topic
        assert agent.config.model_path == str(selected.checkpoint)
        assert agent.config.clip_threshold == 0.35
        assert agent.detection_db.db_path == selected.db_path
        assert agent.identity.instance_id == "gpu-test-laptop"
        assert agent.orpheus_config.storage.base_path == str(selected.root)
        assert agent.orpheus_config.event_bus.nats_url.endswith(":4333")
        assert not agent.orpheus_config.event_bus.presence_enabled
        assert not agent.orpheus_config.event_bus.health_kv_enabled
        assert not agent.orpheus_config.event_sourcing.shadow_publish_enabled
        assert not agent.orpheus_config.config_service.enabled
        assert "test-only" not in (selected.root / "run.json").read_text()
        assert "synthetic-user" not in (selected.root / "run.json").read_text()
    finally:
        agent._executor.shutdown(wait=True)


def test_live_dotenv_settings_are_resolved_before_isolation(experiment_args, monkeypatch):
    env = experiment_args["live_config"].with_suffix(".env")
    env.write_text(
        "ORPHEUS_EVENT_BUS__NATS_URL=nats://127.0.0.1:4555\n"
        "ORPHEUS_DATA_ROOT=/wrong/data/root\n"
        "ORPHEUS_AUDIO_EVENTS__OUTPUT_TOPIC=orpheus/detection/audio/events\n"
        "ORPHEUS_AGENT_INSTANCE_ID=production-cpu\n"
    )
    monkeypatch.setenv("ORPHEUS_DOTENV_PATH", str(env))
    monkeypatch.delenv("ORPHEUS_DATA_ROOT")
    selected = prepare_experiment(**experiment_args)
    assert selected.config.event_bus.nats_url == "nats://127.0.0.1:4555"
    assert os.environ["ORPHEUS_DATA_ROOT"] == str(selected.root)
    assert os.environ["ORPHEUS_AGENT_INSTANCE_ID"] == selected.instance_id


@pytest.mark.parametrize(
    "change",
    [
        {"backend": "auto"},
        {"backend": "inprocess"},
        {"instance_id": "audio-events"},
        {"instance_id": "gpu-test-bad.id"},
        {"instance_id": "gpu-test-bad/*"},
    ],
)
def test_unsafe_launch_refused_before_scratch_creation(experiment_args, change):
    with pytest.raises(ValueError, match=r"backend|instance"):
        prepare_experiment(**dict(experiment_args, **change))
    assert not experiment_args["scratch_root"].exists()


def test_existing_directory_or_symlink_refused(experiment_args):
    experiment_args["scratch_root"].symlink_to(
        experiment_args["checkpoint"].parent, target_is_directory=True
    )
    before = experiment_args["checkpoint"].read_bytes()
    with pytest.raises(FileExistsError):
        prepare_experiment(**experiment_args)
    assert experiment_args["checkpoint"].read_bytes() == before


def test_inherited_instance_cannot_collide(experiment_args, monkeypatch):
    monkeypatch.setenv("ORPHEUS_AGENT_INSTANCE_ID", experiment_args["instance_id"])
    with pytest.raises(ValueError, match="differ"):
        prepare_experiment(**experiment_args)


def test_custom_live_topics_and_stricter_memory_policy_preserved(experiment_args, monkeypatch):
    monkeypatch.setenv("ORPHEUS_AUDIO_EVENTS__INPUT_TOPIC", "station/audio/motion/events")
    monkeypatch.setenv("ORPHEUS_AUDIO_EVENTS__OUTPUT_TOPIC", "station/detection/audio/events")
    monkeypatch.setenv("ORPHEUS_AUDIO_EVENTS__GPU_WORKER__START_MEMORY_MIB", "10000")
    selected = prepare_experiment(**experiment_args)
    assert selected.input_topic == "station/audio/motion/events"
    assert selected.cpu_topic == "station/detection/audio/events"
    assert selected.config._raw["audio_events"]["gpu_worker"]["start_memory_mib"] == 10000


@pytest.mark.parametrize("flag", ["--backend", "--instance-id"])
def test_cli_requires_explicit_backend_and_instance(experiment_args, monkeypatch, flag):
    argv = ["experiment", "run"]
    for key, value in experiment_args.items():
        option = "--" + key.replace("_", "-")
        if option != flag:
            argv.extend([option, str(value)])
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit):
        main()
    assert not experiment_args["scratch_root"].exists()


def test_run_cli_prepares_isolation_before_actor_launch(experiment_args, monkeypatch):
    argv = ["experiment", "run"]
    for key, value in experiment_args.items():
        argv.extend(["--" + key.replace("_", "-"), str(value)])
    monkeypatch.setattr("sys.argv", argv)
    with patch(
        "orpheus_agent_audio_events.experiment.run_experiment", new_callable=AsyncMock
    ) as run:
        main()
    assert run.call_args.args[0].config._raw["audio_events"]["backend"] == "gpu_worker"


@pytest.mark.parametrize(
    "topic",
    [
        "orpheus/detection/audio/events",
        "orpheus.detection.audio.events",
        "orpheus/domain/detection/audio/events",
        "orpheus/entities/animal",
        "orpheus/system/audio-events/health",
    ],
)
def test_transport_refuses_production_publishes(plan, topic):
    underlying = MagicMock()
    bus = ExperimentBus(underlying, plan, Journal(plan.root))
    with pytest.raises(ValueError, match="cannot publish"):
        bus.publish(topic, {})
    underlying.publish.assert_not_called()


def test_transport_cannot_write_kv_or_streams_or_retain(plan):
    raw = MagicMock()
    bus = ExperimentBus(raw, plan, Journal(plan.root))
    with pytest.raises(ValueError, match="retain"):
        bus.publish(plan.output_topic, {}, retain=True)
    for action in (
        lambda: bus.kv_put("orpheus_health", "audio-events", {}),
        lambda: bus.kv_delete("orpheus_presence", "production-cpu"),
        lambda: bus.stream_ensure("orpheus_domain", ["anything"]),
        lambda: bus.stream_publish("orpheus/domain/detection/audio/events", {}),
    ):
        with pytest.raises(NotImplementedError):
            action()
    assert not raw.mock_calls


async def test_db_and_worker_caches_remain_scratch_after_late_overrides(plan, monkeypatch):
    production = plan.checkpoint.parent
    production_db = production / "production.db"
    production_db.write_bytes(b"production database sentinel")
    before = plan.checkpoint.read_bytes()
    agent = ExperimentAgent(plan)
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(production))
    monkeypatch.setenv("ORPHEUS_AUDIO_EVENTS__OUTPUT_TOPIC", "orpheus/detection/audio/events")
    try:
        with patch("orpheus_agent_audio_events.worker_model.WorkerClient") as client:
            await agent.on_setup()
            command, env, options = client.call_args.args[:3]
            assert str(plan.checkpoint) in command
            assert command[0] == str(plan.worker_python)
            assert options.start_memory_mib == 8704
            assert options.floor_memory_mib == 3800
            for name in (
                "HOME",
                "MPLCONFIGDIR",
                "XDG_CACHE_HOME",
                "NUMBA_CACHE_DIR",
                "TMPDIR",
                "CUDA_CACHE_PATH",
            ):
                assert Path(env[name]).is_relative_to(plan.root)
            assert agent.detection_db.db_path == plan.db_path
            assert production_db.read_bytes() == b"production database sentinel"
            assert plan.checkpoint.read_bytes() == before
            # Runtime drift is denied before publishing or saving, even with a raw bus.
            agent.bus = MagicMock()
            agent.config.output_topic = "orpheus/detection/audio/events"
            with pytest.raises(ValueError, match="isolation changed"):
                agent._emit_detection(None, None, None, 0)
            agent.config.output_topic = plan.output_topic
            agent.detection_db.db_path = production_db
            with pytest.raises(ValueError, match="isolation changed"):
                agent._emit_detection(None, None, None, 0)
            assert production_db.read_bytes() == b"production database sentinel"
    finally:
        await agent.on_stopping()


async def test_side_effect_flags_cannot_enable_production_writes(plan):
    agent = ExperimentAgent(plan)
    raw = MagicMock()
    agent.bus = raw
    plan.config.event_bus.presence_enabled = True
    plan.config.event_bus.health_kv_enabled = True
    plan.config.event_sourcing.shadow_publish_enabled = True
    try:
        assert agent._make_presence() is None
        assert agent._make_operational_health() is None
        await agent.on_started()
        agent._heartbeat_payload()
        assert agent._shadow_publish is False
        assert not raw.mock_calls
    finally:
        await agent.on_stopping()


async def wait_until(predicate):
    end = time.monotonic() + 5
    while not predicate():
        if time.monotonic() >= end:
            pytest.fail("live experiment did not reach expected state")
        await asyncio.sleep(0.01)


class LocalBackplane:
    """Broadcast to all matching live subscribers; no queue groups or broker I/O."""

    def __init__(self):
        self.clients, self.published, self.callbacks = [], [], []

    def factory(self, _config, **kwargs):
        client = MagicMock()
        client.client_id = kwargs["client_id"]
        client.subscribe.side_effect = lambda topic, handler: self.callbacks.append(
            (client, topic, handler)
        )
        client.is_connected = False
        client.connect.side_effect = lambda: setattr(client, "is_connected", True)
        client.disconnect.side_effect = lambda: setattr(client, "is_connected", False)

        def publish(topic, payload, **_kwargs):
            self.published.append((client.client_id, topic, payload))
            for subscriber, pattern, handler in list(self.callbacks):
                if subscriber.is_connected and pattern == topic:
                    handler(topic, payload)

        client.publish.side_effect = publish
        self.clients.append(client)
        return client


def assert_matched_and_isolated(plan, production_db, source):
    gpu_rows, cpu_rows = read_journal(plan.root, "gpu"), read_journal(plan.root, "cpu")
    assert gpu_rows[0]["event_id"] != cpu_rows[0]["event_id"]
    assert gpu_rows[0]["source_event_id"] == cpu_rows[0]["source_event_id"] == source.event_id
    assert gpu_rows[0]["root_event_id"] == "root-acoustic-moment"
    assert compare_results(plan.root)["matched_labels"] == 1
    assert plan.db_path != production_db
    with open_connection(production_db, read_only=True) as conn:
        assert conn.execute("SELECT event_id FROM detections").fetchall() == [
            (cpu_rows[0]["event_id"],)
        ]
    with open_connection(plan.db_path, read_only=True) as conn:
        assert conn.execute("SELECT event_id FROM detections").fetchall() == [
            (gpu_rows[0]["event_id"],)
        ]


async def test_same_clip_reaches_cpu_and_gpu_with_separate_writes(
    plan,
    tiny_labels,
    worker_factory,
    monkeypatch,
):
    """Real fake-worker IPC, real SQLite and Actor lifecycle; no real broker/GPU."""
    # Resolve an independent CPU config before starting the test instance.
    cpu_config = OrpheusConfig.from_dict(
        {"audio_events": {"backend": "inprocess", "device": "cpu"}}
    )
    monkeypatch.delenv("ORPHEUS_AGENT_INSTANCE_ID")
    cpu_model = DeterministicFakeSED(num_classes=527, frame_duration_seconds=0.01)
    cpu_model.inject_event(0, 0, 1, 0.9)
    production_db = plan.checkpoint.parent / "cpu.db"
    cpu = AudioEventsAgent(
        orpheus_config=cpu_config,
        model=cpu_model,
        labels=tiny_labels,
        detection_db=DetectionDB(production_db),
    )
    monkeypatch.setenv("ORPHEUS_AGENT_INSTANCE_ID", plan.instance_id)
    gpu = ExperimentAgent(plan)
    gpu.model = worker_factory()
    gpu.labels = tiny_labels
    monkeypatch.setattr("orpheus_inference.resources.mem_available_mib", lambda: 10000)
    backplane = LocalBackplane()
    path = plan.checkpoint.parent / "live-clip.wav"
    sf.write(path, np.zeros(32000, dtype=np.float32), 32000)
    source = Detection(
        detection_type="audio.motion",
        timestamp=datetime.now(timezone.utc),
        root_event_id="root-acoustic-moment",
        audio_clip_path=str(path),
        metadata={"duration_seconds": 1},
    )
    tasks = []
    with patch("orpheus_common.actor.base.create_event_bus", side_effect=backplane.factory):
        try:
            tasks = [asyncio.create_task(cpu.start()), asyncio.create_task(gpu.start())]
            await wait_until(
                lambda: (
                    len(backplane.clients) == 2 and all(c.is_connected for c in backplane.clients)
                )
            )
            assert cpu.identity.instance_id is None
            assert gpu.identity.instance_id == plan.instance_id
            assert {topic for _, topic, _ in backplane.callbacks} == {
                plan.input_topic,
                plan.cpu_topic,
            }
            for _client, topic, callback in list(backplane.callbacks):
                if topic == plan.input_topic:
                    callback(topic, source.model_dump(mode="json"))
            await wait_until(lambda: cpu.detections_emitted == 1 and gpu.detections_emitted == 1)
            assert [
                event[1] for event in backplane.published if event[0] == gpu.identity.client_id
            ].count(plan.output_topic) == 1
            assert all(
                topic in {plan.output_topic, plan.health_topic}
                for identity, topic, _ in backplane.published
                if identity == gpu.identity.client_id
            )
            assert all(
                "experiment" not in topic
                for identity, topic, _ in backplane.published
                if identity == cpu.identity.client_id
            )
            assert_matched_and_isolated(plan, production_db, source)
            assert (
                read_journal(plan.root, "health")[0]["experiment_instance_id"] == plan.instance_id
            )
            # Stop only the experiment; a later clip still reaches the CPU instance.
            gpu.stop_event.set()
            await tasks[1]
            source.event_id = "second-live-clip"
            for client, topic, callback in list(backplane.callbacks):
                if client.is_connected and topic == plan.input_topic:
                    callback(topic, source.model_dump(mode="json"))
            await wait_until(lambda: cpu.detections_emitted == 2)
            assert gpu.detections_emitted == 1
            assert cpu.bus.is_connected
        finally:
            for agent in (cpu, gpu):
                if agent.stop_event is not None:
                    agent.stop_event.set()
            await asyncio.gather(*tasks)
            await gpu.on_stopping()
    assert gpu.model.health()["state"] == "stopped"


def test_expiry_uses_clip_end_and_comparison_uses_source_ids(plan):
    agent = ExperimentAgent(plan)
    try:
        source = Detection(
            detection_type="audio.motion",
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=35),
            metadata={"duration_seconds": 35},
        )
        assert agent._clip_deadline(source) > time.monotonic()
        source.timestamp -= timedelta(seconds=10)
        assert agent._clip_deadline(source) < time.monotonic()
        journal = Journal(plan.root)
        payload = {
            "source_event_id": "clip-1",
            "taxonomy": {"namespace": "audioset", "id": "/m/test"},
            "confidence": 0.8,
            "event_id": "cpu-id",
            "intervals": [],
        }
        journal.write("cpu", payload)
        journal.write("gpu", dict(payload, event_id="gpu-id", confidence=0.800001))
        journal.write("cpu", dict(payload, source_event_id="cpu-only-clip"))
        report = compare_results(plan.root)
        assert report["matched_labels"] == 1
        assert report["matched"][0]["cpu_event_id"] != report["matched"][0]["gpu_event_id"]
        assert report["max_confidence_abs_diff"] == pytest.approx(1e-6)
        assert report["cpu_only"] == [("cpu-only-clip", "/m/test")]
    finally:
        agent._executor.shutdown(wait=True)


async def test_startup_failure_always_stops_worker(plan):
    agent = MagicMock()

    async def fail():
        raise RuntimeError("synthetic connect failure")

    agent.start.side_effect = fail

    async def stop():
        pass

    agent.on_stopping.side_effect = stop
    with (
        patch("orpheus_agent_audio_events.experiment.ExperimentAgent", return_value=agent),
        pytest.raises(RuntimeError, match="connect failure"),
    ):
        await run_experiment(plan)
    agent.on_stopping.assert_called_once()
    agent.bus.disconnect.assert_called_once()


def test_compare_cli_is_read_only_without_launch(plan, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["experiment", "compare", "--scratch-root", str(plan.root)])
    with patch("orpheus_agent_audio_events.experiment.ExperimentAgent") as constructor:
        main()
    constructor.assert_not_called()
    assert json.loads(capsys.readouterr().out)["matched_labels"] == 0
