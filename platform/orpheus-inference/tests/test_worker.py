"""Exercise worker framing/dispatch directly as well as in subprocess tests."""

import os

import pytest

from orpheus_inference import protocol as p
from orpheus_inference.worker import serve


def frame(header, body=b""):
    hb = p.encode_header(header)
    return p.pack_prefix(hb, len(body)) + hb + body


def frames(raw):
    result = []
    while raw:
        hlen, plen = p.parse_prefix(raw[: p.PREFIX.size])
        offset = p.PREFIX.size
        header = p.parse_header(raw[offset : offset + hlen])
        offset += hlen
        result.append((header, raw[offset : offset + plen]))
        raw = raw[offset + plen :]
    return result


def run_server(raw, infer):
    incoming, writer = os.pipe()
    reader, outgoing = os.pipe()
    os.write(writer, raw)
    os.close(writer)
    try:
        serve(incoming, outgoing, os.getppid(), 0, lambda: {"model_loaded": True}, infer)
        return frames(os.read(reader, 65536))
    finally:
        os.close(reader)


def test_worker_dispatch_shutdown_and_python_error():
    def infer(_header, body):
        assert body == b"input"
        return {"shape": [1]}, b"output"

    responses = run_server(
        frame({"type": "ping", "id": 1})
        + frame({"type": "infer", "id": 2}, b"input")
        + frame({"type": "invalid", "id": 3})
        + frame({"type": "shutdown", "id": 4}),
        infer,
    )
    assert responses[0][0]["type"] == "ready"
    assert responses[1][0]["type"] == "pong"
    assert responses[2][1] == b"output"
    assert responses[3][0]["status"] == "error"
    assert responses[4][0]["type"] == "bye"


def test_worker_eof_and_rejected_inference():
    def infer(_header, _body):
        raise ValueError("invalid input")

    responses = run_server(frame({"type": "infer", "id": 1}), infer)
    assert "invalid input" in responses[1][0]["error"]


def test_worker_partial_frame_and_bad_magic():
    with pytest.raises(p.ProtocolError):
        run_server(p.PREFIX.pack(b"BAD!", 0, 0), None)
    with pytest.raises(p.ProtocolError):
        run_server(p.PREFIX.pack(p.MAGIC, 5, 0), None)
