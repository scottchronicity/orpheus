"""Tests for the actor-model tick/clock seam (Clock + PeriodicTask)."""

import asyncio
from datetime import timezone

from orpheus_common.actor import ManualClock, PeriodicTask, WallClock


async def _settle(n: int = 3) -> None:
    """Yield to the loop a few times so released coroutines make progress."""
    for _ in range(n):
        await asyncio.sleep(0)


class TestWallClock:
    def test_now_is_utc_aware(self) -> None:
        assert WallClock().now().tzinfo == timezone.utc

    def test_monotonic_nondecreasing(self) -> None:
        c = WallClock()
        assert c.monotonic() <= c.monotonic()

    def test_sleep_zero_returns(self) -> None:
        asyncio.run(WallClock().sleep(0))  # does not hang


class TestManualClock:
    def test_advance_releases_sleep(self) -> None:
        async def scenario() -> float:
            clock = ManualClock()
            woke = []

            async def sleeper() -> None:
                await clock.sleep(30)
                woke.append(clock.monotonic())

            task = asyncio.ensure_future(sleeper())
            await _settle()
            assert woke == []  # still asleep — no real time passed
            clock.advance(30)
            await _settle()
            await task
            return woke[0]

        assert asyncio.run(scenario()) == 30.0

    def test_partial_advance_does_not_release(self) -> None:
        async def scenario() -> bool:
            clock = ManualClock()
            woke = []
            task = asyncio.ensure_future(_wake(clock, 30, woke))
            await _settle()
            clock.advance(10)  # not enough
            await _settle()
            still_asleep = woke == []
            clock.advance(25)  # now past 30
            await _settle()
            await task
            return still_asleep and woke == [35.0]

        assert asyncio.run(scenario()) is True

    def test_now_tracks_virtual_time(self) -> None:
        clock = ManualClock(start=0.0)
        clock.advance(60)
        assert clock.monotonic() == 60.0
        assert clock.now().tzinfo == timezone.utc


async def _wake(clock: ManualClock, secs: float, out: list) -> None:
    await clock.sleep(secs)
    out.append(clock.monotonic())


class TestPeriodicTask:
    def test_ticks_on_each_interval(self) -> None:
        async def scenario() -> list:
            clock = ManualClock()
            ticks: list = []
            pt = PeriodicTask(10.0, lambda: ticks.append(clock.monotonic()), clock=clock)
            pt.start()
            await _settle()  # reach the first sleep
            for _ in range(3):
                clock.advance(10)
                await _settle()
            await pt.stop()
            return ticks

        # Three advances of one interval each → three ticks at 10/20/30.
        assert asyncio.run(scenario()) == [10.0, 20.0, 30.0]

    def test_callback_exception_does_not_kill_the_loop(self) -> None:
        async def scenario() -> int:
            clock = ManualClock()
            calls = {"n": 0}

            def boom() -> None:
                calls["n"] += 1
                raise ValueError("bad tick")

            pt = PeriodicTask(5.0, boom, clock=clock)
            pt.start()
            await _settle()
            for _ in range(2):
                clock.advance(5)
                await _settle()
            running = pt.running
            await pt.stop()
            return calls["n"] if running else -1

        # Both ticks fired despite each raising, and the loop was still running.
        assert asyncio.run(scenario()) == 2

    def test_stop_is_clean_and_idempotent(self) -> None:
        async def scenario() -> bool:
            pt = PeriodicTask(1.0, lambda: None, clock=ManualClock())
            pt.start()
            await _settle()
            await pt.stop()
            stopped = not pt.running
            await pt.stop()  # idempotent
            return stopped

        assert asyncio.run(scenario()) is True

    def test_default_clock_is_wallclock(self) -> None:
        pt = PeriodicTask(1.0, lambda: None)
        assert isinstance(pt._clock, WallClock)
