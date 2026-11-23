#!/usr/bin/env python3
"""Print a pip ``--require-hashes`` requirements file for the PANNs worker venv.

Every pin in constraints.txt gets the SHA-256 of each tested wheel recorded in
wheels.sha256, so ``pip install --require-hashes`` refuses any artifact that is
not one of them. torch is NVIDIA's local JetPack wheel, given as the argument
and pinned to its recorded hash. A pin without a recorded hash is an error, not
an unhashed install. Standard library only; runs on the worker's Python 3.8.

    requirements_hashed.py /path/to/torch-...-cp38-cp38-linux_aarch64.whl
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def build(torch_wheel: str, constraints: Path, hashes_file: Path) -> list[str]:
    recorded: dict[tuple[str, str], list[str]] = {}
    for line in hashes_file.read_text().splitlines():
        if not line.strip():
            continue
        digest, filename = line.split()
        name, version = filename.split("-")[:2]
        digests = recorded.setdefault((_norm(name), version), [])
        if digest not in digests:  # the file lists some wheels twice
            digests.append(digest)
    lines = []
    for raw in constraints.read_text().splitlines():
        spec = raw.split("#", 1)[0].strip()
        if "==" not in spec:
            continue
        name, version = (part.strip() for part in spec.split("==", 1))
        digests = recorded.get((_norm(name), version))
        if not digests:
            raise SystemExit(f"no recorded wheel hash for {name}=={version} in {hashes_file.name}")
        hashes = " ".join(f"--hash=sha256:{d}" for d in digests)
        target = torch_wheel if _norm(name) == "torch" else f"{name}=={version}"
        lines.append(f"{target} {hashes}")
    return lines


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1]:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    print("\n".join(build(argv[1], HERE / "constraints.txt", HERE / "wheels.sha256")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
