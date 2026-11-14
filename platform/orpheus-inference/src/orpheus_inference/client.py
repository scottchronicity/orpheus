"""Supervised persistent subprocess, using the validated OGW1 pipe protocol.

Model reloads happen on a persistent maintenance thread, never on a clip's
request path. One lock covers a complete exchange. No fork/preexec_fn or
thread-scoped PR_SET_PDEATHSIG is used.
"""

import collections
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from . import protocol as p
from .resources import mem_available_mib, require_memory


class WorkerUnavailable(RuntimeError):
    """Worker is loading, recovering, memory-blocked, or stopped."""


class WorkerRequestError(RuntimeError):
    """The worker rejected a request."""


@dataclass(frozen=True)
class WorkerOptions:
    """Lifecycle policy; memory limits are host MemAvailable, never cgroups."""

    startup_timeout: float = 60.0
    request_timeout: float = 5.0
    # The owning agent supplies host memory limits for its model.
    start_memory_mib: int = 0
    floor_memory_mib: int = 0
    restart_backoff: float = 2.0
    max_starts: int = 3
    restart_window: float = 300.0
    poll_interval: float = 0.2

    def __post_init__(self) -> None:
        for value in (
            self.startup_timeout,
            self.request_timeout,
            self.restart_backoff,
            self.restart_window,
            self.poll_interval,
        ):
            if not 0 < value < float("inf"):
                raise ValueError("worker timeouts/backoff must be positive and finite")
        if self.max_starts < 1 or self.floor_memory_mib < 0:
            raise ValueError("invalid restart count or memory floor")
        if self.start_memory_mib < self.floor_memory_mib:
            raise ValueError("start memory must cover the running memory floor")


class WorkerClient:
    """Own one child and its pipes; stderr inherits the parent's bounded logging.

    ``snapshot`` never waits for a load or inference. ``request`` requires an
    already-ready worker and never transparently retries work after failure.
    """

    def __init__(
        self,
        command: Sequence[str],
        env: Mapping[str, str],
        options: Optional[WorkerOptions] = None,
        expected_ready: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.command = list(command)
        self.env = dict(env)
        self.options = options or WorkerOptions()
        self.expected_ready = dict(expected_ready or {})
        self._proc = None  # type: Optional[subprocess.Popen]
        self._io = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None  # type: Optional[threading.Thread]
        self._attempts = collections.deque()  # type: collections.deque
        self._next_start = 0.0
        self._next_id = 1
        self._state = {
            "state": "stopped",
            "ready": False,
            "pid": None,
            "starts": 0,
            "failures": 0,
            "last_error": None,
            "last_exit_code": None,
            "runtime": {},
        }  # type: Dict[str, Any]

    def _update(self, **fields: Any) -> None:
        with self._state_lock:
            self._state.update(fields)

    def snapshot(self) -> Dict[str, Any]:
        """Cached lifecycle/readiness plus a fresh host memory reading."""
        with self._state_lock:
            result = dict(self._state)
        result["mem_available_mib"] = mem_available_mib()
        return result

    def start(self) -> None:
        """Start supervision without blocking agent startup on model loading."""
        if self._thread is not None:
            raise RuntimeError("supervisor already started")
        self._update(state="starting")
        self._thread = threading.Thread(
            target=self._maintain, name="inference-supervisor", daemon=True
        )
        self._thread.start()

    def _dispose(self) -> bool:
        proc = self._proc
        if proc is None:
            return True
        if proc.poll() is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        # Retain ownership if reaping fails; never spawn an overlapping child.
        try:
            code = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._update(state="reap_failed", ready=False, last_error="worker could not be reaped")
            return False
        for pipe in (proc.stdin, proc.stdout):
            if pipe is not None:
                pipe.close()
        self._proc = None
        self._update(ready=False, pid=None, last_exit_code=code)
        return True

    def _fail(self, exc: Exception) -> None:
        self._update(ready=False, state="recovering", last_error=str(exc)[:300])
        with self._state_lock:
            self._state["failures"] += 1
            failures = self._state["failures"]
        self._next_start = time.monotonic() + min(
            30.0, self.options.restart_backoff * 2 ** min(failures - 1, 4)
        )
        self._dispose()

    def _read_frame(self, deadline: float) -> Tuple[dict, bytearray]:
        fd = self._proc.stdout.fileno()
        hlen, plen = p.parse_prefix(p.read_exact_deadline(fd, p.PREFIX.size, deadline))
        header = p.parse_header(p.read_exact_deadline(fd, hlen, deadline))
        body = p.read_exact_deadline(fd, plen, deadline) if plen else bytearray()
        return header, body

    def _spawn(self) -> None:
        if self.options.start_memory_mib:
            require_memory(self.options.start_memory_mib)
        self._attempts.append(time.monotonic())
        self._update(state="loading", ready=False)
        self._proc = subprocess.Popen(
            self.command + ["--parent-pid", str(os.getpid())],
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            close_fds=True,
            # Let the agent handle terminal Ctrl-C and reap the child itself.
            start_new_session=True,
            bufsize=0,
        )
        self._update(pid=self._proc.pid)
        with self._state_lock:
            self._state["starts"] += 1
        if self._stop.is_set():
            self._dispose()
            return
        os.set_blocking(self._proc.stdin.fileno(), False)
        os.set_blocking(self._proc.stdout.fileno(), False)
        header, body = self._read_frame(time.monotonic() + self.options.startup_timeout)
        if body or header.get("type") != "ready" or header.get("protocol") != p.PROTOCOL_VERSION:
            raise p.ProtocolError("invalid ready handshake")
        for key, expected in self.expected_ready.items():
            if header.get(key) != expected:
                raise p.ProtocolError("worker readiness mismatch for %s" % key)
        self._update(state="ready", ready=True, runtime=header)

    def _maintain(self) -> None:
        while not self._stop.is_set():
            if self._io.acquire(blocking=False):
                try:
                    if self._proc is not None:
                        if self._proc.poll() is not None:
                            raise p.WorkerDied("worker exited while idle")
                        if not self.snapshot()["ready"]:
                            self._dispose()
                        elif self.options.floor_memory_mib:
                            require_memory(self.options.floor_memory_mib)
                    elif time.monotonic() >= self._next_start:
                        now = time.monotonic()
                        while (
                            self._attempts and now - self._attempts[0] > self.options.restart_window
                        ):
                            self._attempts.popleft()
                        if len(self._attempts) < self.options.max_starts:
                            self._spawn()
                        else:
                            self._update(state="circuit_open", ready=False)
                except MemoryError as exc:
                    self._update(state="memory_blocked", ready=False, last_error=str(exc))
                    self._next_start = time.monotonic() + self.options.restart_backoff
                    self._dispose()
                except Exception as exc:
                    self._fail(exc)
                finally:
                    self._io.release()
            self._stop.wait(self.options.poll_interval)

    def request(
        self,
        header: Mapping[str, Any],
        payload: Any = b"",
        *,
        deadline: Optional[float] = None,
        start_deadline: Optional[float] = None,
        validate: Optional[Callable[[dict, bytearray], None]] = None,
    ) -> Tuple[dict, bytearray]:
        """Exchange within the hard deadline, with an optional earlier cutoff to start."""
        end = min(
            deadline if deadline is not None else float("inf"),
            time.monotonic() + self.options.request_timeout,
        )
        begin_by = min(end, start_deadline) if start_deadline is not None else end
        if not self._io.acquire(timeout=max(0.0, begin_by - time.monotonic())):
            raise WorkerUnavailable("worker busy or loading")
        try:
            if self._stop.is_set() or not self.snapshot()["ready"] or self._proc is None:
                raise WorkerUnavailable("worker not ready")
            if time.monotonic() >= begin_by:
                raise WorkerUnavailable("request expired before exchange")
            rid = self._next_id
            self._next_id += 1
            hb = p.encode_header(dict(header, id=rid))
            view = p.as_bytes_view(payload)
            p.parse_prefix(p.pack_prefix(hb, view.nbytes))
            try:
                if self.options.floor_memory_mib:
                    require_memory(self.options.floor_memory_mib)
            except MemoryError as exc:
                self._fail(exc)
                raise
            if time.monotonic() >= begin_by:
                raise WorkerUnavailable("request expired before exchange")
            try:
                p.write_all_deadline(
                    self._proc.stdin.fileno(), (p.pack_prefix(hb, view.nbytes), hb, view), end
                )
                response, body = self._read_frame(end)
                if response.get("id") != rid:
                    raise p.ProtocolError("response id does not match request")
                if response.get("status") != "ok":
                    raise WorkerRequestError(response.get("error", "worker rejected request"))
                if validate is not None:
                    validate(response, body)
                return response, body
            except Exception as exc:
                # Native runtimes can remain unusable after OOM or an invalid result.
                self._fail(exc)
                raise
        finally:
            self._io.release()

    def close(self) -> None:
        """Stop recovery, interrupt a pending exchange/load, kill and reap the child."""
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=6)
        if not self._io.acquire(timeout=6):
            raise RuntimeError("worker exchange did not stop")
        try:
            if not self._dispose():
                raise RuntimeError("worker could not be reaped")
            self._update(state="stopped", ready=False)
        finally:
            self._io.release()
