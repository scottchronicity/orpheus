"""Tests for orpheus_common.utils.buffer.PreRollRingBuffer."""

from __future__ import annotations

from orpheus_common.utils.buffer import PreRollRingBuffer


class TestPreRollRingBufferInit:
    """Tests for __init__ capacity calculation."""

    def test_max_len_is_seconds_times_rate(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=3, items_per_second=10)
        assert buf._max_len == 30

    def test_max_len_audio_defaults(self) -> None:
        """5s * 47 chunks/s = 235 slots (typical audio pre-roll)."""
        buf: PreRollRingBuffer[bytes] = PreRollRingBuffer(max_seconds=5, items_per_second=47)
        assert buf._max_len == 235

    def test_max_len_video_defaults(self) -> None:
        """3s * 10 fps = 30 slots (typical video pre-roll)."""
        buf: PreRollRingBuffer[bytes] = PreRollRingBuffer(max_seconds=3, items_per_second=10)
        assert buf._max_len == 30

    def test_buffer_starts_empty(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=5, items_per_second=10)
        assert len(buf) == 0
        assert buf.get_snapshot() == []


class TestPreRollRingBufferAppend:
    """Tests for append behaviour."""

    def test_append_increases_length(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        buf.append(1)
        assert len(buf) == 1

    def test_append_multiple_items(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        for i in range(5):
            buf.append(i)
        assert len(buf) == 5

    def test_evicts_oldest_when_full(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=1, items_per_second=3)
        # capacity = 3
        buf.append(10)
        buf.append(20)
        buf.append(30)
        buf.append(40)  # evicts 10
        assert buf.get_snapshot() == [20, 30, 40]

    def test_length_never_exceeds_max(self) -> None:
        max_len = 5
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=1, items_per_second=max_len)
        for i in range(20):
            buf.append(i)
        assert len(buf) == max_len

    def test_works_with_bytes(self) -> None:
        buf: PreRollRingBuffer[bytes] = PreRollRingBuffer(max_seconds=2, items_per_second=4)
        buf.append(b"\x00\x01")
        buf.append(b"\x02\x03")
        assert len(buf) == 2

    def test_works_with_strings(self) -> None:
        buf: PreRollRingBuffer[str] = PreRollRingBuffer(max_seconds=2, items_per_second=5)
        buf.append("hello")
        buf.append("world")
        assert buf.get_snapshot() == ["hello", "world"]


class TestPreRollRingBufferGetSnapshot:
    """Tests for get_snapshot."""

    def test_returns_items_in_insertion_order(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        for i in range(5):
            buf.append(i)
        assert buf.get_snapshot() == [0, 1, 2, 3, 4]

    def test_returns_copy_not_reference(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        buf.append(1)
        snap1 = buf.get_snapshot()
        buf.append(2)
        snap2 = buf.get_snapshot()
        assert snap1 == [1]
        assert snap2 == [1, 2]

    def test_exclude_last_removes_final_item(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        for i in range(5):
            buf.append(i)
        result = buf.get_snapshot(exclude_last=True)
        assert result == [0, 1, 2, 3]

    def test_exclude_last_false_returns_all(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        for i in range(5):
            buf.append(i)
        assert buf.get_snapshot(exclude_last=False) == [0, 1, 2, 3, 4]

    def test_exclude_last_on_single_item_returns_empty(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        buf.append(99)
        assert buf.get_snapshot(exclude_last=True) == []

    def test_snapshot_on_empty_buffer_returns_empty_list(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        assert buf.get_snapshot() == []

    def test_exclude_last_on_empty_buffer_returns_empty_list(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        assert buf.get_snapshot(exclude_last=True) == []

    def test_snapshot_after_eviction_reflects_evicted_items(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=1, items_per_second=3)
        # capacity = 3
        for i in range(6):
            buf.append(i)
        # Only last 3 items remain: [3, 4, 5]
        assert buf.get_snapshot() == [3, 4, 5]

    def test_snapshot_is_list_type(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=1, items_per_second=5)
        buf.append(1)
        result = buf.get_snapshot()
        assert isinstance(result, list)


class TestPreRollRingBufferClear:
    """Tests for clear."""

    def test_clear_empties_buffer(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        for i in range(10):
            buf.append(i)
        buf.clear()
        assert len(buf) == 0
        assert buf.get_snapshot() == []

    def test_can_append_after_clear(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        for i in range(5):
            buf.append(i)
        buf.clear()
        buf.append(99)
        assert buf.get_snapshot() == [99]

    def test_clear_on_empty_is_safe(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        buf.clear()  # Should not raise
        assert len(buf) == 0


class TestPreRollRingBufferLen:
    """Tests for __len__."""

    def test_len_zero_when_empty(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        assert len(buf) == 0

    def test_len_grows_with_appends(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=2, items_per_second=10)
        for i in range(7):
            buf.append(i)
            assert len(buf) == i + 1

    def test_len_capped_at_max(self) -> None:
        buf: PreRollRingBuffer[int] = PreRollRingBuffer(max_seconds=1, items_per_second=5)
        for i in range(20):
            buf.append(i)
        assert len(buf) == 5


class TestPreRollRingBufferGenericTypes:
    """Tests to ensure the buffer works with different concrete types."""

    def test_generic_with_dicts(self) -> None:
        from typing import Any, Dict

        buf: PreRollRingBuffer[Dict[str, Any]] = PreRollRingBuffer(
            max_seconds=2, items_per_second=5
        )
        buf.append({"key": "value1"})
        buf.append({"key": "value2"})
        snap = buf.get_snapshot()
        assert len(snap) == 2
        assert snap[0]["key"] == "value1"

    def test_generic_with_tuples(self) -> None:
        from typing import Tuple

        buf: PreRollRingBuffer[Tuple[int, str]] = PreRollRingBuffer(
            max_seconds=1, items_per_second=4
        )
        buf.append((1, "a"))
        buf.append((2, "b"))
        assert buf.get_snapshot() == [(1, "a"), (2, "b")]

    def test_integration_audio_preroll(self) -> None:
        """Simulate a 5-second audio pre-roll at 47 chunks/second."""
        chunks_per_second = 47
        buf: PreRollRingBuffer[bytes] = PreRollRingBuffer(
            max_seconds=5, items_per_second=chunks_per_second
        )
        # Fill 6 seconds of fake audio (1 byte per chunk for simplicity)
        total_chunks = chunks_per_second * 6
        for i in range(total_chunks):
            buf.append(bytes([i % 256]))

        snap = buf.get_snapshot()
        # Should retain exactly 5s worth
        assert len(snap) == chunks_per_second * 5

    def test_integration_video_preroll_exclude_last(self) -> None:
        """Simulate 3-second video pre-roll at 10fps with trigger frame exclusion."""
        fps = 10
        buf: PreRollRingBuffer[bytes] = PreRollRingBuffer(max_seconds=3, items_per_second=fps)
        total_frames = fps * 4  # 4 seconds
        for i in range(total_frames):
            buf.append(bytes([i % 256]))

        # exclude_last avoids duplicating the trigger frame
        snap = buf.get_snapshot(exclude_last=True)
        assert len(snap) == fps * 3 - 1
