"""Worker-side serving loop and process/host guards; no framework imports."""

import os
import sys
import threading
from typing import Any, Callable, Dict, Tuple

from . import protocol as p
from .resources import require_memory


def isolate_stdio() -> Tuple[int, int]:
    """Keep protocol on private fds before any model/library imports.

    Both native fd-1 writes and Python prints go to stderr, including output
    buffered by model libraries. The original protocol fds stay non-inheritable.
    """
    incoming, outgoing = os.dup(0), os.dup(1)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    sys.stdout.flush()
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return incoming, outgoing


def serve(
    incoming: int,
    outgoing: int,
    parent_pid: int,
    floor_mib: int,
    load: Callable[[], Dict[str, Any]],
    infer: Callable[[dict, bytearray], Tuple[dict, Any]],
) -> None:
    """Load once, announce readiness, then serve serial requests until EOF.

    Watch the *process* parent, not the spawning thread. This also handles a
    parent killed while the worker is inside native inference (not reading EOF).
    MemAvailable is checked throughout load, warmup, inference and idle time.
    """
    stopped = threading.Event()

    def guard() -> None:
        while not stopped.is_set():
            if os.getppid() != parent_pid:
                os._exit(70)
            if floor_mib:
                try:
                    require_memory(floor_mib)
                except MemoryError as exc:
                    sys.stderr.write("inference worker memory stop: %s\n" % exc)
                    sys.stderr.flush()
                    os._exit(12)
            stopped.wait(0.1)

    if os.getppid() != parent_pid:
        raise RuntimeError("parent already gone")
    threading.Thread(target=guard, name="inference-guard", daemon=True).start()

    def send(header: dict, body: Any = b"") -> None:
        hb = p.encode_header(header)
        view = p.as_bytes_view(body)
        p.parse_prefix(p.pack_prefix(hb, view.nbytes))
        p.write_all_blocking(outgoing, p.pack_prefix(hb, view.nbytes), hb, view)

    def part(size: int) -> bytearray:
        if not size:
            return bytearray()
        value = p.read_exact_blocking(incoming, size)
        if value is None:
            raise p.ProtocolError("EOF inside frame")
        return value

    try:
        metadata = load()
        send(dict(metadata, type="ready", protocol=p.PROTOCOL_VERSION))
        while True:
            prefix = p.read_exact_blocking(incoming, p.PREFIX.size)
            if prefix is None:
                return
            hlen, plen = p.parse_prefix(prefix)
            header = p.parse_header(part(hlen))
            body = part(plen)
            rid = header.get("id")
            try:
                kind = header.get("type")
                if kind == "shutdown":
                    send({"type": "bye", "id": rid, "status": "ok"})
                    return
                if kind == "ping":
                    send({"type": "pong", "id": rid, "status": "ok"})
                elif kind == "infer":
                    result, payload = infer(header, body)
                    send(dict(result, type="result", status="ok", id=rid), payload)
                else:
                    raise ValueError("unknown request type")
            except Exception as exc:
                send(
                    {
                        "type": "error",
                        "id": rid,
                        "status": "error",
                        "error": "%s: %s" % (type(exc).__name__, str(exc)[:200]),
                    }
                )
    except BrokenPipeError:
        return
    finally:
        stopped.set()
        os.close(incoming)
        os.close(outgoing)
