"""Python 3.8 entry point. Isolate stdout before importing numerical libraries."""

from orpheus_inference.worker import isolate_stdio, serve


def main() -> None:
    """Run the pinned CUDA worker; never silently fall back to CPU."""
    incoming, outgoing = isolate_stdio()
    # Importing the runtime module must happen after descriptor isolation.
    import argparse

    from .runtime import PannsRuntime

    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--floor-mib", type=int, required=True)
    parser.add_argument("--max-seconds", type=float, default=40)
    args = parser.parse_args()
    if args.floor_mib <= 0 or not 0 < args.max_seconds <= 120:
        parser.error("floor-mib must be positive and max-seconds within (0,120]")
    runtime = PannsRuntime(args.checkpoint, args.max_seconds)
    serve(incoming, outgoing, args.parent_pid, args.floor_mib, runtime.load, runtime.infer)


if __name__ == "__main__":
    main()
