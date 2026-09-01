"""How much space each kind of recording is using.

This is deliberately separate from :mod:`orpheus_common.storage.cleanup`.
Cleanup knows about one directory and the policy for trimming it; the
survey here knows about *every* directory under the data root, including
the ones nothing trims. Putting the survey inside the cleanup class would
have tied "can we measure it" to "does something delete it", and the
directories with no cleanup are exactly the ones worth watching — a
station can hold hundreds of gigabytes of timelapses that no policy will
ever touch.

So: measure everything, always. Policy is layered on top by whoever holds
it, and is expected to cover only some of these.

The survey walks directories, so it belongs on a component's existing
periodic pass — ``orpheus_common.storage.sweep`` calls it once per sweep —
and not in a request handler.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from orpheus_common.storage.cleanup import DiskSpace, read_disk_space


@dataclass(frozen=True)
class StorageCategory:
    """A directory under the data root that accumulates recordings."""

    key: str
    label: str
    relative_path: str
    # Said on screen next to the size, so it is worth being concrete.
    description: str


# Every directory that grows. Sizes are reported for all of them; whether
# anything trims a given one is a separate question, answered elsewhere.
DATA_ROOT_CATEGORIES: tuple[StorageCategory, ...] = (
    StorageCategory(
        key="audio_motion",
        label="Audio clips",
        relative_path="audio/audio_motion",
        description="Clips recorded when a microphone hears something",
    ),
    StorageCategory(
        key="video_motion",
        label="Motion video",
        relative_path="video/video_motion",
        description="Clips recorded when a camera sees movement",
    ),
    StorageCategory(
        key="snapshots",
        label="Snapshots",
        relative_path="video/snapshots",
        description="Periodic still frames from each camera",
    ),
    StorageCategory(
        key="timelapses",
        label="Timelapses",
        relative_path="video/timelapses",
        description="Rendered timelapse videos",
    ),
    StorageCategory(
        key="database",
        label="Detections database",
        relative_path="detections",
        description="Detections, entities, and the write-ahead log",
    ),
)


def measure_directory(path: Path) -> tuple[int, int]:
    """Total bytes and file count under ``path``, recursively.

    Returns ``(0, 0)`` for a directory that does not exist — a station that
    has not recorded any timelapses yet genuinely holds zero of them, which
    is different from the "never measured" case the caller handles by not
    having a survey at all.

    Uses ``os.scandir`` and reads size from the directory entry: on a
    quarter-million files that is the difference between a survey that
    finishes inside the tick and one that does not. Files that vanish
    mid-walk (a sweep running alongside) are skipped rather than raising.
    """
    total_bytes = 0
    file_count = 0

    if not path.exists():
        return 0, 0

    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                            file_count += 1
                    except OSError:
                        # Deleted between listing and stat, or unreadable.
                        continue
        except OSError:
            continue

    return total_bytes, file_count


def survey_data_root(
    root: Path,
    categories: tuple[StorageCategory, ...] = DATA_ROOT_CATEGORIES,
    disk_space=read_disk_space,
) -> dict[str, Any]:
    """Measure every category under ``root``, plus the disk they share.

    The result is publishable as-is on a health payload. ``disk_space`` is
    injectable so tests can fake a nearly-full filesystem.
    """
    measured_at = datetime.now().astimezone().isoformat()

    measured: dict[str, Any] = {}
    for category in categories:
        path = root / category.relative_path
        total_bytes, file_count = measure_directory(path)
        measured[category.key] = {
            "path": str(path),
            "label": category.label,
            "description": category.description,
            "bytes": total_bytes,
            "file_count": file_count,
            "exists": path.exists(),
        }

    space: Optional[DiskSpace] = disk_space(root)

    return {
        "measured_at": measured_at,
        "data_root": str(root),
        "categories": measured,
        "disk": {
            "total_bytes": space.total_bytes if space else None,
            "free_bytes": space.free_bytes if space else None,
            "free_percent": round(space.free_percent, 1) if space else None,
        },
    }
