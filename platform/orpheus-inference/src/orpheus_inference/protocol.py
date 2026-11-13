"""Framing shared by the GPU worker (Python 3.8) and its client (Python 3.9).

Derived from the verified 2026-11-12 prototype. Standard library only, Python 3.8 compatible.

Frame layout (all integers big-endian):
    16-byte prefix : magic b"OGW1" | uint32 header_len | uint64 payload_len
    header         : header_len bytes of UTF-8 JSON (an object)
    payload        : payload_len raw bytes (float32 little-endian arrays here)

The prefix makes every frame self-delimiting, so a bad header or a rejected
payload never desynchronises the stream. Only a bad magic or an oversized
length means the stream cannot be trusted any more.
"""

import json
import os
import select
import struct
import time
from typing import Any, Dict, Optional, Tuple

MAGIC = b"OGW1"
PREFIX = struct.Struct(">4sIQ")
MAX_HEADER = 64 * 1024
MAX_PAYLOAD = 64 * 1024 * 1024
PROTOCOL_VERSION = 1


class ProtocolError(Exception):
    """The bytes received are not a valid frame (or not the frame expected)."""


class WorkerTimeout(Exception):
    """The peer did not complete a read or write before the deadline."""


class WorkerDied(Exception):
    """The peer closed its end of a pipe."""


def encode_header(header: Dict[str, Any]) -> bytes:
    return json.dumps(header, separators=(",", ":"), sort_keys=True, allow_nan=False).encode(
        "utf-8"
    )


def pack_prefix(header_bytes: bytes, payload_len: int) -> bytes:
    return PREFIX.pack(MAGIC, len(header_bytes), int(payload_len))


def parse_prefix(buf: bytes) -> Tuple[int, int]:
    magic, hlen, plen = PREFIX.unpack(bytes(buf))
    if magic != MAGIC:
        raise ProtocolError("bad magic %r" % (bytes(magic),))
    if hlen > MAX_HEADER:
        raise ProtocolError("header length %d exceeds %d" % (hlen, MAX_HEADER))
    if plen > MAX_PAYLOAD:
        raise ProtocolError("payload length %d exceeds %d" % (plen, MAX_PAYLOAD))
    return hlen, plen


def parse_header(buf: bytes) -> Dict[str, Any]:
    try:
        header = json.loads(bytes(buf).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ProtocolError("header is not valid JSON: %s" % exc)
    if not isinstance(header, dict):
        raise ProtocolError("header is not a JSON object")
    return header


def as_bytes_view(chunk: Any) -> memoryview:
    mv = memoryview(chunk)
    return mv if mv.format == "B" and mv.ndim == 1 else mv.cast("B")


# ---------------------------------------------------------------- blocking (worker)
def read_exact_blocking(fd: int, n: int) -> Optional[bytearray]:
    """Read exactly n bytes. Returns None on EOF before the first byte;
    raises ProtocolError on EOF part-way through."""
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0
    while got < n:
        k = os.readv(fd, [view[got:]])
        if k == 0:
            if got == 0:
                return None
            raise ProtocolError("EOF after %d of %d bytes" % (got, n))
        got += k
    return buf


def write_all_blocking(fd: int, *chunks: Any) -> None:
    for chunk in chunks:
        view = as_bytes_view(chunk)
        while len(view):
            k = os.write(fd, view)
            view = view[k:]


# ---------------------------------------------------------------- deadline (client)
def read_exact_deadline(fd: int, n: int, deadline: float) -> bytearray:
    """Read exactly n bytes from a non-blocking fd before `deadline` (monotonic)."""
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0
    while got < n:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WorkerTimeout("read timed out after %d of %d bytes" % (got, n))
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            continue
        try:
            k = os.readv(fd, [view[got:]])
        except BlockingIOError:
            continue
        if k == 0:
            raise WorkerDied("worker output closed after %d of %d bytes" % (got, n))
        got += k
    return buf


def write_all_deadline(fd: int, chunks: Any, deadline: float) -> None:
    """Write every chunk to a non-blocking fd before `deadline` (monotonic)."""
    for chunk in chunks:
        view = as_bytes_view(chunk)
        while len(view):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WorkerTimeout("write timed out with %d bytes unsent" % len(view))
            _, ready, _ = select.select([], [fd], [], remaining)
            if not ready:
                continue
            try:
                k = os.write(fd, view)
            except BlockingIOError:
                continue
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise WorkerDied("worker input closed: %s" % exc)
            view = view[k:]
