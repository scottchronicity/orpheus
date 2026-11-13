"""Synthetic executable exercising real pipes/guards without Torch or CUDA."""

import argparse
import os
import struct
import time

from orpheus_inference.worker import isolate_stdio, serve


def main():
    incoming, outgoing = isolate_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--mode", default="normal")
    args = parser.parse_args()

    if args.mode == "memory_exit":
        from orpheus_inference import worker

        def no_memory(_minimum):
            raise MemoryError("synthetic worker host pressure")

        worker.require_memory = no_memory

    def load():
        if args.mode == "startup_exit":
            os._exit(3)
        if args.mode == "startup_hang":
            time.sleep(30)
        if args.mode == "startup_garbage":
            os.write(outgoing, b"stray stdout corrupts the framing\n")
        if args.mode == "slow_load":
            time.sleep(0.4)
        # Neither native writes nor block-buffered Python stdout may corrupt IPC.
        os.write(1, b"native library stdout\n")
        print("python library stdout", flush=True)
        return {
            "model_loaded": True,
            "device": "cuda",
            "sample_rate": 32000,
            "num_classes": 527,
            "frame_duration_seconds": 0.01,
        }

    def infer(header, body):
        if args.mode == "crash":
            os._exit(3)
        if args.mode == "hang":
            time.sleep(30)
        if args.mode == "garble":
            os.write(outgoing, b"not a protocol frame!\n")
        if args.mode == "wrongid":
            from orpheus_inference import protocol as p

            hb = p.encode_header({"id": -1, "status": "ok"})
            p.write_all_blocking(outgoing, p.pack_prefix(hb, 0), hb)
        frames = header["shape"][0] // 320 + 1
        row = struct.pack("<f", 0.9) + b"\0" * (526 * 4)
        data = row * frames
        if args.mode == "badshape":
            data = data[:4]
        if args.mode == "nan":
            data = struct.pack("<f", float("nan")) + data[4:]
        return {"dtype": "<f4", "shape": [frames, 527]}, data

    serve(
        incoming, outgoing, args.parent_pid, 3800 if args.mode == "memory_exit" else 0, load, infer
    )


if __name__ == "__main__":
    main()
