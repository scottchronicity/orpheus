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
from orpheus_common.detection import Detection
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


def test_bounded_admission_precedes_decode(gpu_agent, clip_source, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def block(_path, _source, *, deadline):
        assert deadline is None
        entered.set()
        release.wait(timeout=5)

    monkeypatch.setattr(gpu_agent, "_process_audio_file", block)
    path, source = clip_source
    try:
        gpu_agent._submit_processing(path, source)
        assert entered.wait(timeout=2)
        for _ in range(20):
            gpu_agent._submit_processing(path, source)
        assert len(gpu_agent._inflight) == 3
        assert gpu_agent.health_payload("heartbeat")["pending_clips"] == 2
        assert gpu_agent.clips_rejected["overload"] == 18
    finally:
        release.set()
        gpu_agent.wait_inflight(timeout=5)


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


def test_memory_guard_before_decode(gpu_agent, clip_source, monkeypatch):
    monkeypatch.setattr("orpheus_inference.resources.mem_available_mib", lambda: 3000)
    with patch.object(gpu_agent, "_load_and_preprocess") as decode:
        gpu_agent._submit_processing(*clip_source)
        decode.assert_not_called()
    assert gpu_agent.clips_rejected["memory"] == 1


def test_unready_worker_does_not_queue_during_recovery(gpu_agent, clip_source):
    gpu_agent.model.client.close()
    gpu_agent._submit_processing(*clip_source)
    assert not gpu_agent._inflight
    health = gpu_agent.health_payload("heartbeat")
    assert health["model_loaded"] is False
    assert health["worker"]["state"] == "stopped"
    assert health["clips_rejected"]["unavailable"] == 1


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


def test_auto_selection_checks_platform_install_and_host_memory(monkeypatch):
    monkeypatch.setattr("orpheus_agent_audio_events.worker_model.platform.system", lambda: "Linux")
    monkeypatch.setattr(
        "orpheus_agent_audio_events.worker_model.platform.machine", lambda: "aarch64"
    )
    monkeypatch.setattr("orpheus_agent_audio_events.worker_model.mem_available_mib", lambda: 10000)
    assert auto_worker_available(GPUWorkerConfig(python=sys.executable))
    monkeypatch.setattr("orpheus_agent_audio_events.worker_model.mem_available_mib", lambda: 5000)
    assert not auto_worker_available(GPUWorkerConfig(python=sys.executable))


async def test_auto_cpu_fallback_uses_cpu(gpu_agent):
    gpu_agent.config.backend = "auto"
    gpu_agent._worker_backend = False
    gpu_agent.model = None
    with (
        patch("orpheus_agent_audio_events.main.select_torch_device", return_value="cpu") as select,
        patch("orpheus_agent_audio_events.main.build_model", return_value=DeterministicFakeSED()),
    ):
        await gpu_agent.on_setup()
        select.assert_called_once_with("cpu")


@pytest.mark.parametrize(
    "settings",
    [
        {"clip_ttl_seconds": 0},
        {"clip_ttl_seconds": float("nan")},
        {"max_pending_clips": -1},
        {"floor_memory_mib": 0},
        {"start_memory_mib": 3800},
        {"start_memory_mib": 3799},
        {"max_clip_seconds": 121},
        {"max_pending_clips": 1.5},
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
