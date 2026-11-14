"""PANNs validation without importing torch/panns or loading a checkpoint."""

import ast
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from orpheus_worker_panns.runtime import PannsRuntime, no_shell


@pytest.fixture
def pinned_runtime(tmp_path, monkeypatch):
    from orpheus_worker_panns import runtime

    monkeypatch.setattr(runtime, "sys", SimpleNamespace(version_info=(3, 8)))
    monkeypatch.setattr(np, "__version__", "1.24.4")
    monkeypatch.setattr(runtime.platform, "machine", lambda: "aarch64")
    monkeypatch.setenv("HOME", str(tmp_path))
    labels = tmp_path / "panns_data/class_labels_indices.csv"
    labels.parent.mkdir()
    labels.write_text("staged canonical labels")
    checkpoint = tmp_path / "checkpoint"
    checkpoint.write_bytes(b"test checkpoint")
    monkeypatch.setattr(
        runtime, "CHECKPOINT_SHA256", hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    )
    # Restore os.system even though load assigns it while blocking downloads.
    monkeypatch.setattr(runtime.os, "system", runtime.os.system)
    torch = MagicMock()
    torch.__version__ = runtime.TORCH_VERSION
    torch.version.cuda = "11.4"
    torch.cuda.is_available.return_value = True
    torch.cuda.memory_allocated.return_value = 1024
    torch.cuda.memory_reserved.return_value = 2048
    sed = MagicMock(device="cuda")
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(
        sys.modules, "panns_inference", SimpleNamespace(SoundEventDetection=lambda **_kw: sed)
    )
    return PannsRuntime(str(checkpoint), 40), torch, sed


def test_load_warms_before_ready_with_pinned_settings(pinned_runtime):
    runtime, torch, sed = pinned_runtime
    ready = runtime.load()
    assert ready["model_loaded"]
    assert ready["device"] == "cuda"
    torch.set_num_threads.assert_called_once_with(1)
    assert torch.backends.cudnn.allow_tf32 is False
    assert torch.backends.cudnn.benchmark is False
    assert sed.inference.call_args.args[0].shape == (1, 40 * 32000)
    torch.cuda.synchronize.assert_called_once()


@pytest.mark.parametrize("failure", ["checkpoint", "missing", "torch", "cuda", "device"])
def test_load_refuses_unvalidated_assets_or_runtime(pinned_runtime, failure):
    runtime, torch, sed = pinned_runtime
    if failure == "checkpoint":
        runtime.checkpoint.write_bytes(b"different checkpoint")
    elif failure == "missing":
        runtime.checkpoint = runtime.checkpoint.with_name("missing")
    elif failure == "torch":
        torch.__version__ = "2.4.0"
    elif failure == "cuda":
        torch.cuda.is_available.return_value = False
    else:
        sed.device = "cpu"
    with pytest.raises((ValueError, FileNotFoundError, RuntimeError)):
        runtime.load()


def test_worker_entrypoint_isolates_stdout_before_serving(monkeypatch):
    from orpheus_worker_panns import __main__ as entry

    serve = MagicMock()
    monkeypatch.setattr(entry, "isolate_stdio", lambda: (100, 101))
    monkeypatch.setattr(entry, "serve", serve)
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker", "--checkpoint", "unused", "--parent-pid", "12", "--floor-mib", "3000"],
    )
    entry.main()
    assert serve.call_args.args[:4] == (100, 101, 12, 3000)


def test_worker_cli_refuses_unsafe_floor(monkeypatch):
    from orpheus_worker_panns import __main__ as entry

    monkeypatch.setattr(entry, "isolate_stdio", lambda: (100, 101))
    monkeypatch.setattr(
        sys, "argv", ["worker", "--checkpoint", "unused", "--parent-pid", "12", "--floor-mib", "0"]
    )
    with pytest.raises(SystemExit):
        entry.main()


@pytest.mark.parametrize(
    "header, body",
    [
        ({"dtype": "f8", "shape": [1]}, bytes(4)),
        ({"dtype": "<f4", "shape": [1, 1]}, bytes(4)),
        ({"dtype": "<f4", "shape": [True]}, bytes(4)),
        ({"dtype": "<f4", "shape": [0]}, b""),
        ({"dtype": "<f4", "shape": [32000 * 121]}, b""),
        ({"dtype": "<f4", "shape": [2]}, bytes(4)),
        ({"dtype": "<f4", "shape": [1]}, np.array([np.nan], dtype="<f4").tobytes()),
    ],
)
def test_invalid_audio(header, body):
    with pytest.raises(ValueError):
        PannsRuntime("unused", 40).infer(header, body)


def test_runtime_output():
    class SED:
        def inference(self, audio):
            assert audio.shape == (1, 320)
            return np.zeros((1, 2, 527), dtype=np.float32)

    runtime = PannsRuntime("unused", 40)
    runtime.sed = SED()
    header, output = runtime.infer({"dtype": "<f4", "shape": [320]}, bytes(1280))
    assert header["shape"] == [2, 527]
    assert output.dtype == np.dtype("<f4")


def test_shell_downloads_disabled():
    with pytest.raises(RuntimeError):
        no_shell("wget something")


def test_loading_refuses_nonvalidated_interpreter():
    # Local dev toolchain is 3.9+, runtime refuses it before ML imports.
    with pytest.raises(RuntimeError, match="Python 3.8"):
        PannsRuntime("unused", 40).load()


def test_worker_and_shared_sources_parse_as_python38():
    root = Path(__file__).resolve().parents[3]
    for directory in (
        root / "workers/orpheus-worker-panns/src",
        root / "platform/orpheus-inference/src",
    ):
        for source in directory.rglob("*.py"):
            ast.parse(source.read_text(), feature_version=(3, 8))
