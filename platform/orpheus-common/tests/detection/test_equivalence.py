"""Tests for the TaxonomyEquivalenceDB — bidirectional, transitive,
confidence-weighted, with negative assertions."""

from __future__ import annotations

from pathlib import Path

import pytest

from orpheus_common.detection import (
    TaxonomyEquivalenceDB,
    TaxonomyRef,
    expand_species_filter,
)


@pytest.fixture
def db(tmp_path: Path) -> TaxonomyEquivalenceDB:
    """Fresh DB per test — no cross-test contamination."""
    return TaxonomyEquivalenceDB(db_path=tmp_path / "test_equivalence.db")


def _crow_ebird() -> TaxonomyRef:
    return TaxonomyRef(namespace="ebird", id="amecro", common_name="American Crow")


def _crow_ioc() -> TaxonomyRef:
    return TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos")


def _crow_audioset() -> TaxonomyRef:
    return TaxonomyRef(namespace="audioset", id="/m/04s8yn", common_name="Crow")


def _raven_ioc() -> TaxonomyRef:
    return TaxonomyRef(namespace="ioc", id="Corvus corax")


class TestExpandSpeciesFilter:
    """expand_species_filter walks the equivalence graph so a search term finds
    every equivalent TaxonomyRef (cross-classifier identity). Lifted from the UI
    backend; it's privacy-load-bearing for the public site, so it must expand the
    same audited way everywhere. The fixture exercises a real corvid pair."""

    def _seed_corvid(self, db: TaxonomyEquivalenceDB) -> None:
        db.record_equivalence(_crow_ebird(), _crow_ioc())
        db.record_equivalence(_crow_ioc(), _crow_audioset())

    def test_free_form_term_expands_to_all_equivalents(
        self, db: TaxonomyEquivalenceDB
    ) -> None:
        self._seed_corvid(db)
        legacy, taxa = expand_species_filter("amecro", eq_db=db)
        assert "amecro" in legacy
        assert ("ebird", "amecro") in taxa
        assert ("ioc", "Corvus brachyrhynchos") in taxa
        assert ("audioset", "/m/04s8yn") in taxa

    def test_namespace_id_pair_expands(self, db: TaxonomyEquivalenceDB) -> None:
        self._seed_corvid(db)
        _, taxa = expand_species_filter("ioc:Corvus brachyrhynchos", eq_db=db)
        assert ("ebird", "amecro") in taxa
        assert ("audioset", "/m/04s8yn") in taxa

    def test_unknown_term_yields_only_legacy(
        self, db: TaxonomyEquivalenceDB
    ) -> None:
        legacy, taxa = expand_species_filter("definitely-not-a-species", eq_db=db)
        assert legacy == {"definitely-not-a-species"}
        assert taxa == set()  # no edges -> no cross-namespace expansion


class TestSchema:
    """The schema is created idempotently on first construction."""

    def test_first_construction_creates_tables(self, tmp_path: Path) -> None:
        db_path = tmp_path / "fresh.db"
        TaxonomyEquivalenceDB(db_path=db_path)
        assert db_path.exists()

    def test_second_construction_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "twice.db"
        TaxonomyEquivalenceDB(db_path=db_path)
        TaxonomyEquivalenceDB(db_path=db_path)  # no crash, no duplicate-table error


class TestReflexivity:
    """``is_equivalent(a, a)`` and ``equivalent_taxa(a)`` include ``a`` itself."""

    def test_is_equivalent_to_self_without_a_row(self, db: TaxonomyEquivalenceDB) -> None:
        assert db.is_equivalent(_crow_ebird(), _crow_ebird()) is True

    def test_equivalent_taxa_always_includes_self(self, db: TaxonomyEquivalenceDB) -> None:
        result = db.equivalent_taxa(_crow_ebird())
        assert _crow_ebird() in result


class TestBidirectionalStorage:
    """Recording ``a ↔ b`` makes ``is_equivalent`` symmetric."""

    def test_symmetry(self, db: TaxonomyEquivalenceDB) -> None:
        db.record_equivalence(_crow_ebird(), _crow_audioset(), confidence=1.0)
        assert db.is_equivalent(_crow_ebird(), _crow_audioset()) is True
        assert db.is_equivalent(_crow_audioset(), _crow_ebird()) is True

    def test_equivalent_taxa_returns_both_directions(
        self, db: TaxonomyEquivalenceDB
    ) -> None:
        db.record_equivalence(_crow_ebird(), _crow_audioset())
        from_ebird = db.equivalent_taxa(_crow_ebird())
        from_audioset = db.equivalent_taxa(_crow_audioset())
        # Compare as sets of (namespace, id) tuples since TaxonomyRef common_name
        # may differ between starting points.
        a_set = {(t.namespace, t.id) for t in from_ebird}
        b_set = {(t.namespace, t.id) for t in from_audioset}
        assert a_set == b_set


class TestTransitivity:
    """If ``a ≡ b`` and ``b ≡ c``, then ``a ≡ c`` — proven via BFS."""

    def test_two_hop(self, db: TaxonomyEquivalenceDB) -> None:
        db.record_equivalence(_crow_ebird(), _crow_ioc())
        db.record_equivalence(_crow_ioc(), _crow_audioset())
        # No direct ebird ↔ audioset row exists.
        assert db.is_equivalent(_crow_ebird(), _crow_audioset()) is True

    def test_three_hop(self, db: TaxonomyEquivalenceDB) -> None:
        a = TaxonomyRef(namespace="ebird", id="a")
        b = TaxonomyRef(namespace="ebird", id="b")
        c = TaxonomyRef(namespace="ebird", id="c")
        d = TaxonomyRef(namespace="ebird", id="d")
        db.record_equivalence(a, b)
        db.record_equivalence(b, c)
        db.record_equivalence(c, d)
        result = {(t.namespace, t.id) for t in db.equivalent_taxa(a)}
        assert ("ebird", "d") in result

    def test_disconnected_components_stay_separate(
        self, db: TaxonomyEquivalenceDB
    ) -> None:
        db.record_equivalence(_crow_ebird(), _crow_audioset())
        # Robin is in a separate component.
        robin = TaxonomyRef(namespace="ebird", id="amerob")
        result = {(t.namespace, t.id) for t in db.equivalent_taxa(_crow_ebird())}
        assert ("ebird", "amerob") not in result
        assert db.is_equivalent(_crow_ebird(), robin) is False


class TestConfidenceThreshold:
    """Edges below the threshold are not walked."""

    def test_low_confidence_edge_blocked(self, db: TaxonomyEquivalenceDB) -> None:
        db.record_equivalence(_crow_ebird(), _crow_audioset(), confidence=0.4)
        # Default threshold is 0.5 — the edge isn't walked.
        assert db.is_equivalent(_crow_ebird(), _crow_audioset()) is False

    def test_lower_threshold_lets_low_confidence_through(
        self, db: TaxonomyEquivalenceDB
    ) -> None:
        db.record_equivalence(_crow_ebird(), _crow_audioset(), confidence=0.4)
        assert (
            db.is_equivalent(_crow_ebird(), _crow_audioset(), min_confidence=0.3) is True
        )

    def test_high_threshold_blocks_low_confidence_chain(
        self, db: TaxonomyEquivalenceDB
    ) -> None:
        db.record_equivalence(_crow_ebird(), _crow_ioc(), confidence=0.95)
        db.record_equivalence(_crow_ioc(), _crow_audioset(), confidence=0.6)
        # Chain breaks at the 0.6 edge when threshold is 0.8.
        assert (
            db.is_equivalent(_crow_ebird(), _crow_audioset(), min_confidence=0.8)
            is False
        )


class TestNonEquivalence:
    """Negative assertions block edges even if equivalence rows exist."""

    def test_non_equivalence_blocks_direct_edge(
        self, db: TaxonomyEquivalenceDB
    ) -> None:
        db.record_equivalence(_crow_ebird(), _crow_audioset())
        db.record_non_equivalence(_crow_ebird(), _crow_audioset(), source="manual")
        assert db.is_equivalent(_crow_ebird(), _crow_audioset()) is False

    def test_non_equivalence_breaks_transitive_chain(
        self, db: TaxonomyEquivalenceDB
    ) -> None:
        db.record_equivalence(_crow_ebird(), _crow_ioc())
        db.record_equivalence(_crow_ioc(), _crow_audioset())
        # Block the middle edge.
        db.record_non_equivalence(_crow_ioc(), _crow_audioset())
        assert db.is_equivalent(_crow_ebird(), _crow_audioset()) is False
        # The first edge still works.
        assert db.is_equivalent(_crow_ebird(), _crow_ioc()) is True

    def test_cannot_assert_self_non_equivalence(
        self, db: TaxonomyEquivalenceDB
    ) -> None:
        with pytest.raises(ValueError, match="ref and itself"):
            db.record_non_equivalence(_crow_ebird(), _crow_ebird())


class TestPendingReview:
    """Auto-discovered rows can land as pending_review and be ignored until
    promoted to accepted."""

    def test_pending_rows_not_walked_by_default(self, db: TaxonomyEquivalenceDB) -> None:
        db.record_equivalence(
            _crow_ebird(), _crow_audioset(), confidence=0.75, status="pending_review"
        )
        assert db.is_equivalent(_crow_ebird(), _crow_audioset()) is False

    def test_pending_rows_appear_in_review_list(
        self, db: TaxonomyEquivalenceDB
    ) -> None:
        db.record_equivalence(
            _crow_ebird(),
            _crow_audioset(),
            confidence=0.75,
            source="auto_discovered",
            status="pending_review",
        )
        pending = db.list_pending_review()
        assert len(pending) == 1
        pair_ids = {(pending[0]["a"].namespace, pending[0]["a"].id),
                    (pending[0]["b"].namespace, pending[0]["b"].id)}
        assert pair_ids == {("ebird", "amecro"), ("audioset", "/m/04s8yn")}

    def test_accept_promotes_pending(self, db: TaxonomyEquivalenceDB) -> None:
        db.record_equivalence(
            _crow_ebird(), _crow_audioset(), confidence=0.8, status="pending_review"
        )
        assert db.is_equivalent(_crow_ebird(), _crow_audioset()) is False
        db.accept_pending(_crow_ebird(), _crow_audioset())
        assert db.is_equivalent(_crow_ebird(), _crow_audioset()) is True


class TestIdempotentRecords:
    """Re-recording the same pair updates rather than duplicates."""

    def test_re_record_updates_confidence(self, db: TaxonomyEquivalenceDB) -> None:
        db.record_equivalence(_crow_ebird(), _crow_audioset(), confidence=0.6)
        db.record_equivalence(_crow_ebird(), _crow_audioset(), confidence=0.95)
        # The updated confidence is what's queried.
        assert (
            db.is_equivalent(
                _crow_ebird(), _crow_audioset(), min_confidence=0.9
            )
            is True
        )


class TestValidation:
    """Constructor and write validation."""

    def test_invalid_confidence(self, db: TaxonomyEquivalenceDB) -> None:
        with pytest.raises(ValueError, match="confidence"):
            db.record_equivalence(_crow_ebird(), _crow_audioset(), confidence=1.5)
        with pytest.raises(ValueError, match="confidence"):
            db.record_equivalence(_crow_ebird(), _crow_audioset(), confidence=-0.1)

    def test_invalid_status(self, db: TaxonomyEquivalenceDB) -> None:
        with pytest.raises(ValueError, match="status"):
            db.record_equivalence(
                _crow_ebird(), _crow_audioset(), status="not_a_status"
            )


class TestRealCorvidScenario:
    """End-to-end: three classifiers' crow refs all become equivalent."""

    def test_three_classifier_crow_chain(self, db: TaxonomyEquivalenceDB) -> None:
        # BirdNET emits (ioc, "Corvus brachyrhynchos")
        # crow-tools doesn't emit a TaxonomyRef (call-type analyzer)
        # PANNs emits (audioset, "/m/04s8yn")
        # Seed: the cross-namespace bridge.
        db.record_equivalence(_crow_ioc(), _crow_audioset(), source="seed")

        # A reader looking up "all known refs for the IOC crow" gets both.
        all_crow = db.equivalent_taxa(_crow_ioc())
        as_keys = {(t.namespace, t.id) for t in all_crow}
        assert ("ioc", "Corvus brachyrhynchos") in as_keys
        assert ("audioset", "/m/04s8yn") in as_keys

    def test_raven_does_not_merge_with_crow(self, db: TaxonomyEquivalenceDB) -> None:
        db.record_equivalence(_crow_ioc(), _crow_audioset())
        # Raven is a different species — no equivalence row.
        assert db.is_equivalent(_raven_ioc(), _crow_ioc()) is False
        assert db.is_equivalent(_raven_ioc(), _crow_audioset()) is False
