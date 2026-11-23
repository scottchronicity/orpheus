"""GPU telemetry for /api/health, read from a fake Jetson sysfs tree."""

from pathlib import Path

import pytest

from orpheus_ui.gpu import (
    UtilizationSampler,
    gpu_info,
    inference_memory,
    read_temperature,
    read_utilization,
)

MIB = 1024 * 1024


@pytest.fixture
def jetson(tmp_path: Path) -> str:
    """sysfs as on jetson1: nvgpu load in tenths of a percent, a GPU-therm zone."""
    (tmp_path / "sys/devices/gpu.0").mkdir(parents=True)
    (tmp_path / "sys/devices/gpu.0/load").write_text("517\n")
    zones = [("CPU-therm", "61812"), ("GPU-therm", "59562"), ("tj-therm", "62093")]
    for i, (kind, temp) in enumerate(zones):
        zone = tmp_path / f"sys/class/thermal/thermal_zone{i}"
        zone.mkdir(parents=True)
        (zone / "type").write_text(kind + "\n")
        (zone / "temp").write_text(temp + "\n")
    return str(tmp_path)


WORKER = {
    "backend": "gpu_worker",
    "stale": False,
    "worker": {"state": "ready", "runtime": {"cuda_reserved_mib": 2006, "cuda_allocated_mib": 322}},
}


def test_reads_utilization_and_gpu_temperature(jetson):
    assert read_utilization(jetson) == 51.7
    assert read_temperature(jetson) == 59.6  # the GPU zone, not CPU or tj


def test_reports_shared_memory_and_the_workers_cuda_share(jetson):
    info = gpu_info(
        16 * 1024 * MIB, 7 * 1024 * MIB, WORKER, floor_mib=3800, utilization=7.2, root=jetson
    )
    assert info["available"] is True
    assert info["utilization_percent"] == 7.2
    assert info["utilization_window_seconds"] == 10
    mem = info["memory"]
    assert mem["shared"] is True
    assert mem["total_bytes"] == 16 * 1024 * MIB
    assert mem["available_bytes"] == 7 * 1024 * MIB
    assert mem["inference_reserved_bytes"] == 2006 * MIB
    assert mem["inference_allocated_bytes"] == 322 * MIB
    assert mem["inference_floor_bytes"] == 3800 * MIB


def test_host_without_a_gpu_reports_unavailable(tmp_path):
    assert gpu_info(1, 1, WORKER, floor_mib=3800, utilization=None, root=str(tmp_path)) == {
        "available": False
    }


@pytest.mark.parametrize(
    "health",
    [
        None,
        {**WORKER, "stale": True},  # an old heartbeat must not look current
        {**WORKER, "backend": "inprocess"},  # CPU inference holds no CUDA memory
        {"backend": "gpu_worker", "stale": False, "worker": {"state": "stopped"}},
    ],
)
def test_no_worker_figures_without_a_fresh_gpu_worker_heartbeat(health):
    assert inference_memory(health) == {
        "inference_reserved_bytes": None,
        "inference_allocated_bytes": None,
    }


def test_utilization_is_the_mean_of_bursty_samples_not_one_reading(jetson):
    """nvgpu reads ~100% while a clip runs and 0 between clips; the health
    check must report the average, not whichever value it happened to read."""
    load = Path(jetson) / "sys/devices/gpu.0/load"
    sampler = UtilizationSampler(root=jetson, interval=0.01, window=0.1)
    for value in ["1000", "0", "0", "0", "0", "1000", "0", "0", "0", "0"]:
        load.write_text(value + "\n")
        sampler._samples.append(read_utilization(jetson))  # noqa: SLF001 - deterministic samples
    sampler._thread = object()  # noqa: SLF001 - don't start the background thread
    assert sampler.mean() == 20.0


def test_sampler_reports_nothing_without_a_gpu(tmp_path):
    assert UtilizationSampler(root=str(tmp_path)).mean() is None


def test_worker_floor_comes_from_the_agents_reported_backend_and_floor():
    """The agent reports the backend it selected (auto included) and its effective
    floor (defaults included); the dashboard must not re-derive them from raw YAML."""
    from orpheus_ui.api.system import _gpu_worker_floor_mib

    assert _gpu_worker_floor_mib({"backend": "gpu_worker", "floor_memory_mib": 3800}) == 3800
    assert _gpu_worker_floor_mib({"backend": "inprocess", "floor_memory_mib": None}) is None
    assert _gpu_worker_floor_mib({"backend": "gpu_worker", "floor_memory_mib": True}) is None
