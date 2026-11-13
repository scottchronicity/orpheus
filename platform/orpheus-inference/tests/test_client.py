"""Real subprocess integration/failure tests, independent of any ML runtime."""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from orpheus_inference import protocol as p
from orpheus_inference.client import WorkerClient, WorkerOptions, WorkerUnavailable

FAKE = Path(__file__).with_name("fake_worker.py")


def wait_for(client, predicate, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        state = client.snapshot()
        if predicate(state):
            return state
        time.sleep(0.01)
    pytest.fail("worker state did not converge: %r" % client.snapshot())


@pytest.fixture
def clients():
    running = []

    def create(mode="normal", **overrides):
        options = dict(
            startup_timeout=1,
            request_timeout=0.3,
            start_memory_mib=0,
            floor_memory_mib=0,
            restart_backoff=0.05,
            max_starts=1,
            restart_window=10,
            poll_interval=0.01,
        )
        options.update(overrides)
        env = dict(os.environ, PYTHONPATH=str(FAKE.parent.parent / "src"))
        client = WorkerClient(
            [sys.executable, "-u", str(FAKE), "--mode", mode],
            env,
            WorkerOptions(**options),
            expected_ready={"device": "cuda"},
        )
        running.append(client)
        client.start()
        return client

    yield create
    for client in running:
        client.close()
        assert client.snapshot()["pid"] is None


def test_pipe_roundtrip_and_stdout_isolation(clients, capfd):
    client = clients()
    ready = wait_for(client, lambda s: s["ready"])
    for _ in range(3):
        header, body = client.request({"type": "ping"})
        assert header["type"] == "pong"
        assert body == b""
    assert client.snapshot()["starts"] == 1
    assert ready["runtime"]["model_loaded"]
    stderr = capfd.readouterr().err
    assert "native library stdout" in stderr
    assert "python library stdout" in stderr


@pytest.mark.parametrize("mode", ["startup_exit", "startup_garbage", "startup_hang"])
def test_failed_start_is_reaped_and_circuit_breaks(clients, mode):
    client = clients(mode, startup_timeout=0.2)
    state = wait_for(client, lambda s: s["state"] == "circuit_open")
    assert state["pid"] is None
    assert state["failures"] == 1
    assert state["last_exit_code"] is not None
    assert state["last_error"]


@pytest.mark.parametrize(
    "mode, error",
    [
        ("hang", p.WorkerTimeout),
        ("crash", p.WorkerDied),
        ("garble", p.ProtocolError),
        ("wrongid", p.ProtocolError),
    ],
)
def test_exchange_failure_reaps_without_retry(clients, mode, error):
    client = clients(mode)
    wait_for(client, lambda s: s["ready"])
    with pytest.raises(error):
        client.request({"type": "infer", "shape": [320]}, bytes(1280))
    assert not client.snapshot()["ready"]
    assert client.snapshot()["pid"] is None
    assert client.snapshot()["starts"] == 1


def test_idle_death_is_reaped_and_recovered_without_a_request(clients):
    client = clients(max_starts=2)
    first = wait_for(client, lambda s: s["ready"])
    os.kill(first["pid"], 9)
    second = wait_for(client, lambda s: s["ready"] and s["starts"] == 2)
    assert first["pid"] != second["pid"]
    assert client.request({"type": "ping"})[0]["type"] == "pong"


def test_reload_outlasts_clip_but_new_work_can_run_afterward(clients):
    client = clients("slow_load", startup_timeout=2)
    # Startup runs independently; a short-lived request must not wait for readiness.
    with pytest.raises(WorkerUnavailable):
        client.request({"type": "ping"}, deadline=time.monotonic() + 0.02)
    wait_for(client, lambda s: s["ready"])
    assert client.request({"type": "ping"})[0]["status"] == "ok"


def test_spawn_from_short_lived_thread_survives_thread_exit(clients):
    holder = []
    thread = threading.Thread(target=lambda: holder.append(clients()))
    thread.start()
    thread.join()
    client = holder[0]
    wait_for(client, lambda s: s["ready"])
    assert client.request({"type": "ping"})[0]["type"] == "pong"


def test_close_interrupts_startup_and_is_idempotent(clients):
    client = clients("startup_hang", startup_timeout=30)
    wait_for(client, lambda s: s["pid"] is not None)
    before = time.monotonic()
    client.close()
    client.close()
    assert time.monotonic() - before < 3
    assert client.snapshot()["state"] == "stopped"


def test_close_interrupts_inference(clients):
    client = clients("hang", request_timeout=30)
    wait_for(client, lambda s: s["ready"])
    errors = []

    def exchange():
        try:
            client.request({"type": "infer", "shape": [320]}, bytes(1280))
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=exchange)
    thread.start()
    time.sleep(0.05)
    client.close()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert errors


def test_memory_gate_does_not_spawn_and_recovers(clients, monkeypatch):
    def deny(_minimum):
        raise MemoryError("synthetic host memory pressure")

    monkeypatch.setattr("orpheus_inference.client.require_memory", deny)
    client = clients(start_memory_mib=8704, floor_memory_mib=3800)
    state = wait_for(client, lambda s: s["state"] == "memory_blocked" and s["pid"] is None)
    assert state["starts"] == 0
    monkeypatch.setattr("orpheus_inference.client.require_memory", lambda _minimum: 10000)
    wait_for(client, lambda s: s["ready"])
    monkeypatch.setattr("orpheus_inference.client.require_memory", deny)
    state = wait_for(client, lambda s: s["state"] == "memory_blocked" and s["pid"] is None)
    assert state["pid"] is None


def test_response_validation_failure_reaps(clients):
    client = clients()
    wait_for(client, lambda s: s["ready"])

    def invalid(_header, _body):
        raise p.ProtocolError("bad shape")

    with pytest.raises(p.ProtocolError, match="bad shape"):
        client.request({"type": "ping"}, validate=invalid)
    assert client.snapshot()["pid"] is None


def test_worker_side_memory_watchdog_exits(clients):
    client = clients("memory_exit")
    state = wait_for(client, lambda s: s["state"] == "circuit_open")
    assert state["last_exit_code"] == 12
    assert state["pid"] is None


def test_expired_unsent_request_keeps_ready_worker(clients):
    client = clients()
    wait_for(client, lambda s: s["ready"])
    with pytest.raises(WorkerUnavailable, match="expired"):
        client.request({"type": "ping"}, deadline=time.monotonic() - 1)
    assert client.snapshot()["ready"]
    assert client.snapshot()["starts"] == 1


@pytest.mark.parametrize("inflight", [False, True])
def test_worker_exits_when_parent_process_is_killed(tmp_path, inflight):
    pidfile = tmp_path / "child.pid"
    code = """
import os, sys, time
from pathlib import Path
from orpheus_inference.client import WorkerClient, WorkerOptions
client = WorkerClient([sys.executable, '-u', sys.argv[1], '--mode', sys.argv[3]], os.environ,
    WorkerOptions(start_memory_mib=0, floor_memory_mib=0, startup_timeout=5, request_timeout=30))
client.start()
while not client.snapshot()['ready']:
    time.sleep(.01)
Path(sys.argv[2]).write_text(str(client.snapshot()['pid']))
if sys.argv[3] == 'hang':
    client.request({'type':'infer', 'shape':[320]}, bytes(1280))
else:
    time.sleep(30)
"""
    parent = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            code,
            str(FAKE),
            str(pidfile),
            "hang" if inflight else "normal",
        ],
        env=dict(os.environ, PYTHONPATH=str(FAKE.parent.parent / "src")),
    )
    child = None
    try:
        end = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < end:
            time.sleep(0.01)
        child = int(pidfile.read_text())
        time.sleep(0.05)
        parent.kill()
        parent.wait(timeout=3)
        end = time.monotonic() + 5
        while time.monotonic() < end:
            # A reparented zombie is exited; only its adopting parent can reap it.
            state = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True, check=False
            ).stdout.strip()
            if not state or state.startswith("Z"):
                break
            time.sleep(0.02)
        else:
            pytest.fail("orphan worker stayed alive")
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=3)
        if child is not None:
            try:
                os.kill(child, 9)
            except ProcessLookupError:
                pass
