"""Opt-in backend tests with real pipe IPC and a synthetic model process."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
from orpheus_common import DetectionDB, OrpheusConfig
from orpheus_common.detection import Detection
from orpheus_common.events import SpatiotemporalContext
from orpheus_inference.client import WorkerClient, WorkerOptions
from orpheus_inference.protocol import ProtocolError

from orpheus_agent_audio_events.config import AudioEventsConfig, GPUWorkerConfig
from orpheus_agent_audio_events.main import AudioEventsAgent
from orpheus_agent_audio_events.model import DeterministicFakeSED
from orpheus_agent_audio_events.worker_model import WorkerSEDModel, auto_worker_available

ROOT = Path(__file__).resolve().parents[3]


def wait_ready(model: WorkerSEDModel) -> None:
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if model.health()["ready"]:
            return
        time.sleep(0.01)
    pytest.fail(str(model.health()))


@pytest.fixture
def worker_factory():
    models = []

    def create(mode="normal"):
        model = WorkerSEDModel.__new__(WorkerSEDModel)
        model.config = GPUWorkerConfig(python=sys.executable)
        fake = ROOT / "platform/orpheus-inference/tests/fake_worker.py"
        model.client = WorkerClient(
            [sys.executable, "-u", str(fake), "--mode", mode],
            dict(os.environ, PYTHONPATH=str(ROOT / "platform/orpheus-inference/src")),
            WorkerOptions(
                start_memory_mib=0,
                floor_memory_mib=0,
                startup_timeout=2,
                request_timeout=1,
                restart_backoff=0.1,
                max_starts=1,
            ),
        )
        models.append(model)
        model.client.start()
        wait_ready(model)
        return model

    yield create
    for model in models:
        model.close()


@pytest.fixture
def gpu_agent(worker_factory, tiny_labels, monkeypatch):
    config = AudioEventsConfig.from_orpheus_config(
        MagicMock(_raw={"audio_events": {"backend": "gpu_worker"}})
    )
    with (
        patch("orpheus_agent_audio_events.main.load_config", return_value=config),
        patch(
            "orpheus_agent_audio_events.main.OrpheusConfig.get_instance", return_value=MagicMock()
        ),
    ):
        agent = AudioEventsAgent(
            model=worker_factory(), labels=tiny_labels, detection_db=MagicMock()
        )
    agent.bus = MagicMock()
    monkeypatch.setattr("orpheus_inference.resources.mem_available_mib", lambda: 10000)
    yield agent
    asyncio.run(agent.on_stopping())


@pytest.fixture
def clip_source(tmp_path):
    path = tmp_path / "clip.wav"
    sf.write(path, np.zeros(32000, dtype=np.float32), 32000)
    return path, Detection(
        timestamp=datetime.now(timezone.utc),
        detection_type="audio.motion",
        audio_clip_path=str(path),
        root_event_id="original-root",
        metadata={"duration_seconds": 1.0},
    )


def test_gpu_pipeline_preserves_lineage_and_persistence(gpu_agent, clip_source):
    path, source = clip_source
    gpu_agent._submit_processing(path, source)
    gpu_agent.wait_inflight(timeout=5)
    assert gpu_agent.detections_emitted == 1
    detection = gpu_agent.detection_db.save.call_args.args[0]
    payload = gpu_agent.bus.publish.call_args.args[1]
    assert detection.event_id == payload["event_id"]
    assert payload["source_event_id"] == source.event_id
    assert payload["root_event_id"] == "original-root"
    assert payload["taxonomy"]["namespace"] == "audioset"
    assert payload["intervals"]
    assert gpu_agent.health_payload("heartbeat")["model_loaded"] is True


def test_gpu_queue_preserves_every_received_clip_under_overload(
    gpu_agent, clip_source, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    processed = []
    processed_lock = threading.Lock()

    def block(_path, _source, *, deadline):
        assert deadline is None
        entered.set()
        release.wait(timeout=5)
        with processed_lock:
            processed.append(_source.event_id)

    monkeypatch.setattr(gpu_agent, "_process_audio_file", block)
    path, source = clip_source
    producer = threading.Thread(
        target=lambda: [gpu_agent._submit_processing(path, source) for _ in range(20)],
        daemon=True,
    )
    try:
        gpu_agent._submit_processing(path, source)
        assert entered.wait(timeout=2)
        producer.start()
        end = time.monotonic() + 2
        while time.monotonic() < end and len(gpu_agent._inflight) < 3:
            time.sleep(0.01)
        assert len(gpu_agent._inflight) == 3
        assert producer.is_alive()  # callback is backpressured at configured capacity
        assert gpu_agent.clips_rejected["overload"] == 0
    finally:
        release.set()
        if producer.ident is not None:
            producer.join(timeout=10)
        gpu_agent.wait_inflight(timeout=5)
    assert not producer.is_alive()
    assert len(processed) == 21


@pytest.mark.parametrize("ttl", [None, 3.0])
def test_clip_age_cutoff_applies_only_when_configured(gpu_agent, clip_source, ttl):
    gpu_agent.config.gpu_worker = replace(gpu_agent.config.gpu_worker, clip_ttl_seconds=ttl)
    path, source = clip_source
    source.timestamp -= timedelta(seconds=20)
    gpu_agent._submit_processing(path, source)
    gpu_agent.wait_inflight(timeout=5)
    if ttl is None:
        detection = gpu_agent.detection_db.save.call_args.args[0]
        assert detection.source_event_id == source.event_id
        assert gpu_agent.clips_rejected["expired"] == 0
    else:
        gpu_agent.detection_db.save.assert_not_called()
        assert gpu_agent.clips_rejected["expired"] == 1


def test_queue_expiry_before_decode(gpu_agent, clip_source):
    path, source = clip_source
    with patch.object(gpu_agent, "_load_and_preprocess") as decode:
        gpu_agent._process_worker_clip(path, source, time.monotonic() - 1, object())
        decode.assert_not_called()
    assert gpu_agent.clips_rejected["expired"] == 1


def test_header_duration_limit_before_decode(gpu_agent, clip_source):
    path, source = clip_source
    with (
        patch("orpheus_agent_audio_events.main.sf.info", return_value=MagicMock(duration=121)),
        patch.object(gpu_agent, "_load_and_preprocess") as decode,
    ):
        gpu_agent._process_worker_clip(path, source, None, object())
        decode.assert_not_called()
    assert gpu_agent.clips_rejected["too_long"] == 1


def test_queued_clip_waits_for_worker_recovery(gpu_agent, clip_source, monkeypatch):
    ready = threading.Event()
    monkeypatch.setattr(
        gpu_agent.model,
        "health",
        lambda: {"ready": ready.is_set(), "state": "recovering", "failures": 0},
    )
    decoded = threading.Event()
    monkeypatch.setattr(gpu_agent, "_process_audio_file", lambda *_args, **_kwargs: decoded.set())
    gpu_agent._submit_processing(*clip_source)
    time.sleep(0.2)
    assert not decoded.is_set()
    ready.set()
    assert decoded.wait(timeout=2)
    gpu_agent.wait_inflight(timeout=2)
    assert gpu_agent.clips_rejected["unavailable"] == 0


def test_decode_expiry_does_not_emit_or_infer(gpu_agent, clip_source):
    path, source = clip_source
    with (
        patch.object(gpu_agent, "_load_and_preprocess", return_value=np.zeros(320)),
        patch.object(gpu_agent.model, "predict_before") as infer,
    ):
        gpu_agent._process_audio_file(path, source, deadline=time.monotonic() - 1)
        infer.assert_not_called()
    gpu_agent.bus.publish.assert_not_called()


@pytest.mark.parametrize("mode", ["badshape", "nan"])
def test_corrupt_output_rejected_and_worker_reaped(worker_factory, mode):
    model = worker_factory(mode)
    with pytest.raises(ProtocolError):
        model.predict(np.zeros(320, dtype=np.float32))
    assert model.health()["ready"] is False
    assert model.health()["pid"] is None


@pytest.mark.parametrize("audio", [np.zeros((2, 2)), np.array([]), np.array([np.nan])])
def test_invalid_input_never_sent(worker_factory, audio):
    model = worker_factory()
    with pytest.raises(ValueError, match="invalid worker audio"):
        model.predict(audio)
    assert model.health()["ready"]


async def test_gpu_setup_skips_parent_torch_probe(gpu_agent):
    model = gpu_agent.model
    gpu_agent.model = None
    with (
        patch("orpheus_agent_audio_events.main.WorkerSEDModel", return_value=model),
        patch("orpheus_agent_audio_events.main.select_torch_device") as probe,
    ):
        await gpu_agent.on_setup()
        probe.assert_not_called()


def test_constructor_stages_only_child_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("PYTHONPATH", "agent-only-python39-source")
    original_home = os.environ.get("HOME")
    with patch("orpheus_agent_audio_events.worker_model.WorkerClient") as client:
        model = WorkerSEDModel(tmp_path / "checkpoint", GPUWorkerConfig(python=sys.executable))
        command, env = client.call_args.args[:2]
        assert "-I" in command
        assert "PYTHONPATH" not in env
        assert env["OPENBLAS_NUM_THREADS"] == "1"
        assert Path(env["HOME"]).is_relative_to(tmp_path)
        assert (Path(env["HOME"]) / "panns_data/class_labels_indices.csv").exists()
        assert os.environ.get("HOME") == original_home
        model.close()


def test_missing_worker_python_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        WorkerSEDModel(tmp_path / "checkpoint", GPUWorkerConfig(python=str(tmp_path / "missing")))


def test_nonexecutable_worker_python_fails_before_supervision(tmp_path):
    worker = tmp_path / "python"
    worker.write_text("not an executable")
    with pytest.raises(FileNotFoundError, match="not executable"):
        WorkerSEDModel(tmp_path / "checkpoint", GPUWorkerConfig(python=str(worker)))


@pytest.mark.parametrize(
    ("system", "machine", "memory"),
    [("Darwin", "arm64", 10000), ("Linux", "x86_64", 10000), ("Linux", "aarch64", None)],
)
def test_auto_does_not_discover_unimplemented_runtime_combinations(
    monkeypatch, system, machine, memory,
):
    monkeypatch.setattr("orpheus_agent_audio_events.worker_model.platform.system", lambda: system)
    monkeypatch.setattr("orpheus_agent_audio_events.worker_model.platform.machine", lambda: machine)
    monkeypatch.setattr("orpheus_agent_audio_events.worker_model.mem_available_mib", lambda: memory)
    assert not auto_worker_available(GPUWorkerConfig(python=sys.executable))


def test_auto_selection_checks_platform_install_and_host_memory(monkeypatch):
    monkeypatch.setattr("orpheus_agent_audio_events.worker_model.platform.system", lambda: "Linux")
    monkeypatch.setattr(
        "orpheus_agent_audio_events.worker_model.platform.machine", lambda: "aarch64"
    )
    monkeypatch.setattr("orpheus_agent_audio_events.worker_model.mem_available_mib", lambda: 10000)
    assert auto_worker_available(GPUWorkerConfig(python=sys.executable))
    monkeypatch.setattr("orpheus_agent_audio_events.worker_model.mem_available_mib", lambda: 5000)
    assert not auto_worker_available(GPUWorkerConfig(python=sys.executable))


async def test_auto_backend_preserves_inprocess_device_discovery(gpu_agent):
    gpu_agent.config.backend = "auto"
    gpu_agent._worker_backend = False
    gpu_agent.model = None
    with (
        patch("orpheus_agent_audio_events.main.select_torch_device", return_value="cuda") as select,
        patch("orpheus_agent_audio_events.main.build_model", return_value=DeterministicFakeSED()),
    ):
        await gpu_agent.on_setup()
        select.assert_called_once_with("auto")
        assert gpu_agent._resolved_device == "cuda"


@pytest.mark.parametrize(
    "settings",
    [
        {"clip_ttl_seconds": 0},
        {"clip_ttl_seconds": float("nan")},
        {"max_pending_clips": -1},
        {"floor_memory_mib": 0},
        {"start_memory_mib": 3800},
        {"start_memory_mib": 3799},
        {"max_clip_seconds": 400},
        {"max_clip_seconds": 1e308},
        {"max_pending_clips": 1.5},
        {"shutdown_drain_timeout_seconds": 0},
        {"shutdown_drain_timeout_seconds": float("nan")},
    ],
)
def test_invalid_gpu_configuration(settings):
    with pytest.raises(ValueError, match="GPU"):
        GPUWorkerConfig(**settings)


def test_backend_is_opt_in_and_paths_follow_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
    config = AudioEventsConfig.from_orpheus_config(MagicMock(_raw={}))
    assert config.backend == "inprocess"
    assert config.device == "auto"
    assert config.gpu_worker.python == str(tmp_path / "venvs/panns-gpu/bin/python")
    with pytest.raises(ValueError, match="backend"):
        AudioEventsConfig.from_orpheus_config(
            MagicMock(_raw={"audio_events": {"backend": "unknown"}})
        )


@pytest.mark.parametrize("backend", ["inprocess", "auto", "gpu_worker"])
@pytest.mark.parametrize("device", ["mps", "cuda:1", "typo"])
def test_unsupported_panns_devices_fail_before_model_loading(backend, device):
    with pytest.raises(ValueError, match="device"):
        AudioEventsConfig.from_orpheus_config(
            MagicMock(_raw={"audio_events": {"backend": backend, "device": device}})
        )


def test_explicit_cpu_cannot_select_required_cuda_worker():
    with pytest.raises(ValueError, match="requires device"):
        AudioEventsConfig.from_orpheus_config(
            MagicMock(_raw={"audio_events": {"backend": "gpu_worker", "device": "cpu"}})
        )


@pytest.mark.parametrize("settings", [{"device": "cpu"}, {"model_variant": "fake"}])
def test_auto_respects_device_and_model_choice(settings, tiny_labels):
    resolved = OrpheusConfig.from_dict({"audio_events": {"backend": "auto", **settings}})
    with patch("orpheus_agent_audio_events.main.auto_worker_available", return_value=True):
        agent = AudioEventsAgent(
            orpheus_config=resolved, model=DeterministicFakeSED(), labels=tiny_labels,
            detection_db=MagicMock(),
        )
    try:
        assert agent._worker_backend is False
        assert agent._executor._max_workers == agent.config.max_concurrent_clips
    finally:
        asyncio.run(agent.on_stopping())


async def test_auto_preserves_explicit_cuda_requirement(gpu_agent):
    gpu_agent.config.backend = "auto"
    gpu_agent.config.device = "cuda"
    gpu_agent._worker_backend = False
    gpu_agent.model = None
    with patch(
        "orpheus_agent_audio_events.main.select_torch_device",
        side_effect=RuntimeError("CUDA is not available"),
    ) as select, pytest.raises(RuntimeError, match="CUDA"):
        await gpu_agent.on_setup()
    select.assert_called_once_with("cuda")


@pytest.mark.parametrize("age_days", [0, 30])
def test_cpu_and_pipe_worker_publish_and_store_equivalent_events(
    gpu_agent, clip_source, tiny_labels, tmp_path, age_days,
):
    """Identical model scores must preserve the domain contract across executors.

    Numerical CUDA parity is hardware evidence, not a claim of this CPU-only test.
    """
    _path, source = clip_source
    source.timestamp -= timedelta(days=age_days)
    source.channel = 19
    source.context = SpatiotemporalContext(timestamp=source.timestamp, sensor_id="mic19")
    cpu_model = DeterministicFakeSED(frame_duration_seconds=0.01)

    def reference_scores(audio):
        scores = np.zeros((audio.size // 320 + 1, 527), dtype=np.float32)
        scores[:, 0] = 0.9
        return scores

    cpu_model.predict = reference_scores
    cpu = AudioEventsAgent(
        orpheus_config=OrpheusConfig.from_dict({"audio_events": {"device": "cpu"}}),
        model=cpu_model, labels=tiny_labels,
        detection_db=DetectionDB(tmp_path / "cpu.db"),
    )
    cpu.bus = MagicMock()
    gpu_agent.detection_db = DetectionDB(tmp_path / "gpu.db")
    outputs = []
    try:
        for agent in (cpu, gpu_agent):
            topic, callback = agent.subscriptions()[0]
            callback(topic, source.model_dump(mode="json"))
            agent.wait_inflight(timeout=5)
            assert agent.bus.publish.call_count == 1
            output_topic, payload = agent.bus.publish.call_args.args
            assert output_topic == "orpheus/detection/audio/events"
            stored = agent.detection_db.get_by_event_id(payload["event_id"])
            assert stored is not None
            assert stored.source_event_id == source.event_id
            assert stored.root_event_id == source.root_event_id
            assert stored.intervals == Detection.model_validate(payload).intervals
            assert stored.taxonomy == Detection.model_validate(payload).taxonomy
            assert payload["detection_type"] == "audio.classified"
            assert payload["channel"] == 19
            assert payload["context"] == source.context.model_dump(mode="json")
            assert agent.clips_rejected["expired"] == 0
            payload.pop("event_id")
            payload.pop("timestamp")
            payload.pop("event_timestamp")
            payload["metadata"].pop("inference_time_ms")
            outputs.append(payload)
        assert outputs[0] == outputs[1]
    finally:
        asyncio.run(cpu.on_stopping())


def test_config_precedence_reaches_parent_and_child(tmp_path, monkeypatch):
    """Use the real YAML -> optional KV -> env -> agent -> IPC path."""
    config_path = tmp_path / "orpheus.yaml"
    config_path.write_text(
        "mqtt:\n  broker_host: localhost\nconfig_service:\n  enabled: true\naudio_events:\n"
        "  backend: gpu_worker\n  gpu_worker:\n"
        f"    python: {sys.executable}\n"
        "    start_memory_mib: 2100\n    floor_memory_mib: 1100\n"
    )
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("ORPHEUS_AUDIO_EVENTS__GPU_WORKER__START_MEMORY_MIB", "2300")
    monkeypatch.setenv("ORPHEUS_AUDIO_EVENTS__GPU_WORKER__MAX_PENDING_CLIPS", "11")
    monkeypatch.setenv("ORPHEUS_AUDIO_EVENTS__GPU_WORKER__MAX_CLIP_SECONDS", "150")
    kv = {"audio_events": {"gpu_worker": {
        "start_memory_mib": 2200, "floor_memory_mib": 1200,
        "request_timeout_seconds": 17, "startup_timeout_seconds": 71,
        "restart_backoff_seconds": 4, "max_starts": 5, "restart_window_seconds": 91,
    }}}
    with patch.object(OrpheusConfig, "_read_kv_config", return_value=kv):
        config = AudioEventsConfig.from_orpheus_config(OrpheusConfig(config_path=config_path))
    with patch("orpheus_agent_audio_events.worker_model.WorkerClient") as client:
        model = WorkerSEDModel(tmp_path / "checkpoint", config.gpu_worker)
        command, _, options = client.call_args.args
        assert command[command.index("--floor-mib") + 1] == "1200"
        assert float(command[command.index("--max-seconds") + 1]) == 150
        assert (options.start_memory_mib, options.floor_memory_mib) == (2300, 1200)
        assert (options.startup_timeout, options.request_timeout) == (71, 17)
        assert (options.restart_backoff, options.max_starts, options.restart_window) == (4, 5, 91)
        assert config.gpu_worker.max_pending_clips == 11
        model.close()


@pytest.mark.parametrize("mode", ["crash", "hang"])
def test_ipc_failure_retries_accepted_old_clip_after_worker_recovery(
    gpu_agent, clip_source, mode
):
    path, source = clip_source
    source.timestamp -= timedelta(days=30)
    model = gpu_agent.model
    model.client.close()
    model.client.command[model.client.command.index("--mode") + 1] = mode
    # New supervisor for the failure probe; change the next launch to normal
    # once the first IPC failure is observed to exercise retry of the same job.
    model.client = WorkerClient(
        model.client.command, model.client.env,
        replace(model.client.options, max_starts=3, restart_backoff=0.1),
    )
    model.client.start()
    wait_ready(model)
    gpu_agent._submit_processing(path, source)
    end = time.monotonic() + 5
    while time.monotonic() < end and model.health()["failures"] == 0:
        time.sleep(0.01)
    assert model.health()["failures"] == 1
    model.client.command[-1] = "normal"
    gpu_agent.wait_inflight(timeout=10)
    assert gpu_agent.bus.publish.call_count == 1
    assert gpu_agent.detection_db.save.call_count == 1
    assert gpu_agent.errors_count == 0
    assert gpu_agent.clips_rejected["expired"] == 0
    assert gpu_agent.model is model
    wait_ready(model)
    assert model.health()["starts"] == 2
    assert gpu_agent.detection_db.save.call_args.args[0].source_event_id == source.event_id


@pytest.mark.parametrize("mode", ["nan", "badshape"])
def test_clip_that_fails_on_a_fresh_worker_is_accounted_and_later_clips_proceed(
    gpu_agent, clip_source, mode
):
    """A result the worker can never produce for this clip must not stall the
    queue: after it fails on a worker restarted for it, the clip is counted under
    worker_error and an error, nothing is published for it, and the next clip is
    classified."""
    path, source = clip_source
    model = gpu_agent.model
    model.client.close()
    model.client.command[model.client.command.index("--mode") + 1] = mode
    model.client = WorkerClient(
        model.client.command, model.client.env,
        replace(model.client.options, max_starts=5, restart_backoff=0.1),
    )
    model.client.start()
    wait_ready(model)
    gpu_agent._submit_processing(path, source)
    gpu_agent.wait_inflight(timeout=20)
    assert gpu_agent.clips_rejected["worker_error"] == 1
    assert gpu_agent.errors_count == 1
    assert model.health()["failures"] == 2
    assert gpu_agent.bus.publish.call_count == 0
    assert gpu_agent.detection_db.save.call_count == 0

    model.client.command[-1] = "normal"
    wait_ready(model)
    later = source.model_copy(update={"event_id": source.event_id + "-later"})
    gpu_agent._submit_processing(path, later)
    gpu_agent.wait_inflight(timeout=20)
    assert gpu_agent.detection_db.save.call_count == 1
    assert gpu_agent.detection_db.save.call_args.args[0].source_event_id == later.event_id
    assert gpu_agent.clips_rejected["worker_error"] == 1


def test_health_reports_the_effective_worker_floor(gpu_agent):
    payload = gpu_agent._build_health_payload()
    assert payload["backend"] == "gpu_worker"
    assert payload["floor_memory_mib"] == gpu_agent.config.gpu_worker.floor_memory_mib == 3800


@pytest.mark.parametrize("source_count", [1, 8, 20])
def test_configured_queue_can_admit_bursts_beyond_four_sources(
    worker_factory, tiny_labels, clip_source, source_count,
):
    cfg = OrpheusConfig.from_dict({"audio_events": {
        "backend": "gpu_worker",
        "gpu_worker": {"max_pending_clips": min(source_count - 1, 1)},
    }})
    agent = AudioEventsAgent(
        orpheus_config=cfg, model=worker_factory(), labels=tiny_labels, detection_db=MagicMock(),
    )
    entered, release = threading.Event(), threading.Event()
    original = agent._process_audio_file

    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        original(*args, **kwargs)

    agent._process_audio_file = gated
    agent.bus = MagicMock()
    path, source = clip_source
    submitted = []
    producer = threading.Thread(
        target=lambda: [
            (agent._submit_processing(path, source.model_copy(update={"channel": channel + 1})),
             submitted.append(channel))
            for channel in range(source_count)
        ],
        daemon=True,
    )
    with patch("orpheus_inference.resources.mem_available_mib", return_value=10000):
        try:
            producer.start()
            assert entered.wait(timeout=2)
            capacity = 1 + min(source_count - 1, 1)
            end = time.monotonic() + 2
            while time.monotonic() < end and len(agent._inflight) < min(source_count, capacity):
                time.sleep(0.01)
            assert len(agent._inflight) == min(source_count, capacity)
            if source_count > capacity:
                assert producer.is_alive()
            assert agent.clips_rejected["overload"] == 0
            release.set()
            producer.join(timeout=10)
            assert not producer.is_alive()
            agent.wait_inflight(timeout=10)
            assert len(submitted) == source_count
            assert agent.detections_emitted == source_count
        finally:
            release.set()
            asyncio.run(agent.on_stopping())


async def test_shutdown_drains_running_and_queued_clips_before_closing_worker(
    gpu_agent, clip_source
):
    entered, release = threading.Event(), threading.Event()
    original = gpu_agent._process_audio_file

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        original(*args, **kwargs)

    gpu_agent._process_audio_file = blocked
    gpu_agent._submit_processing(*clip_source)
    assert entered.wait(timeout=2)
    for _ in range(2):
        gpu_agent._submit_processing(*clip_source)
    queued = [future for future in gpu_agent._inflight if not future.running()]
    assert len(queued) == 2
    stopping = asyncio.create_task(gpu_agent.on_stopping())
    try:
        await asyncio.sleep(0.1)
        assert not stopping.done()
        assert gpu_agent.model.health()["ready"]
    finally:
        release.set()
        await stopping
    assert all(future.done() and not future.cancelled() for future in queued)
    assert gpu_agent.detections_emitted == 3
    assert gpu_agent.clips_rejected["shutdown"] == 0
    assert not gpu_agent._inflight
    assert gpu_agent.bus.publish.call_count == 3


async def test_shutdown_bounds_wait_for_permanently_unavailable_worker(gpu_agent, clip_source):
    gpu_agent.config.gpu_worker = replace(
        gpu_agent.config.gpu_worker, shutdown_drain_timeout_seconds=0.1
    )
    gpu_agent.model.health = lambda: {"ready": False, "failures": 0, "state": "circuit_open"}
    gpu_agent._submit_processing(*clip_source)
    end = time.monotonic() + 2
    while time.monotonic() < end and not gpu_agent._inflight:
        await asyncio.sleep(0.01)
    assert gpu_agent._inflight

    await asyncio.wait_for(gpu_agent.on_stopping(), timeout=2)

    assert not gpu_agent._inflight
    assert gpu_agent.clips_rejected["shutdown"] == 1
    gpu_agent.bus.publish.assert_not_called()
    gpu_agent.detection_db.save.assert_not_called()
