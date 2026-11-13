"""Host memory accounting; cgroup charges omit Jetson GPU/nvmap allocations."""

from pathlib import Path
from typing import Optional


def mem_available_mib(path: Path = Path("/proc/meminfo")) -> Optional[int]:
    """Read MemAvailable; return None when the host cannot report it."""
    try:
        for line in path.read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def require_memory(minimum_mib: int) -> int:
    """Fail closed if Linux cannot report the configured host memory reserve."""
    available = mem_available_mib()
    if available is None or available < minimum_mib:
        raise MemoryError("MemAvailable %s MiB is below required %s MiB" % (available, minimum_mib))
    return available
