"""Framing bounds, deadline I/O and fail-closed host accounting."""

import os
import time

import pytest

from orpheus_inference import protocol as p
from orpheus_inference.client import WorkerOptions
from orpheus_inference.resources import mem_available_mib, require_memory


@pytest.mark.parametrize(
    "prefix",
    [
        p.PREFIX.pack(b"BAD!", 0, 0),
        p.PREFIX.pack(p.MAGIC, p.MAX_HEADER + 1, 0),
        p.PREFIX.pack(p.MAGIC, 0, p.MAX_PAYLOAD + 1),
    ],
)
def test_prefix_limits(prefix):
    with pytest.raises(p.ProtocolError):
        p.parse_prefix(prefix)


@pytest.mark.parametrize("body", [b"not json", b"[]", b"null"])
def test_bad_headers(body):
    with pytest.raises(p.ProtocolError):
        p.parse_header(body)


def test_deadline_and_eof():
    incoming, outgoing = os.pipe()
    try:
        os.set_blocking(incoming, False)
        with pytest.raises(p.WorkerTimeout):
            p.read_exact_deadline(incoming, 1, time.monotonic() + 0.01)
        p.write_all_deadline(outgoing, (b"abc",), time.monotonic() + 1)
        assert p.read_exact_deadline(incoming, 3, time.monotonic() + 1) == b"abc"
        os.close(outgoing)
        outgoing = None
        with pytest.raises(p.WorkerDied):
            p.read_exact_deadline(incoming, 1, time.monotonic() + 1)
    finally:
        os.close(incoming)
        if outgoing is not None:
            os.close(outgoing)


def test_blocking_partial_eof():
    incoming, outgoing = os.pipe()
    os.write(outgoing, b"a")
    os.close(outgoing)
    try:
        with pytest.raises(p.ProtocolError):
            p.read_exact_blocking(incoming, 2)
        assert p.read_exact_blocking(incoming, 1) is None
    finally:
        os.close(incoming)


def test_host_memory(tmp_path, monkeypatch):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable: 8912896 kB\n")
    assert mem_available_mib(meminfo) == 8704
    meminfo.write_text("MemAvailable: invalid\n")
    assert mem_available_mib(meminfo) is None
    assert mem_available_mib(tmp_path / "missing") is None
    monkeypatch.setattr("orpheus_inference.resources.mem_available_mib", lambda: None)
    with pytest.raises(MemoryError):
        require_memory(3800)


@pytest.mark.parametrize(
    "options",
    [
        {"startup_timeout": 0},
        {"request_timeout": float("nan")},
        {"max_starts": 0},
        {"start_memory_mib": 1, "floor_memory_mib": 2},
    ],
)
def test_invalid_policy(options):
    with pytest.raises(ValueError):
        WorkerOptions(**options)
