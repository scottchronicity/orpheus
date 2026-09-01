"""Unit tests for the shared history/analytics response helpers.

Locks in the DRY consolidation of three copy-pasted blocks (``even_sample``,
``paginate``, ``set_cache_control``) that lived inline across ``api/diagnostics``,
``api/entities`` and ``api/system``. These tests pin the *exact* historical
behaviour — including the deliberate drop-newest off-by-one and the magic 1000
page-size cap — so the refactor stays byte-identical.
"""

from fastapi import Response

from orpheus_ui.api._responses import Page, even_sample, paginate, set_cache_control


class TestEvenSample:
    def test_fewer_than_n_returns_all_in_order(self):
        """len(rows) < n -> every row, original order, unchanged."""
        rows = list(range(10))
        assert even_sample(rows, 500) == list(range(10))

    def test_default_n_is_500(self):
        """The default cap matches the historical inline literal (500)."""
        assert len(even_sample(list(range(600)))) == 500
        assert even_sample(list(range(500))) == list(range(500))

    def test_exactly_n_returns_all(self):
        """len(rows) == n hits the ``<=`` branch: everything, no sampling."""
        rows = [1, 2, 3]
        assert even_sample(rows, 3) == [1, 2, 3]

    def test_empty_returns_empty(self):
        assert even_sample([], 500) == []
        assert even_sample([]) == []

    def test_more_than_n_downsamples_to_n(self):
        """len(rows) > n -> exactly n rows picked at a constant stride."""
        rows = list(range(1000))
        result = even_sample(rows, 500)
        assert len(result) == 500
        # step = 1000 / 500 = 2.0 -> indices 0, 2, 4, ... 998
        assert result == [rows[int(i * 2.0)] for i in range(500)]
        assert result[0] == 0
        assert result[-1] == 998

    def test_selection_matches_historical_formula_non_integer_step(self):
        """A non-round stride must match ``rows[int(i * step)]`` exactly."""
        rows = list(range(750))
        step = 750 / 500
        expected = [rows[int(i * step)] for i in range(500)]
        assert even_sample(rows, 500) == expected
        assert len(even_sample(rows, 500)) == 500

    def test_drops_newest_point_by_design(self):
        """The deliberate off-by-one: the last (newest) row is never sampled
        when downsampling, because the max index int((n-1)*step) < len-1."""
        rows = list(range(1000))  # ascending == oldest..newest
        result = even_sample(rows, 500)
        assert rows[-1] == 999
        assert 999 not in result  # newest point dropped
        assert max(result) < 999

    def test_custom_n(self):
        rows = list(range(100))
        result = even_sample(rows, 10)
        assert len(result) == 10
        assert result == [rows[int(i * 10.0)] for i in range(10)]


class TestPaginate:
    def test_returns_page_namedtuple(self):
        pg = paginate(list(range(25)), page=1, page_size=10)
        assert isinstance(pg, Page)
        assert pg.items == list(range(10))
        assert pg.page == 1
        assert pg.page_size == 10
        assert pg.total_pages == 3

    def test_page_floor_clamped_to_one(self):
        """page < 1 clamps up to 1 (matches ``max(1, page)``)."""
        assert paginate(list(range(25)), page=0, page_size=10).page == 1
        assert paginate(list(range(25)), page=-5, page_size=10).page == 1

    def test_page_size_floor_clamped_to_one(self):
        assert paginate(list(range(25)), page=1, page_size=0).page_size == 1
        assert paginate(list(range(25)), page=1, page_size=-3).page_size == 1

    def test_page_size_capped_at_1000(self):
        """The magic 1000 cap is preserved."""
        pg = paginate(list(range(1500)), page=1, page_size=5000)
        assert pg.page_size == 1000
        assert len(pg.items) == 1000
        assert pg.total_pages == 2  # ceil(1500 / 1000)

    def test_last_page_partial_slice(self):
        pg = paginate(list(range(25)), page=3, page_size=10)
        assert pg.items == [20, 21, 22, 23, 24]
        assert pg.total_pages == 3

    def test_over_range_page_yields_empty_slice(self):
        """A page past the end returns [] but the clamped page echoes back."""
        pg = paginate(list(range(25)), page=99, page_size=10)
        assert pg.items == []
        assert pg.page == 99
        assert pg.total_pages == 3

    def test_empty_items_reports_one_page(self):
        pg = paginate([], page=1, page_size=10)
        assert pg.items == []
        assert pg.total_pages == 1
        assert pg.page == 1
        assert pg.page_size == 10

    def test_exact_multiple_total_pages(self):
        assert paginate(list(range(20)), page=1, page_size=10).total_pages == 2

    def test_items_is_a_slice_not_the_original(self):
        original = list(range(5))
        pg = paginate(original, page=1, page_size=10)
        assert pg.items == original
        assert pg.items is not original


class TestSetCacheControl:
    def test_default_stale_while_revalidate_is_3x(self):
        resp = Response()
        set_cache_control(resp, 10)
        assert (
            resp.headers["Cache-Control"]
            == "private, max-age=10, stale-while-revalidate=30"
        )
        assert resp.headers["Vary"] == "Authorization"

    def test_entities_five_second_window(self):
        """The /entities call site uses max_age=5 -> swr 15."""
        resp = Response()
        set_cache_control(resp, max_age=5)
        assert (
            resp.headers["Cache-Control"]
            == "private, max-age=5, stale-while-revalidate=15"
        )

    def test_explicit_stale_while_revalidate_overrides_default(self):
        """The system storage-history call site keeps max-age=30 / swr=60
        (not the 3x default of 90) — byte-identical to the old inline header."""
        resp = Response()
        set_cache_control(resp, max_age=30, stale_while_revalidate=60)
        assert (
            resp.headers["Cache-Control"]
            == "private, max-age=30, stale-while-revalidate=60"
        )
        assert resp.headers["Vary"] == "Authorization"
