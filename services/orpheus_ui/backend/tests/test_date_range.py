"""Unit tests for the shared ``resolve_date_range`` history-window helper.

Locks in the consolidation of the six copy-pasted date-range blocks: explicit
ISO bounds win, ``days`` (defaulted) provides a rolling fallback, and — the
bugfix — unparseable input raises a clean ``HTTPException(400)`` instead of a
bare ``ValueError`` that the endpoints turned into a 500.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from orpheus_ui.api._date_range import resolve_date_range


class TestResolveDateRange:
    def test_explicit_start_and_end_win(self):
        """ISO start/end are honoured; end_date snaps to end-of-day UTC."""
        start_dt, end_dt = resolve_date_range(None, "2026-01-01", "2026-01-07")

        assert start_dt == datetime(2026, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
        assert end_dt == datetime(
            2026, 1, 7, 23, 59, 59, 999999, tzinfo=timezone.utc
        )

    def test_z_suffix_is_accepted(self):
        """A trailing ``Z`` parses (Python 3.9 fromisoformat would reject it)."""
        start_dt, end_dt = resolve_date_range(
            None, "2026-02-17T08:00:00Z", "2026-02-17T00:00:00Z"
        )

        assert start_dt == datetime(2026, 2, 17, 8, 0, 0, 0, tzinfo=timezone.utc)
        # end_date is snapped to end-of-day regardless of the given time.
        assert end_dt == datetime(
            2026, 2, 17, 23, 59, 59, 999999, tzinfo=timezone.utc
        )

    def test_days_default_when_no_dates(self):
        """No explicit bounds -> rolling window of default_days back from now."""
        before = datetime.now(timezone.utc)
        start_dt, end_dt = resolve_date_range(None, None, None, default_days=7)
        after = datetime.now(timezone.utc)

        assert end_dt is not None and start_dt is not None
        # end_dt is ~now.
        assert before <= end_dt <= after
        # start_dt is ~7 days before now.
        assert before - timedelta(days=7) <= start_dt <= after - timedelta(days=7)

    def test_explicit_days_overrides_default(self):
        """A concrete ``days`` value drives the window size."""
        before = datetime.now(timezone.utc)
        start_dt, _ = resolve_date_range(3, None, None, default_days=7)
        after = datetime.now(timezone.utc)

        assert before - timedelta(days=3) <= start_dt <= after - timedelta(days=3)

    def test_days_falsy_falls_back_to_default(self):
        """``days=0`` is falsy and falls back to default_days (matches ``or``)."""
        before = datetime.now(timezone.utc)
        start_dt, _ = resolve_date_range(0, None, None, default_days=7)
        after = datetime.now(timezone.utc)

        assert before - timedelta(days=7) <= start_dt <= after - timedelta(days=7)

    def test_non_int_days_treated_as_absent(self):
        """A non-int ``days`` (e.g. an unresolved Query default in a direct
        unit-test call) is treated as absent, not fed to timedelta."""
        sentinel = object()
        before = datetime.now(timezone.utc)
        start_dt, _ = resolve_date_range(sentinel, None, None, default_days=5)  # type: ignore[arg-type]
        after = datetime.now(timezone.utc)

        assert before - timedelta(days=5) <= start_dt <= after - timedelta(days=5)

    def test_default_days_none_leaves_unbounded(self):
        """The entities semantics: no rolling fallback, absent bounds -> None."""
        start_dt, end_dt = resolve_date_range(None, None, None, default_days=None)

        assert start_dt is None
        assert end_dt is None

    def test_default_days_none_with_only_end(self):
        """default_days=None: only end_date given -> (None, end-of-day)."""
        start_dt, end_dt = resolve_date_range(
            None, None, "2026-03-15", default_days=None
        )

        assert start_dt is None
        assert end_dt == datetime(
            2026, 3, 15, 23, 59, 59, 999999, tzinfo=timezone.utc
        )

    def test_bad_start_date_raises_400(self):
        """The bugfix: garbage start_date -> HTTPException(400), not ValueError."""
        with pytest.raises(HTTPException) as exc_info:
            resolve_date_range(None, "garbage", None)
        assert exc_info.value.status_code == 400
        assert "start_date" in exc_info.value.detail

    def test_bad_end_date_raises_400(self):
        """Garbage end_date -> HTTPException(400)."""
        with pytest.raises(HTTPException) as exc_info:
            resolve_date_range(None, "2026-01-01", "not-a-date")
        assert exc_info.value.status_code == 400
        assert "end_date" in exc_info.value.detail

    def test_explicit_start_after_end_raises_400(self):
        """An inverted EXPLICIT window is caller error -> 400, not a silent
        every-row-excluded query that renders as "no data"."""
        with pytest.raises(HTTPException) as exc_info:
            resolve_date_range(None, "2026-02-01", "2026-01-01")
        assert exc_info.value.status_code == 400
        assert "start_date" in exc_info.value.detail

    def test_old_end_date_alone_keeps_the_rolling_fallback_behavior(self):
        """The 400 guard applies to EXPLICIT bounds only: an old end_date with
        no start_date under the rolling fallback still resolves (historically a
        silently-empty result, not an error)."""
        start_dt, end_dt = resolve_date_range(None, None, "2020-01-01", default_days=7)

        assert end_dt == datetime(2020, 1, 1, 23, 59, 59, 999999, tzinfo=timezone.utc)
        assert start_dt > end_dt  # inverted by the fallback; caller sees empty, not 400
