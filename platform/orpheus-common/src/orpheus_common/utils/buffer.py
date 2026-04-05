"""Time-aware generic ring buffer for pre-roll capture in sensor agents."""

from __future__ import annotations

import collections
from typing import Deque, Generic, List, TypeVar

T = TypeVar("T")


class PreRollRingBuffer(Generic[T]):
    """
    A time-aware, generic ring buffer for capturing pre-trigger sensor data.

    Stores the most recent N seconds of items, enabling agents to prepend
    pre-trigger data to detection events.  The buffer capacity is derived
    from the desired duration and the known throughput of the data source.

    Type parameter T allows the same class to be reused for both audio
    (bytes) and video (VideoFrame) pipelines.

    Args:
        max_seconds:      Maximum duration of data to retain, in seconds.
        items_per_second: Expected throughput of the data source (e.g.
                          frames-per-second for video, chunks-per-second
                          for audio).
    """

    def __init__(self, max_seconds: int, items_per_second: int) -> None:
        self._max_len = max_seconds * items_per_second
        self._buffer: Deque[T] = collections.deque(maxlen=self._max_len)

    def append(self, item: T) -> None:
        """Add *item* to the buffer, evicting the oldest entry if full."""
        self._buffer.append(item)

    def get_snapshot(self, exclude_last: bool = False) -> List[T]:
        """
        Return a list snapshot of the current buffer contents.

        Args:
            exclude_last: When True, omit the most-recently added item.
                          Use this to avoid duplicating the trigger frame
                          when prepending pre-roll data to a detection event.

        Returns:
            Ordered list from oldest to newest (minus last if excluded).
        """
        snap: List[T] = list(self._buffer)
        if exclude_last and snap:
            return snap[:-1]
        return snap

    def clear(self) -> None:
        """Remove all items from the buffer."""
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)
